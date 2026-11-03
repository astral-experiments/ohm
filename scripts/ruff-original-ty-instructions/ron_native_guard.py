"""Try to falsify dropping the signed Ron observer on Ruff's actual locked Serde derive native image."""
from pathlib import Path
import gzip
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess as sp
import sys
import tarfile
import tempfile
import tomllib
import urllib.request

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
sys.path.insert(0,str(HERE.parent/'ruff-foreign-span-observer'))
import worker as w
from ron_causality import without_observation,replace
P=w.proof
W=w.root/'guard-source'
V=w.root/'registry'
LOCKED='b9cbcf372621bf3aa25ba0985e0b066b8c70624d51ecc50cc2f29b98712e6f40'
NEW='bfa2407e98ee1343caeefd02b4b69043509baa8c'
GOOD=b'serialize_newtype_struct'
BAD=b'serialize_newtype_strucx'


def dump(p,x):p.write_text(json.dumps(x,indent=1,sort_keys=True)+'\n')
def sig(data):return hashlib.sha256(data).hexdigest()
def elf(data):
    assert data[:7]==b'\x7fELF\x02\x01\x01' and struct.unpack_from('<H',data,18)[0]==62
    off=struct.unpack_from('<Q',data,40)[0];ent,n,sh=struct.unpack_from('<HHH',data,58)
    rows=[struct.unpack_from('<IIQQQQIIQQ',data,off+i*ent)for i in range(n)]
    names=data[rows[sh][4]:rows[sh][4]+rows[sh][5]];sections={}
    for name,kind,flags,addr,pos,size,*_ in rows:
        section=names[name:names.index(0,name)].decode()
        if section and kind!=8:
            assert section not in sections
            sections[section]=(pos,size,sig(data[pos:pos+size]))
    return sections


def corrupt(data):
    sections=elf(data);pos,n,_=sections['.rodata'];m=bytearray(data)
    offsets=[pos+x.start()for x in re.finditer(GOOD,data[pos:pos+n])]
    assert 0<len(offsets)<60 and len(GOOD)==len(BAD) and '.rustc' in sections and '.text' in sections
    for at in offsets:
        assert m[at:at+len(GOOD)]==GOOD;m[at:at+len(GOOD)]=BAD
    bad=bytes(m);new=elf(bad)
    assert [k for k in sections if sections[k]!=new[k]]==['.rodata']
    assert len(data)==len(bad)and sum(x!=y for x,y in zip(data,bad))==len(offsets)
    return bad,{'size':len(data),'normal':sig(data),'malformed':sig(bad),'offsets':offsets,'text':sections['.text'],'rustc':sections['.rustc'],'rodata':[sections['.rodata'],new['.rodata']]}


def inputs():
    assert w.git('rev-parse','HEAD')==NEW and w.hf(w.work/'Cargo.lock')==LOCKED
    pkgs=tomllib.loads((w.work/'Cargo.lock').read_text())['package']
    need=('ron','serde','serde_core','serde_derive','typeid','once_cell','unicode-ident','proc-macro2','quote','syn','bitflags')
    def locked_dependency(parent,name):
        stanza,=(x for x in pkgs if x['name']==parent)
        text,=(d for d in stanza['dependencies'] if d.split()[0]==name)
        part=text.split()
        return part[1] if len(part)==2 else None
    versions={'syn':locked_dependency('serde_derive','syn'),'bitflags':locked_dependency('ron','bitflags')}
    assert versions=={'syn':'3.0.6','bitflags':'2.13.2'}
    picked={}
    V.mkdir(); W.mkdir();(W/'src').mkdir();(W/'.cargo').mkdir()
    for name in need:
        matches=[p for p in pkgs if p['name']==name and (not versions.get(name)or p['version']==versions[name])]
        pkg,=matches;label=name+'-'+pkg['version'];out=V/(label+'.crate')
        with urllib.request.urlopen('https://static.crates.io/crates/'+name+'/'+label+'.crate',timeout=60)as uf,out.open('wb')as f:shutil.copyfileobj(uf,f)
        assert w.hf(out)==pkg['checksum']
        with tarfile.open(out,'r:gz')as tf:
            for entry in tf.getmembers():
                p=Path(entry.name);assert p.parts[0]==label and '..'not in p.parts and not p.is_absolute()and (entry.isfile()or entry.isdir())
            tf.extractall(V,filter='data')
        root=V/label
        files={str(p.relative_to(root)):w.hf(p)for p in root.rglob('*')if p.is_file()and p.name!='.cargo-checksum.json'}
        dump(root/'.cargo-checksum.json',{'package':pkg['checksum'],'files':files});picked[name]=[pkg['version'],pkg['checksum'],len(files)]
    (W/'.cargo/config.toml').write_text('[source.crates-io]\nreplace-with="original"\n[source.original]\ndirectory='+json.dumps(str(V))+'\n')
    (W/'Cargo.toml').write_text('[package]\nname="ron_native_safeguard"\nversion="0.0.0"\nedition="2021"\n[dependencies]\nron="=0.12.0"\n[profile.dev]\nopt-level=1\ndebug="line-tables-only"\n')
    (W/'src/lib.rs').write_text('#[cfg(test)]\nmod tests {\n #[test] fn current_ron_extension() {\n  let value=ron::extensions::Extensions::IMPLICIT_SOME;\n  let rendered=ron::ser::to_string_pretty(&value,ron::ser::PrettyConfig::new().struct_names(true)).unwrap();\n  println!("{rendered}");\n  assert_eq!(rendered, r#"Extensions("IMPLICIT_SOME")"#);\n }\n}\n')
    dump(P/'official-inputs.json',picked)
    return picked


def locked(env):
    sp.run(['cargo','+ohm','generate-lockfile','--offline'],env=env,cwd=W,check=True)
    p=tomllib.loads((W/'Cargo.lock').read_text())['package']
    assert len(p)==12
    return {x['name']:[x['version'],x.get('source'),x.get('checksum')]for x in p}


def histories(label,env):
    dest=P/label;dest.mkdir()
    args=['cargo','+ohm','test','--lib','--no-run','--locked','--offline','-j4','--message-format=json']
    err=dest/'stderr';log=dest/'stdout.jsonl'
    with err.open('wb')as so,log.open('wb')as out:
        ret=sp.run(['strace','-ff','-qq','-s','1048576','-e','trace=execve','-o',str(dest/'exec'),*args],cwd=W,env=env,stdout=out,stderr=so,timeout=240)
    rows=[json.loads(s)for s in log.read_bytes().splitlines()]
    assert rows[-1]=={'reason':'build-finished','success':ret.returncode==0}and ret.returncode in(0,101)
    messages=[m['message']for m in rows if m['reason']=='compiler-message'and m['message']['level']=='error']
    launched=[]
    for f in sorted(dest.glob('exec.*')):
        for line in f.read_text().splitlines():
            if line.rstrip().endswith(') = 0')and '"/' in line and '"/'+str(w.sdk/'bin/rustc').lstrip('/')+'"'in line and '"--crate-name", "ron"'in line:launched.append(f.name)
    # Cargo's own compiler message and physical native argv are both retained.
    verdict={'ret':ret.returncode,'errors':[[m.get('code',{}).get('code')if m.get('code')else None,m['message']]for m in messages],'ron_exec':launched}
    if ret.returncode==0:
        test,=[m['executable']for m in rows if m['reason']=='compiler-artifact'and m.get('executable')and m['target']['name']=='ron_native_safeguard']
        listing=sp.check_output([test,'--list','--format=terse'],cwd=W);assert listing.count(b': test')==1 and b'tests::current_ron_extension: test'in listing
        ans=sp.run([test,'--exact','tests::current_ron_extension','--nocapture'],cwd=W,stdout=sp.PIPE,stderr=sp.STDOUT)
        assert ans.returncode==0 and b'1 passed;'in ans.stdout and b'Extensions("IMPLICIT_SOME")'in ans.stdout
        (dest/'test-list').write_bytes(listing);(dest/'native').write_bytes(ans.stdout);verdict['elf']=w.hf(Path(test))
        rr,=[m for m in rows if m['reason']=='compiler-artifact'and m['target']['name']=='ron'and m['target']['kind']==['lib']]
        assert rr['features']==['default','std'];verdict['ron_fresh']=rr['fresh']
        so,=[m for m in rows if m['reason']=='compiler-artifact'and m['target']['name']=='serde_derive'and m['target']['kind']==['proc-macro']]
        verdict['dso']=so['filenames'][0];verdict['ron_rlib']=next(s for s in rr['filenames']if s.endswith('.rlib'))
    dump(dest/'result.json',verdict)
    return verdict


def reset_tree():
    for p in (w.target,w.shared):
        assert p.is_dir()and p.parent==w.root and not p.is_symlink()
        shutil.rmtree(p)


def main():
    assert os.environ['GITHUB_RUN_ATTEMPT']=='1'and os.environ['GITHUB_SHA']==os.environ['REVIEWED_HEAD']
    dump(P/'registration.json',{'run':os.environ['GITHUB_RUN_ID'],'head':os.environ['GITHUB_SHA'],'boot':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'source':NEW,'lock':LOCKED,'primary':'Unscored veto only: identical malformed native Serde ELF, no changes to its .text/.rustc. Ordinary trained Cargo, two single-OBS1 ablations, restored guard, repair, empty matching native compiler and independently edited actual source.'})
    env=w.install();proof=inputs();locked0=locked(env)
    assert all(locked0[k][0]==q[0] and locked0[k][2]==q[1]for k,q in proof.items())
    dump(P/'actual-lock.json',locked0)
    cold=histories('cold',env);warm=histories('warm',env)
    assert cold['ret']==warm['ret']==0 and cold['elf']==warm['elf']
    lib=Path(warm['ron_rlib']);fp=lib.parent.parent/'fingerprint/dep-lib-ron';original=fp.read_bytes();trim,qu=without_observation(original)
    (P/'original-dep-record').write_bytes(original);(P/'ablated-dep-record').write_bytes(trim);dump(P/'dep-ablation.json',qu)
    dso=Path(warm['dso']).resolve(strict=True);assert dso.is_relative_to(w.root);good=dso.read_bytes();bad,physical=corrupt(good);dump(P/'actual-dso.json',physical)
    with gzip.open(P/'original-serde.so.gz','wb')as f:f.write(good)
    badfile=w.root/'malformed-operand.so';badfile.write_bytes(bad)
    s=dso.stat();oldfp=fp.stat()
    replace(dso,bad,good);replace(fp,trim,original)
    rows={'cold':cold,'warm':warm}
    for label in('ablated-first','ablated-again'):rows[label]=histories(label,env)
    before=fp.read_bytes() if fp.is_file()else None
    if before is None:fp.write_bytes(original);os.utime(fp,ns=(oldfp.st_atime_ns,oldfp.st_mtime_ns))
    elif before!=original:replace(fp,original,before)
    assert dso.read_bytes()==bad and dso.stat().st_ino==s.st_ino and dso.stat().st_mtime_ns==s.st_mtime_ns
    rows['ordinary-malformed']=histories('ordinary-malformed',env)
    replace(dso,good,bad)
    rows['repair']=histories('repair',env)
    assert rows['repair']['ret']==0
    reset_tree()
    rows['empty-repair']=histories('empty-repair',env)
    reset_tree()
    # The empty reference builds every dependency normally. At first entry into Ron only,
    # install the exact held, independently section-checked DSO into its resolved --extern.
    wrap=w.root/'before-ron.py'
    wrap.write_text('#!/usr/bin/python3\nimport hashlib,os,sys,pathlib\na=sys.argv[1:];q=pathlib.Path\nif "--crate-name"in a and a[a.index("--crate-name")+1]=="ron":\n ds,=[q(x.split("=",1)[1])for i,x in enumerate(a) if i and a[i-1]=="--extern"and x.startswith("serde_derive=")]\n assert ds.is_file()and '+repr(str(w.root))+'in ds.as_posix()\n old=ds.read_bytes();new=q('+repr(str(badfile))+').read_bytes()\n q('+repr(str(P/'empty-native-installer'))+').write_text(str(ds)+"\\n"+hashlib.sha256(old).hexdigest()+"\\n"+hashlib.sha256(new).hexdigest()+"\\n")\n assert hashlib.sha256(old).hexdigest()=='+repr(physical['normal'])+' and hashlib.sha256(new).hexdigest()=='+repr(physical['malformed'])+'\n s=ds.stat();ds.write_bytes(new);os.utime(ds,ns=(s.st_atime_ns,s.st_mtime_ns))\nos.execv(a[0],a)\n')
    wrap.chmod(0o700);rows['empty-same-malformed']=histories('empty-same-malformed',dict(env,RUSTC_WRAPPER=str(wrap)))
    reset_tree()
    src=W/'serde-source';shutil.copytree(V/('serde_derive-'+proof['serde_derive'][0]),src)
    f=src/'src/ser.rs';old=f.read_bytes();from_=b'quote_spanned!(span=> _serde::Serializer::'+GOOD+b')'
    assert old.count(from_)==1
    f.write_bytes(old.replace(from_,from_.replace(GOOD,BAD)))
    with(W/'Cargo.toml').open('a')as h:h.write('[patch.crates-io]\nserde_derive={path="serde-source"}\n')
    modified=locked(env);assert modified['serde_derive'][1]is None;dump(P/'source-edited-lock.json',modified)
    rows['real-source-malformed']=histories('real-source-malformed',env)
    result={'rows':rows,'dso':physical,'manifest':qu,'ablation_admitted_stale':all(rows[k]['ret']==0 and rows[k].get('ron_fresh')for k in('ablated-first','ablated-again')),'ordinary_and_independent_clean_fail':all(rows[k]['ret']==101 and rows[k]['errors']for k in('ordinary-malformed','empty-same-malformed','real-source-malformed')),'repair_exact':rows['repair']['elf']==rows['empty-repair']['elf']}
    dump(P/'result.json',result)
    assert (P/'empty-native-installer').is_file()and result['ordinary_and_independent_clean_fail'] and result['repair_exact']
    assert sum(p.stat().st_size for p in P.rglob('*')if p.is_file())<40*2**20
if __name__=='__main__':main()
