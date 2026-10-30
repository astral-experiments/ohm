"""Reopen the release Cargo compile failure before Ruff or the integration suite started."""
import gzip
import hashlib
import json
import zipfile
from pathlib import Path
p=Path(__file__).with_name('original.zip')
assert p.stat().st_size==145686 and hashlib.sha256(p.read_bytes()).hexdigest()=='423cacaa3a906d7e2c67cb35332f84c7bf009e37a00471f4937d1738f75d05d9'
with zipfile.ZipFile(p) as z:
    assert z.testzip() is None and 'fix-terminal.json' not in z.namelist()
    j=lambda n:json.loads(z.read(n))
    for arm,sha,expected in [('P','2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c',0),('C','8c68d93dd97c142750714de6e27b832faaa1dd0d',101)]:
        loc='buildkit/'+arm+'/';assert j(loc+'source.json')['commit']==sha
        result=j(loc+'compile/result.json')
        assert result['exit']==expected and '--release' in result['command'] and 'ohm-defaults,all-static' in result['command']
        messages=[json.loads(line) for line in gzip.decompress(z.read(loc+'compile/stdout.gz')).splitlines()]
        assert messages[-1]=={'reason':'build-finished','success':expected==0}
        errors=[m['message'] for m in messages if m['reason']=='compiler-message' and m['message']['level']=='error']
        if arm=='P':assert not errors and sha in j(loc+'built.json')['version']
        else:
            err,=errors;assert err['code']['code']=='E0004' and 'PreviousBuildIncomplete' in err['message']
            primary,=[s for s in err['spans'] if s['is_primary']]
            assert primary['file_name']=='src/ops/cargo_report/rebuilds.rs' and primary['line_start']==398 and primary['column_start']==11
        print(arm,sha,expected,('complete' if not errors else errors[0]['message']))
