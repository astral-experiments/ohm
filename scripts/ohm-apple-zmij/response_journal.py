"""Record real Endpoint Security creation/deletion for eligible filenames during one native command."""
from calendar import timegm
from collections import Counter,defaultdict
import hashlib,json,os
from pathlib import Path,PurePosixPath
import re,secrets,subprocess,tempfile,threading,time

from study import need
from xcode_response import NAME

KINDS={'create','rename','link','unlink'}
DATE=re.compile(r'(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)\.(\d{9})Z')

def time_ns(value):
    m=DATE.fullmatch(value);need(m is not None,'unsupported kernel timespec')
    return timegm(time.strptime(m[1],'%Y-%m-%dT%H:%M:%S'))*10**9+int(m[2])

def fs_stamp(s):
    return [s['st_dev'],s['st_ino'],s['st_mode'],s['st_uid'],s['st_nlink'],s['st_size'],
            time_ns(s['st_mtimespec']),time_ns(s['st_ctimespec'])]

def key(path):
    p=PurePosixPath(path);need(p.is_absolute() and '..' not in p.parts,'foreign kernel pathname')
    for root in ('/private/var','/private/tmp'):
        if str(p)==root or str(p).startswith(root+'/'):return str(p)[len('/private'):]
    return str(p)

def fs_paths(kind,fields):
    """Use Apple's actual event union layout. Preserve both ends of every rename and link."""
    def file(f):
        need(not f['path_truncated'],'truncated relevant kernel path');return f['path']
    def named(directory,n):
        need(n and '/' not in n and n not in ('.','..'),'noncomponent kernel name');return str(PurePosixPath(file(directory))/n)
    def dest(v):
        d=v['destination'];t=v['destination_type']
        if t==0:return file(d['existing_file'])
        need(t==1 and 'new_path' in d,'unsupported kernel file destination');n=d['new_path'];return named(n['dir'],n['filename'])
    if kind=='create':return [dest(fields)]
    if kind=='rename':return [file(fields['source']),dest(fields)]
    if kind=='unlink':return [file(fields['target'])]
    need(kind=='link','unknown lifecycle event');return [file(fields['source']),named(fields['target_dir'],fields['target_filename'])]

def frames(stream):
    chunks=[];total=0
    for line in stream:
        if not chunks and not line.strip():continue
        chunks.append(line);total+=len(line);need(total<8*2**20,'oversized kernel lifecycle record')
        if line.startswith(b'}') or len(chunks)==1 and line.strip().endswith(b'}'):
            yield b''.join(chunks);chunks=[];total=0
    need(not chunks,'incomplete kernel lifecycle frame')

class FileJournal:
    def __init__(self,root):
        self.root=Path(root).resolve(strict=True);self.prefix='ohm-response-custody-'+secrets.token_hex(10)
        self.events=defaultdict(list);self.seqs={};self.counts=Counter();self.first=None;self.last=None
        self.errors=[];self.lock=threading.Lock();self.seals={};self.proc=None;self.thread=None;self.stderr=None
        self.roll=hashlib.sha256()
    def __enter__(self):
        self.stderr=tempfile.TemporaryFile()
        self.proc=subprocess.Popen(['sudo','-n','/usr/bin/eslogger','create','rename','link','unlink'],stdout=subprocess.PIPE,stderr=self.stderr,start_new_session=True)
        self.thread=threading.Thread(target=self.pump,daemon=True,name='response ES file lifecycle');self.thread.start()
        try:self.seals['start']=self.barrier();return self
        except BaseException:self.close();raise
    def pump(self):
        try:
            for data in frames(self.proc.stdout):
                r=json.loads(data);kind,=r['event'];seq=r['seq_num'];glob=r['global_seq_num']
                need(kind in KINDS and isinstance(seq,int) and isinstance(glob,int),'non-enrolled kernel event')
                with self.lock:
                    if kind in self.seqs and seq!=self.seqs[kind]+1:self.errors.append('lost '+kind+' lifecycle sequence')
                    if self.last is not None and glob!=self.last+1:self.errors.append('lost global filesystem lifecycle sequence')
                    self.seqs[kind]=seq;self.counts[kind]+=1;self.first=glob if self.first is None else self.first;self.last=glob
                    self.roll.update(hashlib.sha256(data).digest())
                    # The exact root and a specific filename are verified before retention. All other
                    # processes' paths and arguments are discarded after the continuity check.
                    if b'response-' not in data:continue
                    for n in fs_paths(kind,r['event'][kind]):
                        p=PurePosixPath(n)
                        if key(p.parent)==key(self.root) and (NAME.fullmatch(p.name) or p.name.startswith(self.prefix)):
                            need(len(self.events)<512,'too many eligible names')
                            self.events[key(p)].append(r)
        except Exception as e:self.errors.append(type(e).__name__+': '+str(e))
    def barrier(self):
        limit=time.monotonic()+9;i=0
        while time.monotonic()<limit:
            need(not self.errors and self.proc.poll() is None,'untrusted kernel lifecycle '+str(self.errors[:2]))
            n=self.prefix+'-'+str(time.monotonic_ns())+'-'+str(i);p=self.root/n
            with p.open('xb') as f:s=os.fstat(f.fileno())
            p.unlink()
            stop=time.monotonic()+.2
            while time.monotonic()<stop:
                with self.lock:visits=list(self.events.get(key(p),[]))
                if len(visits)>=2:
                    need([next(iter(r['event'])) for r in visits]==['create','unlink'],'kernel lifecycle barrier mismatch')
                    witness=visits[-1];target=witness['event']['unlink']['target']['stat']
                    need(target['st_ino']==s.st_ino and target['st_dev']==s.st_dev and witness['process']['audit_token']['pid']==os.getpid(),'kernel lifetime barrier does not identify our original file')
                    return {'path':str(p),'identity':[s.st_dev,s.st_ino,s.st_uid],'pid':os.getpid(),
                            'mach_time':witness['mach_time'],'global_seq':witness['global_seq_num']}
                time.sleep(.005)
            i+=1
        raise RuntimeError('no bounded real kernel create/unlink barrier')
    def finish(self):
        self.seals['end']=self.barrier()
        with self.lock:
            need(not self.errors,'files were missed during native capture: '+str(self.errors[:2]))
            return {'start':self.seals['start'],'end':self.seals['end'],'first_seq':self.first,'last_seq':self.last,
                    'counts':dict(self.counts),'digest':self.roll.hexdigest()}
    def close(self):
        if self.proc and self.proc.poll() is None:
            subprocess.run(['sudo','-n','/bin/kill','-TERM',str(self.proc.pid)],capture_output=True)
            try:self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:self.proc.kill()
        if self.thread:self.thread.join(timeout=2)
        if self.stderr:self.stderr.close()
    def __exit__(self,*unused):self.close()
