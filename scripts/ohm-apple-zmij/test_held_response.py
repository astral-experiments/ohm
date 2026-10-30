"""Retrospective refusals, synthetic inode lifecycles, then real Xcode direct and long links."""
from copy import deepcopy
from datetime import datetime,timezone
import gzip,json,os
from pathlib import Path
import stat,subprocess,sys,tempfile,time,unittest

sys.path.insert(0,str(Path(__file__).resolve().parent))
from execs import ExecTrace
from response_custody import CaptureRows,command,resolved,seal
from response_handles import DirectoryHandles
from response_journal import key
from study import compress_bytes,digest,need,save
from xcode_response import darwin_user_temp,stamp

def kernel_stamp(s):
    time_text=lambda n:datetime.fromtimestamp(n//10**9,timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')+'.'+str(n%10**9).zfill(9)+'Z'
    return {'st_dev':s.st_dev,'st_ino':s.st_ino,'st_mode':s.st_mode,'st_uid':s.st_uid,'st_nlink':s.st_nlink,'st_size':s.st_size,
            'st_mtimespec':time_text(s.st_mtime_ns),'st_ctimespec':time_text(s.st_ctime_ns)}

def synthetic(root,mutator=None):
    args=['/tool/clang',str(root/'stable.o'),'-o',str(root/'output')];path=root/'response-a123fd.txt'
    body=(' '.join('"'+x+'"' for x in args[1:])+'\n').encode()
    parent={'pid':13,'pgid':9,'ppid':2,'seq':7,'path':'/tool/clang','cdhash':'aa','argv':args,'es_pidversion':381,'es_euid':os.getuid(),'es_mach_time':110}
    ld={'pid':14,'pgid':9,'ppid':13,'seq':8,'path':'/tool/ld','cdhash':'bb','argv':['/tool/ld','@'+str(path)],'es_pidversion':383,'es_euid':os.getuid(),'es_mach_time':130}
    program={'audit_token':{'pid':13,'pidversion':381,'euid':os.getuid()},'group_id':9,'executable':{'path':'/tool/clang','path_truncated':False},'cdhash':'aa'}
    class Journal:
        def finish(self):
            return {'first_seq':5,'last_seq':9,'counts':{'create':3,'unlink':2},'digest':'a'*64,
                    'start':{'global_seq':5,'mach_time':100,'pid':os.getpid(),'identity':[1,2,os.getuid()]},
                    'end':{'global_seq':9,'mach_time':150,'pid':os.getpid(),'identity':[1,3,os.getuid()]}}
    j=Journal()
    with DirectoryHandles([root],native=False) as h:
        with path.open('xb') as f:
            made=kernel_stamp(os.fstat(f.fileno()));h.scan();f.write(body)
        gone=kernel_stamp(path.stat())
        shell=lambda:{'path_truncated':False,'path':str(path)}
        create={'event':{'create':{'destination_type':0,'destination':{'existing_file':{**shell(),'stat':made}}}},'process':program,'global_seq_num':6,'mach_time':120}
        unlink={'event':{'unlink':{'target':{**shell(),'stat':gone},'parent_dir':{'path':str(root),'path_truncated':False,'stat':kernel_stamp(root.stat())}}},'process':program,'global_seq_num':8,'mach_time':140}
        j.events={key(path):[create,unlink]}
        path.unlink()
        if mutator:mutator(h,j,path)
        rows=CaptureRows([parent,ld]);seal(rows,h,j);return rows

def reject(f):
    try:f()
    except (RuntimeError,KeyError,ValueError,IndexError):return
    raise AssertionError('forged/incomplete link was accepted')

def negatives(events):
    selected=next(i for i,x in enumerate(events) if x.get('xcode_response'))
    cases=('missing','stale-body','replaced-inode','missing-create','unrelated-unlink','early-unlink','late-create','different-pidversion',
           'other-directory','hard-linked','unstable-after','lost-global-event','unbounded-duration','repeated-name','different-ownership','wrong-parent-operands')
    for which in cases:
        src=deepcopy(events);e=src[selected];p=e['xcode_response'];c=p['held_custody'];h=c['fd'];born,gone=c['events']
        if which=='missing':del e['xcode_response']
        elif which=='stale-body':p['sha256']='0'*64
        elif which=='replaced-inode':h['initial'][1]+=1
        elif which=='missing-create':c['events']=c['events'][1:]
        elif which=='unrelated-unlink':gone['process']['audit_token']['pid']+=1
        elif which=='early-unlink':gone['mach_time']=e['es_mach_time']-1
        elif which=='late-create':born['mach_time']=e['es_mach_time']+1
        elif which=='different-pidversion':born['process']['audit_token']['pidversion']+=1
        elif which=='other-directory':h['root'][1]+=1
        elif which=='hard-linked':h['initial'][4]=2
        elif which=='unstable-after':h['final_after'][5]+=1
        elif which=='lost-global-event':c['journal']['last_seq']+=1
        elif which=='unbounded-duration':h['read_ns']+=2500*10**9
        elif which=='repeated-name':src.append(deepcopy(e))
        elif which=='different-ownership':h['initial'][3]+=1
        elif which=='wrong-parent-operands':
            a=next(v for v in src[:selected][::-1] if v['pid']==e['ppid'])
            i=next(i for i,k in enumerate(a['argv']) if k.startswith('/') and k.endswith('.o'))
            a['argv'][i]+='.replaced.o'
        reject(lambda:list(resolved(src)))
    return len(cases)

class Checks(unittest.TestCase):
    def test_preopened_empty_file(self):
        with tempfile.TemporaryDirectory() as root:
            events=synthetic(Path(root));self.assertEqual(len(list(resolved(events))),2);self.assertEqual(negatives(events),16)
    def test_recreated_basename(self):
        def new(h,j,path):
            path.write_bytes(b'another file with the same name');h.scan();path.unlink()
        with tempfile.TemporaryDirectory() as root:self.assertRaises(RuntimeError,synthetic,Path(root),new)
    def test_kernel_rename(self):
        def rename(h,j,path):j.events[key(path)].insert(1,{'event':{'rename':{}},'mach_time':123})
        with tempfile.TemporaryDirectory() as root:self.assertRaises(RuntimeError,synthetic,Path(root),rename)
    def test_missing_original_fd(self):
        def missed(h,j,path):
            k=(path.parent,path.name);records=h.files.pop(k)
            for e in records.values():os.close(e.fd)
        with tempfile.TemporaryDirectory() as root:self.assertRaises(RuntimeError,synthetic,Path(root),missed)
    def test_initial_linked_alias(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);p=root/'response-a812ef.txt';p.write_bytes(b'fixture')
            with DirectoryHandles([root],native=False) as h:
                h.scan();self.assertIn(p.name,h.initial[root]);self.assertFalse(h.files)

def native(root):
    root=root.resolve();root.mkdir(parents=True,exist_ok=True);out=root/'receipts';out.mkdir(exist_ok=True)
    work=root/'long';work.mkdir();src,obj,exe=[work/n for n in ('main.c','main.o','probe')]
    src.write_text('extern int puts(const char *);\nvolatile const unsigned char fixture[64*1024*1024]={29};\nint main(void){return fixture[0]==29 ? (puts("29"),0) : 1;}\n')
    cc=subprocess.check_output(['/usr/bin/xcrun','--find','clang'],text=True).strip();sdk=subprocess.check_output(['/usr/bin/xcrun','--sdk','macosx','--show-sdk-path'],text=True).strip()
    subprocess.run([cc,'-isysroot',sdk,'-c',src,'-o',obj],check=True)
    base=[cc,'-isysroot',sdk,str(obj),'-o',str(exe)];opts=[]
    for i in range(825):
        d=work/(f'{i:04}-'+'a'*96);d.mkdir();opts.append('-L'+str(d))
    trace=ExecTrace();result={}
    try:
        trace.ready()
        for name,args in [('direct',base),('response-1',base+opts),('response-2',base+opts)]:
            capture=CaptureRows();save(out/(name+'-temp.json'),{'darwin_user_temp':str(darwin_user_temp())})
            try:
                with (out/(name+'.out')).open('wb') as o,(out/(name+'.err')).open('wb') as e:
                    code,raw=command(trace.command,args,env=dict(os.environ),cwd=work,out=o,err=e,capture_rows=capture,timeout=120)
            finally:compress_bytes(out/(name+'-exec.json.gz'),json.dumps(capture,separators=(',',':')).encode())
            need(code==0 and raw is capture,'failed compiled native fixture')
            eargv=list(resolved(raw))
            ld,=[v for v in raw if Path(v['path']).name in ('ld','ld64','ld-classic','ld-prime')]
            actual,=[v for v in eargv if v['pid']==ld['pid'] and v['seq']==ld['seq']]
            need(bool(ld.get('xcode_response'))==(name!='direct') and str(obj) in actual['argv'] and str(exe) in actual['argv'],'failed expected real Xcode response shape')
            b=exe.read_bytes();value=subprocess.check_output([str(exe)]);need(value==b'29\n','wrong real native program')
            entry={'whole_macho':digest(b),'bytes':len(b),'stdout':value.decode(),'source_object':digest(obj.read_bytes()),'real_output':str(exe),'signed_linker_pid':ld['pid'],'exact_raw_args':ld['argv']}
            if name!='direct':
                p=ld['xcode_response'];entry.update(sha256=p['sha256'],held_inode=p['identity'][:2],actual_parent=ld['ppid'],real_adversarial_refusals=negatives(raw))
            result[name]=entry;exe.unlink()
        need(len({x['whole_macho'] for x in result.values()})==1,'direct and indirect actual program bytes differed')
        need(result['response-1']['exact_raw_args']!=result['response-2']['exact_raw_args'],'response basename not independent across installations')
        save(out/'terminal.json',result);print(json.dumps(result,sort_keys=True),flush=True)
    except BaseException as exc:
        save(out/'failure.json',{'failure':str(exc),'accepted_completed':result});raise
    finally:trace.close()

if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='native':native(Path(sys.argv[2]))
    else:unittest.main()
