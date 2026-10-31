"""Real overlay with different directory/file st_dev, a same-device bind and an ordinary hardlink."""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import mount_evidence as m
import tables as t

def ledger(home,paths):
    return {str(p.relative_to(home)):t.shape(p.lstat()) for root in paths for p in (root,*sorted(root.rglob('*')))}

def main(root,mode):
    stage=root/'displaced-shadow';target=root/'target';build=root/'build'
    native=ledger(root,[target,build]);staged=ledger(stage,[stage]);captured=m.capture(root,stage,native)
    if mode=='positive':
        receipt=m.validate(captured,native,staged)
        t.need(len(receipt['original_devices'])==len(receipt['stage_devices'])==2, 'overlay control did not expose distinct real directory/regular st_dev')
        t.need(captured['shadow']['.']['stat'][0]!=captured['shadow']['new']['stat'][0],"old source must reject this genuine layout")
    else:
        try:m.validate(captured,native,staged)
        except ValueError as ex:
            reason=str(ex)
            t.need(('foreign mount or unstable identity' if mode=='bound' else 'aliases an ordinary allocation') in reason,reason)
        else:raise ValueError('accepted foreign bind or real alias')
        receipt={'rejection':reason,'root':captured['roots']['.'],'staged':captured['shadow']['new']}
    print(json.dumps({'actual_overlay_mode':mode,'receipt':receipt},sort_keys=True))
if __name__=='__main__':main(Path(sys.argv[1]),sys.argv[2])
