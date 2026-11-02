"""Read-only decoding functions lifted verbatim from the measured worker."""
from pathlib import Path
import os,signal
OPTS = 0x10001e

def decode(data):
    root=data["root"];assert type(root)is int and root>0 and data["options"]==OPTS
    births={};exits={};images=[];handoffs={};unresumed=set()
    for row in data["events"]:
        pid,status=row[:2];assert type(pid)is int and pid>0
        if status=="resume-ESRCH":
            assert len(row)==2
            unresumed.add(pid);continue
        assert type(status)is int and 0<=status<1<<24
        if os.WIFEXITED(status)or os.WIFSIGNALED(status):
            assert len(row)==2 and pid not in exits
            exits[pid]=os.waitstatus_to_exitcode(status);continue
        assert os.WIFSTOPPED(status)and os.WSTOPSIG(status)==signal.SIGTRAP
        event=status>>16;child=row[2];assert type(child)is int and child>0
        if event in (1,2,3):
            assert len(row)==3 and pid!=child and child not in births and child!=root
            births[child]=pid
        else:
            assert event==4 and len(row)==4
            im=row[3];assert isinstance(im["exe"],str) and len(im["file"])==3 and all(type(x)is int for x in im["file"])
            images.append(dict(im,pid=pid,previous_tid=child))
            if child!=pid:
                assert child not in handoffs
                handoffs[child]=pid
    tracees={root,*births}
    assert all(p in tracees for p in births.values()) and {v["pid"]for v in images}<=tracees
    for child in births:
        seen=set()
        while child!=root:
            assert child in births and child not in seen
            seen.add(child);child=births[child]
    assert set(handoffs)<=tracees and set(handoffs.values())<=tracees
    assert tracees==set(exits)|set(handoffs) and unresumed<=set(exits)|set(handoffs)
    assert all((pid==root or pid in births)for pid in exits)and images and images[0]["pid"]==root
    return {"root":root,"images":images,"births":births,"exits":exits,"handoffs":handoffs}

def kernel_receipt(events,enrollment,forms,expected_argv,decode):
    z=decode(events);root=z['root'];first=z['images'][0]
    assert first['pid']==root and first['argv']==expected_argv and first['exe']==expected_argv[0]and first['file']==enrollment['cargo_file']and z['exits'][root]==0
    rust=enrollment['compiler'];wanted={a[a.index('--crate-name')+1]:a for a in forms};assert len(wanted)==len(forms)==8;actual={}
    for image in z['images']:
        args=image.get('argv')or []
        if image['file']!=enrollment['rustc_file']and Path(image['exe']).name!='rustc'and not(args and Path(args[0]).name=='rustc'):continue
        pid=image['pid'];assert image['file']==enrollment['rustc_file']and image['exe']==rust and args[0]==rust and z['exits'].get(pid)==0
        assert args.count('--crate-name')==1 and args.count('--crate-type')==1 and args[args.index('--crate-type')+1]=='lib';name=args[args.index('--crate-name')+1]
        assert name not in actual and wanted.get(name)==args;actual[name]=pid
    assert set(actual)==set(wanted)and len(set(actual.values()))==8
    return {'cargo':root,'rustcs':actual,'images':len(z['images']),'tracees':len(z['exits'])+len(z['handoffs'])}
