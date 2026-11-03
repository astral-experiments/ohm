"""Exercise both Cargo readers on a single target, genuine registry source and unchanged compiler."""
import argparse,hashlib,json,os,shutil,stat,subprocess,zlib
from pathlib import Path

def sha(p):
    with p.open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
def put(p,j):p.write_text(json.dumps(j,sort_keys=True,indent=2)+'\n')
def main():
    p=argparse.ArgumentParser()
    for name in ('work','sdk','parent','candidate','registry','fixture'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--exec-counter',type=Path);a=p.parse_args();r=a.work.resolve();r.mkdir();proof=r/'proof';proof.mkdir()
    kit=r/'active-sdk';(kit/'bin').mkdir(parents=True);rt=r/'rustup/toolchains';rt.mkdir(parents=True);(rt/'ohm').symlink_to(kit)
    for f in a.sdk.iterdir():
        if f.name!='bin':(kit/f.name).symlink_to(f)
    for f in(a.sdk/'bin').iterdir():
        if f.name!='cargo':(kit/'bin'/f.name).symlink_to(f)
    dest=kit/'bin/cargo';parent=a.parent.resolve();candidate=a.candidate.resolve()
    seeds={k:sha(v)for k,v in [('parent',parent),('candidate',candidate)]};assert seeds['parent']!=seeds['candidate']
    reg=r/'cargo-home/registry';reg.mkdir(parents=True)
    for n in ('cache','index'):(reg/n).symlink_to((a.registry/n).resolve())
    project=r/'project';(project/'src').mkdir(parents=True)
    for n in('Cargo.toml','Cargo.lock'):shutil.copyfile(a.fixture/n,project/n)
    (project/'src/main.rs').write_text('fn main() { println!("{}", insta::Settings::clone_current().snapshot_path().display()); }\n')
    target=r/'target';shared=r/'shared';e={k:os.environ[k]for k in ('PATH','HOME','USER','LANG','TMPDIR')if k in os.environ}
    e.update(RUSTUP_HOME=str(rt.parent),RUSTUP_TOOLCHAIN='ohm',CARGO_HOME=str(reg.parent),CARGO_TARGET_DIR=str(target),CARGO_BUILD_BUILD_DIR=str(shared),CARGO_NET_OFFLINE='true')
    command=['cargo','+ohm','build','--locked','--offline','-j1','-vv','--message-format=json']
    registration=dict(seeds=seeds,rustc=sha(kit/'bin/rustc'),wild=sha(kit/'lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd'),lock=sha(project/'Cargo.lock'),argv=command,order=['parent-old','parent-unchanged','upgrade-valid','candidate-settled','invalid','invalid-repeated','candidate-repair','downgrade','second-upgrade','second-settled','empty-repair'],rule='The signed -24 reader knows v5 and v2. V6 must require retranslation on downgrade. The physical dep-lib-insta pathname must stay fixed on both transitions, including its initial empty v2 record if applicable. A changed valid result, two E0308s and an independently empty repaired program are required.')
    put(proof/'registration.json',registration);states=[];current=None;initial_path=None;oldelf=None;source=None;oldst=None
    def role(name):
        nonlocal current
        if current!=name:
            tmp=kit/'bin/cargo.next';shutil.copyfile(parent if name=='parent'else candidate,tmp);tmp.chmod(0o755);os.replace(tmp,dest);current=name
        assert sha(dest)==seeds[name]
    def source_stat():
        st=source.stat();return [st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns]
    def visit(label,who,expected,expected_rc=0):
        nonlocal initial_path
        role(who);d=proof/label;d.mkdir();argv=command
        if a.exec_counter:
            tasks=d/'tasks';tasks.mkdir();argv=[str(a.exec_counter),str(tasks),*argv]
        with(d/'stdout.jsonl').open('wb')as out,(d/'stderr').open('wb')as err:ret=subprocess.run(argv,cwd=project,env=e,stdout=out,stderr=err).returncode
        messages=[json.loads(l)for l in(d/'stdout.jsonl').read_bytes().splitlines()if l.startswith(b'{')]
        assert ret==expected_rc and messages[-1]=={'reason':'build-finished','success':ret==0},(label,ret)
        arts=[m for m in messages if m['reason']=='compiler-artifact'];errors=[m['message']for m in messages if m['reason']=='compiler-message'and m['message']['level']=='error']
        exe=target/'debug/ohm_insta_chain';assert exe.is_file();digest=sha(exe);display=subprocess.check_output([str(exe)],text=True).strip();assert display==expected,(label,display,expected)
        nat=proof/'native';nat.mkdir(exist_ok=True);stored=nat/(digest+'.z');body=exe.read_bytes()
        if not stored.exists():stored.write_bytes(zlib.compress(body,5))
        assert zlib.decompress(stored.read_bytes())==body
        fps=list(target.rglob('dep-lib-insta'))+list(shared.rglob('dep-lib-insta'));assert len(fps)==1,(label,fps)
        f=fps[0];relative=str(f.relative_to(r));wire=f.read_bytes();assert len(wire)>=6 and wire[:5]==bytes([1,0,0,0,255]);(d/'translated-dep-info').write_bytes(wire)
        if initial_path is None:initial_path=relative
        assert relative==initial_path,(label,initial_path,relative)
        if ret==0:
            assert not errors and (wire[5]==6 if who=='candidate'else wire[5]in(2,5)),(label,wire[5])
        else:
            assert any((m.get('code')or{}).get('code')=='E0308'and any(s['is_primary']and s['file_name']==str(source)for s in m['spans'])for m in errors)
        scheduled=[m['target']['name']for m in arts if not m['fresh']]
        row=dict(label=label,role=who,exit=ret,elf=digest,bytes=len(body),display=display,translated_path=relative,translated_bytes=len(wire),translated_version=wire[5],translated_sha256=sha(f),scheduled=scheduled,same_stat=source_stat()if source else None,source_sha256=sha(source)if source else None)
        if a.exec_counter:
            rustcs=[]
            for fn in sorted((d/'tasks').glob('*.nul')):
                v=fn.read_bytes().split(b'\0');args=v[4:-1]
                if v[3].endswith(b'/bin/rustc')and b'--crate-name'in args:rustcs.append(args[args.index(b'--crate-name')+1].decode())
            row['physical_rustcs']=rustcs
            if label in ('upgrade-valid','candidate-repair','downgrade','second-upgrade'):assert 'insta'in rustcs,(label,rustcs)
        if source:assert row['same_stat']==oldst
        put(d/'result.json',row);states.append(row);return digest
    oldelf=visit('parent-old','parent','snapshots');visit('parent-unchanged','parent','snapshots')
    source,=(reg/'src').glob('*/insta-1.48.0/src/settings.rs');original=source.read_bytes();st=source.stat();oldst=source_stat()
    def mutate(before,after):
        assert len(before)==len(after)and original.count(before)==1
        source.chmod(st.st_mode|stat.S_IWUSR);source.write_bytes(original.replace(before,after));os.utime(source,ns=(st.st_atime_ns,st.st_mtime_ns));source.chmod(st.st_mode);assert source_stat()==oldst
    base=b'snapshot_path: "snapshots".into(),';valid=b'snapshot_path: "snapsh0ts".into(),';wrong=b'snapshot_path: false'+b' '*(len(base)-len(b'snapshot_path: false,'))+b','
    mutate(base,valid);new=visit('upgrade-valid','candidate','snapsh0ts');assert new!=oldelf
    assert visit('candidate-settled','candidate','snapsh0ts')==new
    mutate(base,wrong);assert visit('invalid','candidate','snapsh0ts',101)==new;assert visit('invalid-repeated','candidate','snapsh0ts',101)==new
    mutate(base,base);repair=visit('candidate-repair','candidate','snapshots');assert repair==oldelf
    assert visit('downgrade','parent','snapshots')==oldelf;assert visit('second-upgrade','candidate','snapshots')==oldelf
    assert visit('second-settled','candidate','snapshots')==oldelf
    for f in(target,shared):
        assert f.parent==r and f.is_dir()and not f.is_symlink();f.rename(r/('used-'+f.name))
    assert visit('empty-repair','candidate','snapshots')==repair;assert [s['label']for s in states]==registration['order']
    put(proof/'complete.json',{'roles':seeds,'source_stat':oldst,'source':sha(source),'native':[oldelf,new],'rows':states})
    print([(s['label'],s['exit'],s['translated_version'],s['translated_bytes'])for s in states])
if __name__=='__main__':main()
