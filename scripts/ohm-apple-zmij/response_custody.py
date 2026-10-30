"""Bind an original ld @file to a pre-opened inode, its actual clang creator and unlinker."""
import base64
from collections import Counter
from contextlib import ExitStack
import os
from pathlib import Path
import stat

from response_handles import DirectoryHandles, MAX_SECONDS
from response_journal import FileJournal, fs_paths,fs_stamp,key
from study import need
import xcode_response as original

TAG='kqueue-fd-es-create-unlink-v1'
LD=original.LD

def actor(record):
    p=record['process'];a=p['audit_token'];f=p['executable']
    need(not f['path_truncated'] and p.get('cdhash'),'unidentified kernel filesystem actor')
    return [a['pid'],a['pidversion'],p['group_id'],f['path'],p['cdhash'],a['euid']]

def verify_held(event,parent):
    """Reopen only observed raw events. Every time and inode check also applies offline."""
    argv=event['argv'];p=event.get('xcode_response');need(p and not event.get('response_observer_error'),'missing held original response')
    c=p.get('held_custody') or {};need(c.get('version')==TAG,'response was not enrolled under the held-inode method')
    path=original.file_name(argv);q=c['events'];window=c['journal'];h=c['fd'];need(len(q)==2,'ambiguous matching filename or filesystem operation')
    create,unlink=q
    need(list(create['event'])==['create'] and list(unlink['event'])==['unlink'] and
         [key(v) for v in fs_paths('create',create['event']['create'])]==[key(path)] and
         [key(v) for v in fs_paths('unlink',unlink['event']['unlink'])]==[key(path)],'wrong kernel file lifetime or intervening rename/link')
    need(parent and Path(parent['path']).name=='clang' and parent['pid']==event['ppid'] and parent['pgid']==event['pgid']
         and parent['seq']<event['seq'] and Path(parent['path']).parent==Path(event['path']).parent,'different kernel parent driver')
    expected=[parent['pid'],parent['es_pidversion'],parent['pgid'],parent['path'],parent['cdhash'],parent['es_euid']]
    need(actor(create)==actor(unlink)==expected and parent['es_euid']==event['es_euid'],'response did not belong to the actual kernel clang parent')
    lo,hi=window['start'],window['end']
    need(window['first_seq']<=lo['global_seq']<create['global_seq_num']<unlink['global_seq_num']<hi['global_seq']<=window['last_seq']
         and window['last_seq']-window['first_seq']+1==sum(window['counts'].values()) and len(window['digest'])==64,'missing contiguous kernel file events')
    need(lo['mach_time']<parent['es_mach_time']<create['mach_time']<event['es_mach_time']<unlink['mach_time']<hi['mach_time'],
         'actual ld exec was not bracketed by its parent file operations')
    opened=create['event']['create'];deleted=unlink['event']['unlink'];need(opened['destination_type']==0,'kernel create did not provide the new original inode')
    made=fs_stamp(opened['destination']['existing_file']['stat']);gone=fs_stamp(deleted['target']['stat']);fd=h['initial'];last=h['final_before'];root=deleted['parent_dir']
    need(not root['path_truncated'] and key(root['path'])==key(path.parent) and key(p['temporary'])==key(path.parent)
         and [root['stat'][k] for k in ('st_dev','st_ino','st_uid')]==h['root'] and h['root'][2]==expected[-1],'different source temporary directory')
    need(fd[:4]==made[:4]==last[:4]==gone[:4] and fd[3]==expected[-1] and stat.S_ISREG(fd[2]) and
         fd[4]==made[4]==gone[4]==1 and last[4]==0 and 0<=fd[5]<=last[5] and 0<=made[5]<=last[5] and
         last==h['final_after'] and last[5:7]==gone[5:7] and h['complete_unlink']==p['identity']==gone,
         'creating, held, deleted and final native inode identities do not agree')
    need(0<last[5]==h['read_bytes']<=original.LIMIT and h['unique_inodes']==1
         and h['window_start_ns']<=h['opened_ns']<=h['read_ns']<=h['window_start_ns']+MAX_SECONDS*10**9,'unbounded held-fd lifetime or file size')
    need(lo['pid']==hi['pid'] and lo['pid']>0 and lo['identity'][2]==hi['identity'][2]==fd[3],'unowned subscriber fences')
    data=base64.b64decode(p['bytes'],validate=True);need(len(data)==last[5] and original.digest(data)==p['sha256'] and p['raw_argv']==original.digest(original.packed(argv)),'saved physical bytes or raw argv changed')
    return data

def resolved(events):
    events=list(events);counts=Counter(key(original.file_name(e['argv'])) for e in events
        if Path(e['path']).name in LD and any(a.startswith('@') for a in e['argv'][1:]))
    need(all(v==1 for v in counts.values()),'one pathname was reused by multiple physical ld executions')
    history={}
    for event in events:
        need(not event.get('response_observer_error'),'unqualified linker response: '+str(event.get('response_observer_error')))
        if Path(event['path']).name in LD and any(a.startswith('@') for a in event['argv'][1:]):
            verify_held(event,history.get(event['ppid']))
        history[event['pid']]=event
    # The reused parser also authenticates direct inputs and the unique -o against that same clang.
    yield from original.resolved(events)

class CaptureRows(list):
    @staticmethod
    def extra_event_fields(raw,process):
        a=process['audit_token'];return {'es_mach_time':raw['mach_time'],'es_pidversion':a['pidversion'],'es_euid':a['euid']}

def seal(rows,hand,journal):
    summary=journal.finish();targets=[(i,e) for i,e in enumerate(rows) if Path(e['path']).name in LD and any(a.startswith('@') for a in e['argv'][1:])]
    keys=[key(original.file_name(e['argv'])) for _,e in targets];need(len(keys)==len(set(keys)),'repeated raw response filename from ld')
    history={}
    for i,e in enumerate(rows):
        if Path(e['path']).name in LD and any(a.startswith('@') for a in e['argv'][1:]):
            p=original.file_name(e['argv']);events=list(journal.events.get(key(p),[]))
            need([next(iter(x['event'])) for x in events]==['create','unlink'],'missing or ambiguous response file creation/deletion')
            gone=fs_stamp(events[-1]['event']['unlink']['target']['stat'])
            data,fd=hand.final(p,gone)
            details={'path':str(p),'temporary':str(p.parent.resolve(strict=True)),'identity':gone,'sha256':original.digest(data),
                     'bytes':base64.b64encode(data).decode(),'raw_argv':original.digest(original.packed(e['argv'])),
                     'held_custody':{'version':TAG,'fd':fd,'events':events,'journal':summary}}
            e=rows[i]={**e,'xcode_response':details}
            verify_held(e,history.get(e['ppid']))
        history[e['pid']]=e
    list(resolved(rows))
    return rows

def command(execute, argv, *, timeout=2100, capture_rows=None, **kwargs):
    """A structural command's evidence can be written even when its response cannot be admitted."""
    root=original.darwin_user_temp();rows=CaptureRows() if capture_rows is None else capture_rows
    need(isinstance(rows,CaptureRows) and not rows,"expected a fresh response subscriber")
    with ExitStack() as stack:
        journal=stack.enter_context(FileJournal(root))
        hand=stack.enter_context(DirectoryHandles([root]))
        code,raw=execute(argv,timeout=timeout,observed_rows=rows,**kwargs)
        need(raw is rows,'foreign native exec subscriber')
        try:seal(rows,hand,journal)
        except (RuntimeError,KeyError,ValueError,OSError) as exc:
            need(rows,'no kernel execution to associate with observer failure')
            first=next((i for i,v in enumerate(rows) if Path(v['path']).name in LD and any(s.startswith('@') for s in v['argv'][1:])),0)
            event=rows[first];at=key(original.file_name(event['argv'])) if Path(event['path']).name in LD and len(event['argv'])==2 and event['argv'][1].startswith('@/') else None
            state=[]
            for (directory,name),ins in hand.files.items():
                if at and key(directory/name)==at:state.extend({'initial':v.initial,'last':original.stamp(os.fstat(v.fd))} for v in ins.values())
            rows[first]={**event,'response_observer_error':str(exc),'response_observer_details':{
                'root':str(root),'selected_events':journal.events.get(at,[]),'observed_inodes':state,
                'journal_barriers':journal.seals,'journal_errors':journal.errors,'directory_errors':hand.errors}}
        return code,rows
