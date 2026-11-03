from pathlib import Path
import errno,hashlib,json,os,shutil,subprocess as sp,time
import argparse
parser=argparse.ArgumentParser(description='Observe the unchanged published Linux release on an ordinary filesystem.')
parser.add_argument('--work',type=Path,required=True)
parser.add_argument('--sdk',type=Path,required=True)
parser.add_argument('--rustup-home',type=Path,required=True)
args=parser.parse_args()
here=Path(__file__).resolve().parent
p=args.work.resolve();p.mkdir();assert os.getuid()!=0
sdk=args.sdk.resolve(strict=True)
sp.run(['cc','-Wall','-Wextra','-Werror','-O2',str(here/'stat-file.c'),'-o',str(p/'inspect')],check=True)
manifest=json.loads((here.parent/'ron-ordinary-backend/release-compiler.json').read_bytes())
assert len(manifest['members'])==79 and manifest['tar_sha256']=='ecde6809d7f1fc1966798198479867c4a49bdf7a51f3873336d23a40fabce453'
def sha(f):
    with f.open('rb')as s:return hashlib.file_digest(s,'sha256').hexdigest()
def dump(file,obj):file.write_text(json.dumps(obj,sort_keys=True,indent=2)+'\n')
for name,r in manifest['members'].items():
    f=sdk/name;assert f.stat().st_size==r['bytes']and sha(f)==r['sha256']
r=p/'case';r.mkdir();src=r/'work';src.mkdir();(src/'src').mkdir()
(src/'Cargo.toml').write_text('[package]\nname="regular_generation"\nversion="0.0.0"\nedition="2021"\n[profile.dev]\nopt-level=1\n')
(src/'Cargo.lock').write_text('version = 4\n\n[[package]]\nname = "regular_generation"\nversion = "0.0.0"\n')
(src/'src/main.rs').write_text('fn main(){println!("{}", 17);}\n')
env={k:v for k,v in os.environ.items()if k in ('HOME','PATH','USER','LANG')}
env.update(RUSTUP_HOME=str(args.rustup_home.resolve(strict=True)),CARGO_HOME=str(r/'cargo-home'),CARGO_TARGET_DIR=str(r/'target'),CARGO_BUILD_BUILD_DIR=str(r/'shared'))
assert 'f5a51d8cc3e76236c2d0f17d495d59ebb03306e4' in sp.check_output(['rustc','+ohm','-vV'],env=env,text=True)
assert 'abc70d60a6fd89c10d5f65cf85820d9b78d5affe' in sp.check_output(['cargo','+ohm','-vV'],env=env,text=True)
def descendants(pid):
    v=[pid];out=[]
    while v:
        n=v.pop();out.append(n)
        for task in (Path('/proc')/str(n)/'task').glob('[0-9]*'):
            try: children=(task/'children').read_text().split()
            except FileNotFoundError: continue
            v.extend(map(int,children))
    return out
rows={};products={}
for label in ('empty','unchanged','second-empty'):
    if label=='second-empty':
        for tree in ('target','shared'):
            if(r/tree).is_dir():(r/tree).rename(r/('first-'+tree))
    at=r/label;at.mkdir();maps={};owners={};live=[]
    with(at/'stdout').open('wb')as so,(at/'stderr').open('wb')as se:
        proc=sp.Popen(['cargo','+ohm','build','--locked','--offline','-j4','--message-format=json'],env=env,cwd=src,stdout=so,stderr=se)
        while proc.poll()is None:
            for pid in descendants(proc.pid):
                pr=Path('/proc')/str(pid)
                try:
                    if not(pr/'exe').samefile(sdk/'bin/rustc'):continue
                    av=(pr/'cmdline').read_bytes().split(b'\0')
                    if b'--crate-name'not in av or av[av.index(b'--crate-name')+1]!=b'regular_generation':continue
                    owners[pid]=[os.fsdecode(a)for a in av[:-1]]
                    for line in (pr/'maps').read_text().splitlines():
                        x=line.split(None,5)
                        if len(x)!=6 or 'x'not in x[1] or not x[5].startswith('/'):continue
                        f=Path(x[5]);st=f.stat();actual=tuple(int(n,16)for n in x[3].split(':'));named=(os.major(st.st_dev),os.minor(st.st_dev))
                        if str(f)in maps:continue
                        mapname=pr/'map_files'/x[0]
                        try:
                            fd=os.open(mapname,os.O_RDONLY|os.O_CLOEXEC)
                        except OSError as e:opened={'errno':e.errno}
                        else:
                            m=os.fstat(fd);os.close(fd);opened={'dev':[os.major(m.st_dev),os.minor(m.st_dev)],'ino':m.st_ino}
                        maps[str(f)]={'dev':actual,'ino':int(x[4]),'held_dev':named,'held_ino':st.st_ino,'uid':st.st_uid,'map_file':opened,'raw':line}
                except (FileNotFoundError,ProcessLookupError,PermissionError):continue
            time.sleep(.002)
        assert proc.returncode==0,(at/'stderr').read_text()
    j=[json.loads(x)for x in (at/'stdout').read_bytes().splitlines()];assert j[-1]=={'reason':'build-finished','success':True}
    unit,=[x for x in j if x['reason']=='compiler-artifact'and x['target']['name']=='regular_generation']
    dump(at/'raw-map-capture.json',dict(unit_fresh=unit['fresh'],owners=owners,maps=maps))
    assert unit['fresh']==(label=='unchanged') and bool(owners)==(label!='unchanged'),(label,unit['fresh'],owners)
    exe=Path(unit['executable']);assert sp.check_output([exe])==b'17\n';products[label]=sha(exe)
    arch={}
    for name,v in maps.items():
        file=Path(name);s=json.loads(sp.check_output([p/'inspect',file]));assert tuple(s['dev'])==v['held_dev'] and s['ino']==v['held_ino']
        arch[name]=dict(v,physical=s,sha256=sha(file))
    if owners:
        assert len(owners)==1 and len(maps)>=8 and str(sdk/'bin/rustc') in maps and any('libLLVM.so'in name for name in maps) and any('librustc_driver-'in name for name in maps)
        for v in maps.values():assert v['dev']==v['held_dev']and v['ino']==v['held_ino'],v
    dump(at/'observed.json',dict(owners=owners,maps=arch,elf=products[label],source=sha(src/'src/main.rs')))
    rows[label]={'physical_rustcs':len(owners),'samefile_maps':len(maps),'ext4':sum(1 for v in arch.values()if v['physical']['fstype']==0xef53),'required_others':[Path(n).name for n,v in arch.items()if v['uid']!=os.geteuid() and v['physical']['verity'][0]<0 and v['physical']['seals'][0]<0],'sha256':sha(at/'observed.json')}
assert len(set(products.values()))==1 and rows['empty']['ext4'] and len(rows['empty']['required_others'])>0
dump(p/'result.json',dict(rows=rows,program=products,ordinary_compiler=manifest['tar_sha256'],normal_gate='real mandatory non-owned mapped executable has no verity or seal; no read lease attempted on shared files',proc_status=Path('/proc/self/status').read_text(),mountinfo=Path('/proc/self/mountinfo').read_text()))
print(rows)
