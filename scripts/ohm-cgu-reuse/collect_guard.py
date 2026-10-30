"""Keep all RawEvents, mono assignments and native programs across checked assembler input changes."""
from pathlib import Path
import argparse, hashlib, json, os, shutil, subprocess

def execute(root, rustup_home, collection):
    repo=root/'untracked-cgu-fixture'
    work=root/collection;work.mkdir();(work/'profile').mkdir()
    env={k:v for k,v in os.environ.items() if not k.startswith(('CARGO_','RUST','OHM_'))}
    env.update(RUSTUP_HOME=str(rustup_home),CARGO_HOME=str(work/'private-cargo'),CARGO_TARGET_DIR=str(work/'target'),
               CARGO_BUILD_BUILD_DIR=str(work/'shared'),CARGO_NET_OFFLINE='true',CARGO_TERM_COLOR='never')
    identity={k:subprocess.check_output([k,'+ohm','-vV' if k=='rustc' else '-Vv'],env=env).decode() for k in ('cargo','rustc')}
    (work/'toolchain.json').write_text(json.dumps(identity,indent=2)+'\n')
    cmd=['cargo','+ohm','rustc','--offline','--locked','--bin','cgu_guard','--message-format=json','--',
         '-Zprint-mono-items=yes','-Zself-profile='+str(work/'profile'),'-Zself-profile-events=generic-activity,function-args']
    (work/'command.json').write_text(json.dumps(cmd,indent=2)+'\n')
    payload=repo/'payload.bin'
    def set_byte(value):
        if value is None:
            assert payload.is_file()
            payload.unlink()
        elif not payload.exists():
            payload.write_bytes(bytes([value]))
        elif payload.read_bytes()!=bytes([value]):
            old=payload.stat();payload.write_bytes(bytes([value]));os.utime(payload,ns=(old.st_atime_ns,old.st_mtime_ns))
            new=payload.stat();assert(new.st_ino,new.st_size,new.st_mtime_ns)==(old.st_ino,old.st_size,old.st_mtime_ns)
    def visit(label,value):
        assert shutil.disk_usage(root).free>8*2**30
        set_byte(value)
        dest=work/('guard-'+label);dest.mkdir()
        initial=set((work/'profile').iterdir())
        p=subprocess.run(cmd,cwd=repo,env=env,capture_output=True,timeout=180)
        (dest/'stdout').write_bytes(p.stdout);(dest/'stderr').write_bytes(p.stderr)
        events=[json.loads(l) for l in p.stdout.splitlines() if l.startswith(b'{')]
        success=value is not None
        assert events[-1]=={'reason':'build-finished','success':success} and p.returncode==(0 if success else 101),(p.stderr[-1800:],p.stdout[-2200:])
        products=[m for m in events if m['reason']=='compiler-artifact' and m['target']['name']=='cgu_guard' and m['executable']]
        profiles=[str(p.relative_to(work)) for p in set((work/'profile').iterdir())-initial]
        if success:
            product,=products; exe=Path(product['executable'])
            b=exe.read_bytes();(dest/'program').write_bytes(b)
            actual=subprocess.check_output([str(exe)]).decode().strip()
            assert actual==f'{value} 41' and b[:4]==b'\x7fELF'
            result={'fresh':product['fresh'],'result':actual,'sha':hashlib.sha256(b).hexdigest(),'profile':profiles}
        else:
            assert not products and b'payload.bin' in p.stdout+p.stderr
            result={'result':'error','profile':profiles}
        (dest/'result.json').write_text(json.dumps(result,indent=2)+'\n')
        print(label,result,flush=True);return result
    rows={}
    for label,value in [('cold',17),('repeat',17),('native-change',29),('repeat-changed',29),('missing',None),('repair',29),('restore',17)]:
        rows[label]=visit(label,value)
    for label,value in [('clean-missing',None),('clean-old',17),('clean-new',29)]:
        retained=work/('before-'+label);retained.mkdir()
        for name in ('target','shared'):
            p=work/name
            assert p.is_dir() and not p.is_symlink() and p.parent==work
            p.rename(retained/name)
        rows[label]=visit(label,value)
    for a,b in [('cold','clean-old'),('repeat','clean-old'),('native-change','clean-new'),('repeat-changed','clean-new'),('repair','clean-new'),('restore','clean-old')]:
        assert rows[a]['sha']==rows[b]['sha'],(a,b)
    assert rows['clean-old']['sha']!=rows['clean-new']['sha']
    set_byte(17)
    return rows

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('rustup',type=Path);parser.add_argument('collection')
    args=parser.parse_args();execute(Path.cwd(),args.rustup.resolve(strict=True),args.collection)
