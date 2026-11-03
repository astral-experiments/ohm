"""Independently reopen the native and metadata members from the real signed cfg-if permutation."""
import argparse,base64,gzip,hashlib,json,os,re,shutil,subprocess,tempfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
def sha(b):return hashlib.sha256(b).hexdigest()
def member_hashes(path):
    return {k:sha(subprocess.check_output(['ar','p',path,k]))for k in subprocess.check_output(['ar','t',path],text=True).splitlines()}
def read():
    data=json.loads(gzip.decompress((HERE/'flag-ablation.json.gz').read_bytes()))
    bodies={k:base64.b64decode(s,validate=True)for k,s in data['bodies'].items()};assert all(sha(b)==k for k,b in bodies.items())
    s=data['held_summary'];assert 'd57fd1515986dccecdcece8da85e651bfb4b81f9'in s['signed']and s['lock_archive']=='baf1de4339761588bc0619e3cbc0120ee582ebb74b53b4efbf79117bd2da40fd'
    out={}
    for scope,rows in s['per_scope'].items():
        a={role:v for role,v in data['source_argvs']if scope in v};x=a['first-upgraded'].copy();i=x.index('checksum-hash-algorithm=blake3');assert x[i-1]=='-Z';del x[i-1:i+1];assert x==a['prior-empty']
        assert rows[0]==rows[3]and rows[1]==rows[2]and rows[0]['rmeta']!=rows[1]['rmeta']
        changed=[]
        for j,row in enumerate(rows):
            n=scope.split('=')[1]+'-'+str(j);tbl=data['cases'][n];rmeta,=[v for k,v in tbl.items()if k.endswith('.rmeta')];root=bodies[tbl['root.txt']].decode()
            assert rmeta==row['rmeta']and re.search(r'private hash (\w{32}) stable_crate_id',root)[1]==row['private']and re.search(r'public_hash (\w{32})',root)[1]==row['public']
            assert (len(row['dep_checksums'])==1)==(j in (1,2));assert root and bodies[rmeta].startswith(b'rust')
            if row['native']:
                lib,=[bodies[v]for k,v in tbl.items()if k.endswith('.rlib')]
                with tempfile.TemporaryDirectory()as d:
                    p=Path(d)/'genuine.rlib';p.write_bytes(lib);assert member_hashes(p)==row['native']
                changed=[k for k,v in rows[0]['native'].items()if rows[1]['native'].get(k)!=v];assert changed==['lib.rmeta']
        out[scope]={'prior':rows[0]['public'],'strong':rows[1]['public'],'changed_archive_members':changed}
    return data,out
def replay(data,home,crate,work):
    import tarfile
    work.mkdir();source=work/'pkg';source.mkdir()
    assert sha(crate.read_bytes())==data['held_summary']['lock_archive']
    with tarfile.open(crate)as t:
        for m in t:
            p=(source/m.name).resolve();assert p.is_relative_to(source.resolve())and m.name.startswith('cfg-if-1.0.0/')and (m.isdir()or m.isreg())
            if m.isreg():p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(t.extractfile(m).read())
    lib=source/'cfg-if-1.0.0/src/lib.rs';assert sha(lib.read_bytes())==data['held_summary']['source']
    env={**os.environ,'RUSTUP_HOME':str(home.resolve())};c=['rustc','+ohm'];assert subprocess.check_output([*c,'-vV'],text=True,env=env)==data['held_summary']['signed']
    dest=work/'current';dest.mkdir()
    for scope in data['held_summary']['per_scope']:
        a={mode:v for mode,v in data['source_argvs']if scope in v};now=[]
        for j,mode in enumerate(('prior-empty','first-upgraded','first-upgraded','prior-empty')):
            v=a[mode][1:].copy();v[v.index('--out-dir')+1]=str(dest.resolve());i,=[i for i,t in enumerate(v)if t.endswith('/cfg-if-1.0.0/src/lib.rs')];v[i]=str(lib.resolve())
            p=subprocess.run([*c,*v],env=env,cwd=work,capture_output=True);assert p.returncode==0,p.stderr[-800:]
            r,=dest.glob('*.rmeta');root=subprocess.check_output([*c,'-Zls=root',r.resolve()],env=env,text=True)
            now.append((sha(r.read_bytes()),re.search(r'public_hash (\w{32})',root)[1]));dest.rename(work/(scope.split('=')[1]+'-'+str(j)));dest.mkdir()
        assert now[0]==now[3]and now[1]==now[2]and now[0][0]!=now[1][0]and now[0][1]!=now[1][1]
        print(scope,now[:2])
p=argparse.ArgumentParser();p.add_argument('--rustup-home',type=Path);p.add_argument('--crate',type=Path);p.add_argument('--new-work',type=Path);a=p.parse_args();data,held=read();print(json.dumps(held,sort_keys=True))
if any([a.rustup_home,a.crate,a.new_work]):
    assert all([a.rustup_home,a.crate,a.new_work]);replay(data,a.rustup_home,a.crate,a.new_work)
