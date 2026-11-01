"""Run historical refusals, a positive native Wild ledger, and adversarial receiving cases offline."""
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import ctfe_pilot_registration as reg
import source_guard
import reopen
import contact_review

def fails(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except (AssertionError, ValueError, KeyError):
        return
    raise ValueError(('unexpected acceptance',fn.__name__))

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def manifest_negatives():
    with tempfile.TemporaryDirectory(prefix='ctfe-v2-manifest-') as d:
        tree=Path(d); base=tree/'scripts/ctfe-crossover-pilot'; base.mkdir(parents=True)
        workflow=tree/'.github/workflows/ci.yml';workflow.parent.mkdir(parents=True);workflow.write_bytes(b'x')
        (base/'native.py').write_bytes(b'y')
        files={'.github/workflows/ci.yml','scripts/ctfe-crossover-pilot/native.py','scripts/ctfe-crossover-pilot/SHA256SUMS'}
        original=[f"{reg.sha(workflow)}  ../../.github/workflows/ci.yml", f"{reg.sha(base/'native.py')}  native.py"]
        manifest=base/'SHA256SUMS'
        manifest.write_text('\n'.join(original)+'\n')
        assert source_guard.checksums(tree,files) == 2
        for bad in [original[:1],original+original[:1],original+['0'*64+'  SHA256SUMS'],
                    [original[0],original[1].replace(reg.sha(base/'native.py'),'0'*64)]]:
            manifest.write_text('\n'.join(bad)+'\n')
            fails(source_guard.checksums,tree,files)

def main(repo):
    manifest_negatives()
    base=repo/'scripts/branch-return-execstop'
    source_guard.tree(repo,reg.OBSERVER,'scripts/branch-return-execstop')
    source_guard.tree(repo,reg.OBSERVER,'scripts/branch-return-pmu')
    assert reg.sha(base/'SHA256SUMS') == reg.OBSERVER_MANIFEST
    assert reg.sha(base/'kernel/read_events.py') == reg.sha(HERE/'kernel-review/read_events.py') == reg.READER
    legacy=module('old_v1',base/'group-v2/history/v1_reader.py')
    curr=reopen.kernel
    original={}
    hashes=('69c9473cbf41a41d24b13776b009bdf90b7c895cb84bd7caf88f9a77f5cf6230','ee1ab1b4b8d74d52eddca09a4e6632d3edb0a8c5add7078374fb2ee8594f3739')
    for pos,digest in zip(('01','02'),hashes,strict=True):
        raw=gzip.decompress((base/'group-v2/history'/(pos+'.tsv.gz')).read_bytes())
        assert hashlib.sha256(raw).hexdigest() == digest
        fails(legacy.parse,raw);fails(curr.parse,raw,expected_schema=2);original[pos]=digest
    raw=gzip.decompress((HERE/'enrollment/wild-v2-local.tsv.gz').read_bytes())
    parsed=curr.parse(raw,expected_code=0,expected_schema=2)
    e,=parsed['execs']
    assert e['image']['sha256'] == curr.STOCK and '-o' in e['argv']
    # No Rust compiler is in this local fixture. The full worker and reviewer derive the actual compiler owner per link.
    rows=[dict(event=e['ordinal'],lifetime=e['lifetime'],output=e['argv'][e['argv'].index('-o')+1],rustc_event=None,rustc_crate=None)]
    h,=reg.wild_helpers(raw,rows)
    assert h['owner'] != h['wild_lifetime'] and len(h['parked']) == 2 and h['status'] == 0
    assert not reg.wild_helpers(raw,[]) and not reg.wild_helpers(raw,[dict(rows[0],event=55)])
    fails(legacy.parse,raw);fails(curr.parse,raw,expected_schema=1)
    for tag in (b'G',b'Q',b'V',b'X',b'T'):
        lines=raw.splitlines(keepends=True)
        ix=next(i for i,x in enumerate(lines) if x.startswith(tag+b'\t'))
        fails(curr.parse,b''.join(lines[:ix]+lines[ix+1:]),expected_schema=2)
    footer=raw.splitlines(keepends=True)
    fails(curr.parse,b''.join(footer[:-1])+b'OK\t0\t1\t4\t3\t4\t0\t1\t0\n',expected_schema=2)
    # A separate installed-image fixture has eight parked threads and no forked Wild image.
    fails(curr.parse,raw,expected_schema=3)
    installed=gzip.decompress((HERE/'enrollment/installed-v3-local.tsv.gz').read_bytes())
    installed_ledger=curr.parse(installed,expected_code=37,expected_schema=3)
    installed_image,=installed_ledger['execs']
    row=dict(lifetime=installed_image['lifetime'],event=installed_image['ordinal'],pid=installed_image['pid'],
             crate='installed_fixture')
    g,=reg.compiler_groups(installed,[row])
    assert g==dict(owner=row['lifetime'],pid=row['pid'],event=row['event'],status=37,crate='installed_fixture',workers=8)
    assert not reg.wild_helpers(installed,[]) and not reg.compiler_groups(raw,[row])
    assert not reg.compiler_groups(installed,[dict(row,event=row['event']+1)])
    fails(reg.compiler_groups,installed,[dict(row,pid=row['pid']+1)])
    fails(curr.parse,installed,expected_schema=2)
    for boots in reg.PREVIOUS.values():
        for boot in boots:
            fails(reg.fresh,boot)
    boot='fb6ccd45-667d-4180-95a3-78c5ebc10725'
    reg.fresh(boot);fails(reg.fresh,boot,[boot])
    h=dict(boot=boot,machine='x86_64',release='7.1.4',affinity=list(range(8)))
    reg.host(h);fails(reg.host,dict(h,release='7.1.40'));fails(reg.host,dict(h,machine='aarch64'))
    assert reg.jobs('contact') == ('01',) and reg.jobs('full-pilot') == ('01','02')
    reg.hardware_gate()
    print(json.dumps(dict(original_refusals=original, positive_schema=parsed['schema'], native_wild=parsed['sha256'],
                          historical_boots=sum(map(len,reg.PREVIOUS.values())),contact_excludes_its_own_boot=True),sort_keys=True))

if __name__=='__main__':
    main(Path(sys.argv[1]).resolve(strict=True))
