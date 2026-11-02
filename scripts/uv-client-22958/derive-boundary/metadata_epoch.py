"""Present the two original foreign metadata files to both real installed SDKs."""
from pathlib import Path
from hashlib import sha256
import json,subprocess
def sh(p):return sha256(p.read_bytes()).hexdigest()
def save(p,x):
    with p.open('x')as f:json.dump(x,f,indent=1,sort_keys=True);f.write('\n')
records=json.loads(Path(__file__).with_name('epoch-sources.json').read_bytes())
EPOCHS={'77ce0545653df71f43e601c28dde01a5e4f02b09': (43317, 3), 'ac67101cb973e35ce8ff044cc8014c2c76bab69e': (43319, 43319)}
label={'77ce0545653df71f43e601c28dde01a5e4f02b09': 'parent', 'ac67101cb973e35ce8ff044cc8014c2c76bab69e': 'candidate'}

def banner_and_epoch(metadata):
    data = metadata.read_bytes()
    assert data[:8] == b'rust\x00\x00\x00\x0a' and 16 < int.from_bytes(data[8:16], 'little') < len(data)
    pos = 16; n = 0
    for k in range(8):
        b = data[pos]; pos += 1; n |= (b & 127) << (7 * k)
        if b < 128:
            break
    assert 5 < n < 255 and data[pos+n] == 0xc1
    return data[pos:pos+n].decode('utf8')

def metadata(sdks,out,*,expected=None):
    verified=EPOCHS if expected is None else dict(expected)
    assert list(sdks)==list(verified) and len(verified)==2
    assert all(len(rev)==40 and set(rev)<=set('0123456789abcdef') and len(pair)==2 and all(type(x) is int and 0<x<65536 for x in pair) for rev,pair in verified.items())
    assert len({v[1]for v in verified.values()})==2
    labels=dict(zip(verified,('parent','candidate'),strict=True))
    out=Path(out).resolve();out.mkdir()
    (out / 'dep.rs').write_text('pub const VALUE: u32 = 41;\npub fn add(value: u32) -> u32 { VALUE + value }\n')
    (out / 'reader.rs').write_text('extern crate derive_boundary;\npub const COPIED: u32 = derive_boundary::VALUE;\npub fn computed() -> u32 { derive_boundary::add(1) }\n')
    (out / 'bad.rs').write_text('extern crate derive_boundary;\npub const WRONG: bool = derive_boundary::VALUE;\n')
    headers = {}; traces = {}; src = {}
    for rev, sdk in sdks.items():
        if rev in records:
            assert records[rev]['epochs']==list(verified[rev]) and records[rev]['source']==rev
            src[rev]=records[rev]['files']
        else:
            assert expected is not None
            src[rev]={'external_explicit_source_pin':rev,'native_banner_and_format_checked':True}
        (out / labels[rev]).mkdir()
    def run(rev, name, args, ok):
        sdk = sdks[rev]; cmd = [str(sdk/'bin/rustc'), '--sysroot', str(sdk), '--edition=2024', *args]
        env = {'PATH': str(sdk/'bin')+':/usr/bin:/bin', 'LD_LIBRARY_PATH': str(sdk/'lib'), 'LC_ALL': 'C'}
        p = subprocess.run(cmd, cwd=out, env=env, capture_output=True)
        stdout, stderr = out/(name+'.stdout'), out/(name+'.stderr')
        stdout.write_bytes(p.stdout); stderr.write_bytes(p.stderr)
        assert (p.returncode == 0) == ok, (name, p.returncode, p.stderr[-1000:])
        assert not p.stdout and (not p.stderr) == ok, (name,p.stderr[:300])
        rows = [json.loads(line) for line in p.stderr.splitlines()]
        traces[name] = {'argv': cmd, 'compiler': rev, 'status': p.returncode, 'stdout': sh(stdout), 'stderr': sh(stderr), 'codes': [x['code']['code'] for x in rows if x.get('code')]}
        return rows
    for rev, sdk in sdks.items():
        stem = labels[rev]; path = out / stem / 'libderive_boundary.rmeta'
        real_banner = subprocess.check_output([sdk/'bin/rustc','--version'], text=True, env={'PATH':'/usr/bin:/bin','LD_LIBRARY_PATH':str(sdk/'lib')}).strip()
        run(rev,stem+'-write',['--crate-name','derive_boundary','--crate-type=rlib','--emit=metadata','-Cmetadata=epoch-format-fixture', '-o',str(path),'dep.rs'],True)
        encoded = banner_and_epoch(path)
        assert encoded == f'{real_banner} (Ohm metadata {verified[rev][1]})' and rev[:9] in encoded, encoded
        headers[rev] = {'path':str(path),'sha256':sh(path),'bytes':path.stat().st_size,'native_banner':real_banner,'encoded_version':encoded,'metadata_epoch':verified[rev][1]}
    for receiver in sdks:
        for donor in sdks:
            name = labels[donor]+'-to-'+labels[receiver]; p = Path(headers[donor]['path'])
            args = ['--crate-name','consumer','--crate-type=lib','--emit=metadata','--extern','derive_boundary='+str(p),'--error-format=json','-o',str(out/(name+'.rmeta'))]
            own = receiver == donor; rows = run(receiver,name,[*args,'reader.rs'],own)
            if own:
                good = out/(name+'.rmeta'); assert banner_and_epoch(good) == headers[receiver]['encoded_version']
                traces[name]['result_sha256'] = sh(good)
                bad = run(receiver,name+'-genuine-type-error',[*args[:-1],str(out/(name+'-bad.rmeta')),'bad.rs'],False)
                assert [x['code']['code'] for x in bad if x.get('code')] == ['E0308']
            else:
                errors = [r for r in rows if r.get('code')]; assert [r['code']['code'] for r in errors] == ['E0514'], rows
                assert 'derive_boundary' in errors[0]['message'] and 'incompatible' in errors[0]['message']
                assert headers[donor]['encoded_version'] in errors[0]['rendered'] and headers[receiver]['encoded_version'] in errors[0]['rendered'], errors[0]['rendered']
                assert not (out/(name+'.rmeta')).exists()
            assert sh(p) == headers[donor]['sha256']
    receipt = {'actual_originals':headers,'real_reader_invocations':traces,'own_crate_reads':2,'own_native_typecheck_errors':2,'cross_crate_E0514':2,'source':src,'file_edits':False,'compiler_version_overrides':False,'scope':'The ordinary native -vV banners differ alongside the genuine encoded metadata epochs. The complete compiler interpretation is rejected before extern item access in both directions. The encoded metadata version is read from both untouched native files. Source references, when locally enrolled, are separate evidence.'}
    save(out/'passed.json',receipt)
    return receipt
