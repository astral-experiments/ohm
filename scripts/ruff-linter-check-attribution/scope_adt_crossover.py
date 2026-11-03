"""Bind the existing mapped-driver format-change receiver to this actual compiler pair."""
import json
from pathlib import Path
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import worker as w

if __name__ == '__main__':
    w.checked_head()
    w.resources()
    bindings=json.loads((w.HERE/'scope-adt-factory.json').read_bytes())['inline']
    roles=json.loads((w.OUT/'scope-sdks.json').read_bytes())
    assert set(roles)=={'inline-P','inline-C'} and roles['inline-P']['source']==bindings['source']['P'] and roles['inline-C']['source']==bindings['source']['C']
    previous=w.WS/'format-reader'
    assert w.git(previous,'rev-parse','HEAD')=='ad5975b4a4aa91c2ff69a1728fa802dba99e3ecd' and not w.git(previous,'status','--porcelain','--untracked-files=all')
    actor=previous/'scripts/ruff-upstream-mono-pilot/cross-version/cross_version.py'
    args=['--factory-receipts',str(w.ROOT/'scope-kit-inline/receipts.zip'),'--expect-factory-sha256',bindings['receipts'][3]]
    for prefix,role,fmt in [('parent','P',24450),('child','C',49126)]:
        entry=roles['inline-'+role]
        args+=['--'+prefix+'-sdk',entry['sdk'],'--'+prefix+'-commit',entry['source'],'--'+prefix+'-format',str(fmt)]
    subprocess.run([sys.executable,'-IB',str(actor),'--work',str(w.ROOT/'adt-rsic-fixed-path'),'--out',str(w.OUT/'adt-rsic-upgrade'),*args],check=True)
