"""Exercise successful, failed and nonleader exec under a real kernel observer."""
import os
import threading
TRUE="/usr/bin/true"
def child(kind):
    if kind=="shell":
        os.execv("/bin/sh",["/bin/sh","-c",'exec /usr/bin/true "$@"',"calibration",kind])
    if kind=="failed":
        try:os.execv("/missing-closure-fixture",["/missing-closure-fixture"])
        except FileNotFoundError:pass
        else:raise AssertionError()
    if kind=="nonleader":
        t=threading.Thread(target=os.execv,args=(TRUE,[TRUE,kind]))
        t.start();t.join();os._exit(77)
    os.execv(TRUE,[TRUE,kind])
if __name__=="__main__":
    children=[]
    for k in ("shell","sibling","failed","nonleader",*(f"rapid-{i}" for i in range(4))):
        pid=os.fork()
        if not pid:child(k);os._exit(78)
        children.append(pid)
    for pid in children:
        assert os.waitpid(pid,0)==(pid,0)
