"""Compile one native observer against a verified real Linux rustc, with all mapped inputs held."""
from pathlib import Path
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess as sp
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
import prepare

# Each is a fully resolved regular ELF name from both uninstrumented -24 runs.
SYSTEM=("ld-linux-x86-64.so.2","libc.so.6","libdl.so.2","libgcc_s.so.1","libm.so.6",
        "libpthread.so.0","librt.so.1","libstdc++.so.6.0.33","libz.so.1.3")

def scope(root,sdk,capture,maps):
    assert set(SYSTEM)=={Path(row[0]).name for row in maps if row[4]==0}
    base=root/'three';bound=prepare.build(base,sdk,capture)
    full=root/'all-native';full.mkdir()
    actor=(HERE.parent/'src/actor.cpp').read_text()
    k='extern "C" bool check_held_software();';assert actor.count(k)==1
    actor=actor.replace(k,k+'\nextern "C" bool check_codegen_software(const char*);')
    k='  bool matches=select_member(';assert actor.count(k)==1
    actor=actor.replace(k,'  if(!check_codegen_software("opt"))return 0;\n'+k)
    i=actor.index(' int inspect_emit(');k='  auto name=id(m);';assert actor[i:].count(k)==1
    actor=actor[:i]+actor[i:].replace(k,'  if(!check_codegen_software("emit"))return 0;\n'+k)
    k='// Copy only whole instructions verified';assert actor.count(k)==1
    actor=actor.replace(k,'''static unsigned char signed_trampolines[2][32];static size_t signed_lengths[2];
extern "C" bool registered_diagnostic_trampoline(unsigned long page) {
  const auto* p=reinterpret_cast<const unsigned char*>(page);
  const int which=page==(unsigned long)opt_trampoline?0:page==(unsigned long)emit_trampoline?1:-1;
  if(which<0 || !signed_lengths[which] || memcmp(p,signed_trampolines[which],signed_lengths[which]))return false;
  for(size_t i=signed_lengths[which];i<4096;i++)if(p[i])return false;
  return true;
}
'''+k)
    k='  require(mprotect(tr,4096,PROT_READ|PROT_EXEC)==0);';assert actor.count(k)==1
    actor=actor.replace(k,'''  const int which=trampoline==&opt_trampoline?0:1;
  require((which==0 || trampoline==&emit_trampoline) && n+14<=32);
  signed_lengths[which]=n+14;memcpy(signed_trampolines[which],tr,n+14);
'''+k)
    k='  if(found && !strcmp(mode,"reuse"))load_receipt();';assert actor.count(k)==1
    actor=actor.replace(k,k+'''
  if(found && getenv("OHM_RON_PRIVATE_RX_CONTROL")){
    void* other=mmap(nullptr,4096,PROT_READ|PROT_EXEC,MAP_ANONYMOUS|MAP_PRIVATE,-1,0);
    require(other!=MAP_FAILED);
  }''')
    (full/'actor.cpp').write_text(actor)
    prepare.execute(['clang++','-std=c++17','-O2','-g','-fPIC','-shared','-fno-rtti','-I'+str(base/'llvm'),'-I'+str(HERE.parent/'src'),full/'actor.cpp',
                    HERE/'mapping.cpp',HERE.parent/'src/hook.S','-L'+str(sdk/'lib'),'-Wl,-rpath,'+str(sdk/'lib'),
                    '-l:libLLVM.so.23.1-rust-1.99.0-beta','-ldl','-lcrypto','-pthread','-o',full/'contact.so'])
    objs=sorted(base.glob('blake3*.o'));assert len(objs)==7
    h=(HERE.parent/'src/hash-tools.c').read_text().replace('if(n!=4)return 1;','if(n!=16)return 1;')
    (full/'hash-all.c').write_text(h)
    prepare.execute(['cc','-O3','-I'+str(base/'blake3'),full/'hash-all.c',*objs,'-o',full/'hash-all'])
    osfiles={Path(row[0]).name:Path(row[0]).resolve()for row in maps if row[4]==0}
    copies=root/'private-elf-generations';copies.mkdir()
    links={}
    for name in (*SYSTEM,'libcrypto.so.3'):
        f=osfiles.get(name,Path('/usr/lib/x86_64-linux-gnu')/name).resolve()
        assert f.is_file() and f.name==name and f.parent==Path('/usr/lib/x86_64-linux-gnu')
        assert f.stat().st_uid==0 and not f.stat().st_mode&0o022
        copy=copies/name;shutil.copyfile(f,copy);links[f]=copy
    files=[sdk/'bin/rustc',sdk/'lib/librustc_driver-b03bf00bec23bb9a.so',sdk/'lib/libLLVM.so.23.1-rust-1.99.0-beta',
           *(osfiles[n] for n in SYSTEM),Path(bound['role']['externs']['serde_derive'][0]).resolve(),full/'contact.so',
           Path('/usr/lib/x86_64-linux-gnu/libcrypto.so.3').resolve()]
    assert len(set(files))==15 and {Path(item[0]).resolve()for item in maps}==set(files[:13])
    sources=[links.get(f,f)for f in files]
    assert all(f.stat().st_uid==os.getuid() and f.stat().st_nlink==1 for f in sources)
    hashrows=sp.check_output([full/'hash-all',*sources],text=True).splitlines()
    rows=[]
    for f,src,line in zip(files,sources,hashrows,strict=True):
        st=src.stat();dig,display=line.split(maxsplit=1);assert display==str(src) and len(dig)==64
        sha=prepare.sha(src);assert sha==prepare.sha(f)
        if f in set(files[:13]):
            item,=[row for row in maps if Path(row[0]).resolve()==f]
            assert sha==item[8] and st.st_size==item[3]
        rows.append(dict(name=str(f),source=str(src),sha256=sha,blake3=dig,bytes=st.st_size,
                         dev=st.st_dev,ino=st.st_ino,uid=st.st_uid,original_uid=f.stat().st_uid,
                         original_dev=f.stat().st_dev,original_ino=f.stat().st_ino))
    compile_supervisor(root, rows, bound["role"]["argv_sha256"])
    return rows

def compile_supervisor(root, rows, argv_fingerprint):
    base=root/'three';full=root/'all-native';objs=sorted(base.glob('blake3*.o'));assert len(objs)==7
    decl=lambda values:','.join(values)
    names=decl(json.dumps(r['name'])for r in rows);hashes=decl(json.dumps(r['blake3'])for r in rows)
    dev=decl(str(r['dev'])for r in rows);ino=decl(str(r['ino'])for r in rows)
    header=(HERE/'generation.h.in').read_text().replace('RON_FILES_AND_DIGESTS',
            'std::array<fs::path,role_count> files={'+names+'};\n    const char* wanted[]={'+hashes+'};')
    header=header.replace('RON_PRIVATE_INODES','const unsigned long expected_dev[]={'+dev+'}, expected_ino[]={'+ino+'};')
    (full/'generation.h').write_text(header)
    prefix=(HERE.parent/'src/supervisor-prefix.cpp').read_text()
    (full/'supervisor.cpp').write_text(prefix+'\n#define REGISTERED_CMD "'+argv_fingerprint+'"\n'+(HERE/'main.inc').read_text())
    prepare.execute(['c++','-std=c++17','-O2','-g','-I'+str(base/'blake3'),'-I'+str(HERE),'-I'+str(HERE.parent/'src'),full/'supervisor.cpp',*objs,'-lcrypto','-o',full/'supervise'])
    dep=sp.check_output(['ldd',str(full/'contact.so')],text=True);assert 'libcrypto.so.3 =>' in dep and 'not found' not in dep
    prepare.dump(full/'physical.json',dict(files=rows,ldd=dep,actor=prepare.sha(full/'contact.so'),
                 supervisor=prepare.sha(full/'supervise'),argv=argv_fingerprint))


def enter_namespace(context,rows):
    """Drop privileges before mounting any copied ELF and never execute user code as root."""
    uid=os.getuid();gid=os.getgid();assert uid>0 and gid>0 and len(rows)==15
    bb=Path('/bin/busybox');assert bb.is_file() and bb.stat().st_uid==0
    static=sp.check_output(['file','-L',str(bb)],text=True);assert 'statically linked' in static or 'static-pie linked' in static,static
    q=shlex.quote
    sh='set -eu\n'
    sh+='test "$(/bin/busybox readlink /proc/self/ns/mnt)" != "$(/bin/busybox readlink /proc/$PPID/ns/mnt)"\n'
    sh+="/bin/busybox awk '{for(i=7;i<=NF && $i!=\"-\";i++) if($i~/^(shared|master):/)exit 1}' /proc/self/mountinfo\n"
    stage=context.parent/'physical-input-generations';stage.mkdir()
    assert context.parent.resolve()==context.parent and stage.stat().st_uid==uid and not list(stage.iterdir())
    assert sum(r['bytes'] for r in rows)<450*2**20
    sh+=f'/bin/busybox mount -t tmpfs -o mode=0700,uid={uid},gid={gid},size=512m,nosuid,nodev tmpfs {q(str(stage))}\n'
    base="/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/bin "
    py="/usr/bin/python3 -IB "+q(str(HERE/'work.py'))
    drop=f"/usr/bin/setpriv --reuid={uid} --regid={gid} --clear-groups --no-new-privs /bin/busybox sh -c "
    ctx=json.loads(context.read_bytes());proof=Path(ctx['proof']);counter=context.parent/'whole_count'
    # All physical copying and all registration of the new generation happens as the regular user.
    for action in ('--copy-generations','--bind-supervisor'):
        cmd=('exec '+base+q(str(counter))+' '+q(str(proof/(action[2:]+'-hardware.json')))+' /usr/bin/python3 '+py+' '+action+' '+q(str(context)))
        sh+=drop+q(cmd)+'\n'
    cmd="kill -STOP $$; exec /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/bin /usr/bin/python3 -IB "+q(str(HERE/'work.py'))+" --inside "+q(str(context))
    sh+=f"/usr/bin/setpriv --reuid={uid} --regid={gid} --clear-groups --no-new-privs /bin/busybox sh -c {q(cmd)} &\nchild=$!\n"
    sh+="trap 'kill -CONT \"$child\" 2>/dev/null || :; kill -TERM \"$child\" 2>/dev/null || :; wait \"$child\" 2>/dev/null || :' EXIT\n"
    check=f'/^State:/ {{a=($2=="T")}} /^Uid:/ {{b=($2=={uid} && $3=={uid} && $4=={uid} && $5=={uid})}} /^CapEff:/ {{c=($2=="0000000000000000")}} /^NoNewPrivs:/ {{d=($2==1)}} END {{exit !(a&&b&&c&&d)}}'
    sh+=f'i=0; while ! /bin/busybox awk {q(check)} "/proc/$child/status"; do i=$((i+1)); [ "$i" -le 500 ]; /bin/busybox sleep 0.02; done\n'
    user_root=context.parent.resolve()
    for idx,r in enumerate(rows):
        src=stage/str(idx);dest=Path(r['name'])
        assert dest.resolve()==dest and dest.is_file() and not dest.is_symlink()
        if dest.is_relative_to(user_root):
            assert (idx in (0,1,2,12,13)) and dest.stat().st_uid==uid
        else:
            assert idx in (*range(3,12),14) and dest.parent==Path('/usr/lib/x86_64-linux-gnu')
            assert dest.name in (*SYSTEM,'libcrypto.so.3') and dest.stat().st_uid==0
        a=q(str(src));b=q(str(dest))
        sh+=f'/bin/busybox mount -o bind {a} {b}\n/bin/busybox mount -o remount,bind,ro {b}\n'
        sh+=f'[ "$(/bin/busybox stat -c %d:%i {a})" = "$(/bin/busybox stat -c %d:%i {b})" ]\n'
    sh+='kill -CONT "$child"; rc=0; wait "$child" || rc=$?; trap - EXIT; exit "$rc"\n'
    (context.parent/'namespace.sh').write_text(sh)
    sp.run(['sudo','-n','unshare','--mount','--propagation','private','--','/bin/busybox','sh','-c',sh],check=True)
