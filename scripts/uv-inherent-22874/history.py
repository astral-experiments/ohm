"""Create real in-place A→B edits and cloned, inode-independent complete Cargo checkpoints."""
import gzip,hashlib,json,os,shutil,stat,subprocess,tomllib
from pathlib import Path
import core as c
m=c.m;P=c.P
def guard_space(*paths):
    for p in paths:c.guard(shutil.disk_usage(p).free>=80<<30,('80 GiB private runner reserve',str(p)))
def git(*args):return m.sha_git(m.SRC,*args)
def clean(path):
    c.guard(path.parent.is_relative_to(m.ROOT)and path.is_relative_to(m.ROOT)and path not in(m.SRC,m.SDK,m.CARGO_HOME)and not path.is_symlink(),'private target only')
    if path.exists():shutil.rmtree(path)
def state(rev):
    file=m.SRC/P['file'];status=git('status','--porcelain=v1').decode().splitlines();delta=git('diff','--binary','--full-index')
    c.guard(git('rev-parse','HEAD').decode().strip()==P['A']and git('write-tree').decode().strip()==P['A_tree'],'HEAD/index left authenticated parent')
    c.guard(not git('ls-files','--others','--exclude-standard')and(status==[]and not delta if rev=='A'else status==[' M '+P['file']]and m.digest(delta)==P['edit_sha256']),'unexpected working-tree edit')
    c.guard(m.filesha(file)==P[rev+'_file']and m.filesha(m.SRC/'Cargo.lock')==P['lock_sha256'],'wrong source or lock')
    return {'head':P['A'],'index':P['A_tree'],'working_tree':P[rev+'_tree'],'source':P[rev+'_file'],'lock':P['lock_sha256'],'patch_sha256':m.digest(delta),'source_mtime_ns':file.stat().st_mtime_ns}
def write(rev,stamp=None):
    content=git('show',P[rev]+':'+P['file']);c.guard(m.digest(content)==P[rev+'_file'],'untrusted edit')
    f=m.SRC/P['file'];f.write_bytes(content)
    if stamp is not None:os.utime(f,ns=(stamp,stamp))
    return state(rev)
def open_source(workspace,bank):
    c.guard(not m.ROOT.exists(),'unexpected prior workload/target');m.ROOT.mkdir()
    for p in(m.HOME,m.CARGO_HOME,bank):p.mkdir()
    donor=workspace/'uv-source';c.guard(m.sha_git(donor,'rev-parse','HEAD').decode().strip()==P['B']and m.sha_git(donor,'rev-parse',P['B']+'^').decode().strip()==P['A'],'wrong landed edit')
    subprocess.run(['git','init','-q','--',m.SRC],env=m.ENV,check=True,timeout=30)
    subprocess.run(['git','-C',m.SRC,'fetch','-q','--no-tags','--depth=2',donor.as_uri(),'HEAD'],env=m.ENV,check=True,timeout=120)
    c.guard(git('rev-parse','FETCH_HEAD').decode().strip()==P['B'] and git('rev-parse',P['B']+'^').decode().strip()==P['A'],'materialized both authenticated snapshots')
    subprocess.run(['git','-C',m.SRC,'checkout','-q','-b','qualified-parent',P['A']],env=m.ENV,check=True)
    c.guard(git('rev-parse',P['B']+'^{tree}').decode().strip()==P['B_tree']and git('diff','--name-only',P['A'],P['B']).decode().splitlines()==[P['file']],'source trees')
    return state('A')
def verify_registry():
    raw=gzip.decompress((c.HERE/'registry-proof.json.gz').read_bytes());c.guard(m.digest(raw)==P['registry_uncompressed_sha256'],'bank receipt')
    bank=json.loads(raw);lock={p['name']+'@'+p['version']:p['checksum']for p in tomllib.loads((m.SRC/'Cargo.lock').read_text())['package']if 'source'in p}
    registry=m.CARGO_HOME/'registry';cache,=(registry/'cache').iterdir();index,=(registry/'index').iterdir();c.guard(cache.name==index.name and set(lock)==set(bank)and len(bank)==654,'full archive/index roster')
    indices={}
    for namever,row in bank.items():
        name,ver=namever.rsplit('@',1);crate=cache/(name+'-'+ver+'.crate');c.guard(crate.is_file()and crate.stat().st_size==row['archive_bytes']and m.filesha(crate)==lock[namever]==row['archive_sha256'],('locked archive',namever))
        ip=index/row['index_relative']
        if ip not in indices:indices[ip]=[json.loads(x)for x in ip.read_bytes().split(b'\0')if x.startswith(b'{')]
        record,=[x for x in indices[ip]if(x.get('name'),x.get('vers'))==(name,ver)]
        c.guard(record['cksum']==lock[namever]and m.digest(m.canon(record))==row['index_record_sha256'],('full sparse registry record',namever))
    return {'archives':len(bank),'sha256':m.digest(raw),'total_archive_bytes':sum(x['archive_bytes']for x in bank.values()),'namespace':cache.name}
def graph():
    argv=[*c.CHECK,'--unit-graph','-Zunstable-options'];raw=subprocess.check_output(argv,cwd=m.SRC,env=m.ENV|{'RUSTC_BOOTSTRAP':'1'},timeout=120)
    v=c.scope.structural(json.loads(raw),m.SRC,m.CARGO_HOME/'registry/src');c.guard(c.scope.digest(v)==P['structural_graph_sha256']and len(v['units'])==P['plan_units']and v['roots']==[P['root_unit']],'full actual Cargo package unit graph')
    return {'argv':argv,'logical_sha256':c.scope.digest(v),'units':len(v['units']),'root':v['roots']}
def file_set(root):
    c.guard(root.is_dir()and not root.is_symlink(),'checkpoint root')
    rows={}
    for base,dirs,files in os.walk(root,followlinks=False):
        base=Path(base)
        for name in sorted(dirs+files):
            p=base/name;r=str(p.relative_to(root));s=p.lstat()
            if p.is_symlink():v=['link',os.readlink(p)]
            elif stat.S_ISREG(s.st_mode):v=['file',s.st_size,m.filesha(p)]
            elif stat.S_ISDIR(s.st_mode):v=['dir']
            else:raise ValueError(('unsupported checkpoint member',r))
            rows[r]=v+[stat.S_IMODE(s.st_mode),s.st_mtime_ns]
    return rows
def checkpoint(role,hold,bank):
    seed=bank/(role+'-A-'+str(hold));c.guard(not seed.exists(),'fresh A checkpoint')
    m.TARGET.rename(seed);fs=file_set(seed);return seed, {'sha256':m.digest(m.canon(fs)),'count':len(fs),'role':role,'hold':hold}
def restore(seed,seal,provider_relative,a_time):
    guard_space(seed);clean(m.TARGET);write('A',a_time)
    c.guard(m.digest(m.canon(file_set(seed)))==seal['sha256'],'checkpoint prior contents or times changed')
    subprocess.run(['/usr/bin/cp','-a','--reflink=auto','--',seed,m.TARGET],check=True,timeout=300)
    c.guard(m.digest(m.canon(file_set(m.TARGET)))==seal['sha256']and (seed/provider_relative).stat().st_ino!=(m.TARGET/provider_relative).stat().st_ino,'restored A differs or shares inode')
    s=write('B');c.guard(s['source_mtime_ns']>a_time,'B did not advance A input mtime');return s
