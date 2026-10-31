"""Reopen actual rustc incremental graphs under one forced stamp. All temporary paths are private."""
import argparse, hashlib, json, os, shutil, struct, subprocess
from pathlib import Path

def digest(b):
    return hashlib.sha256(b).hexdigest()

def root_version(data):
    assert data[:4] == b'rust'
    n = shift = 0
    for pos in range(16, 21):
        byte = data[pos]
        n |= (byte & 127) << shift
        if byte < 128:
            return data[pos+1:pos+1+n].decode()
        shift += 7
    raise AssertionError('invalid rmeta string length')

def graph_files(root):
    return [p for p in root.rglob('dep-graph.bin') if p.parent.name.startswith('s-') and not p.parent.name.endswith('-working')]

def graph_header(p):
    b = p.read_bytes()
    assert b[:4] == b'RSIC'
    return dict(version=struct.unpack_from('<H', b, 4)[0], stamp=b[7:7+b[6]].decode(), sha=digest(b))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old',type=Path,required=True,help='complete signed-stage SDK root')
    parser.add_argument('--new',type=Path,help='matched candidate SDK; omit only to calibrate the old compiler')
    parser.add_argument('--work',type=Path,required=True,help='fresh nonexistent workspace')
    parser.add_argument('--old-generation',type=int,default=8)
    parser.add_argument('--new-generation',type=int,default=9)
    a=parser.parse_args()
    sdk={'old':a.old.resolve()};gens={'old':a.old_generation};epochs={'old':1}
    if a.new:
        sdk['new']=a.new.resolve();gens['new']=a.new_generation;epochs['new']=2
    w=a.work.resolve();w.mkdir();os.chdir(w);(w/'rustup/toolchains').mkdir(parents=True);(w/'raw').mkdir()
    stamp='ohm-checked-generics-identical-incremental-cfg-version'
    env=os.environ|{'RUSTUP_HOME':str(w/'rustup'),'RUSTC_FORCE_RUSTC_VERSION':stamp,'RUSTC_LOG':'ohm_metadata_reuse=info'}
    (w/'subject.rs').write_text('pub fn value() -> u32 { 17 }\n')
    (w/'reader.rs').write_text('extern crate subject; fn main() { assert_eq!(subject::value(), 17); }\n')
    snapshots=[];visits=[];versions={};rustc_versions={}
    def alias(role):
        link=w/'rustup/toolchains/ohm'
        if link.is_symlink(): link.unlink()
        link.symlink_to(sdk[role],target_is_directory=True)
    def run(role,label,cmd,ok=True):
        alias(role);p=subprocess.run(cmd,env=env,capture_output=True)
        loc=w/'raw'/label;loc.mkdir()
        for name,data in [('stdout',p.stdout),('stderr',p.stderr)]: (loc/name).write_bytes(data)
        visits.append(dict(arm=role,label=label,cmd=cmd,exit=p.returncode,stdout=digest(p.stdout),stderr=digest(p.stderr)))
        (w/'partial.json').write_text(json.dumps(dict(commands=visits,snapshots=snapshots),indent=2)+'\n')
        assert (p.returncode==0)==ok,(cmd,p.returncode,p.stderr.decode(errors='replace')[-1500:])
        return p
    def compiler(role,label,args,ok=True):
        return run(role,label,['rustc','+ohm',*args],ok)
    for role in sdk:
        v=compiler(role,'tool-'+role,['-vV']);rustc_versions[role]=v.stdout.decode()
    if a.new: assert len(set(rustc_versions.values()))==1,'not a true complete-version match'
    def visit(role,label,state):
        p=compiler(role,label,['subject.rs','--crate-name','subject','--crate-type','rlib','--emit=metadata,link',
            '-Cincremental=inc','-Zpublic-api-hash=yes','-Zassert-incr-state='+state,'-Cmetadata=unchanged-owned-fixture'])
        graphs=graph_files(w/'inc');assert len(graphs)==1,graphs
        g=graphs[0];header=graph_header(g);assert header['stamp']==stamp and header['version']==gens[role],(header,gens[role])
        data=(w/'libsubject.rmeta').read_bytes();health=root_version(data)
        suffix=f' (Ohm metadata {epochs[role]})';assert health.endswith(suffix),health
        versions[role]=health[:-len(suffix)]
        if len(versions)>1:assert len(set(versions.values()))==1,'not a true rmeta compiler stamp match'
        rmeta=g.parent/'metadata.rmeta';assert rmeta.read_bytes()==data
        prefixes={x.name:digest(x.read_bytes()) for x in g.parent.glob('*.ohm-prefix-*')}
        if state=='not-loaded':assert prefixes, 'no real prefix work product was collected'
        if label.startswith('switch'):assert b'reused metadata item prefix' not in p.stderr
        snapshots.append(dict(arm=role,label=label,graph=header,metadata_version=health,
             metadata_sha=digest(data),rlib_sha=digest((w/'libsubject.rlib').read_bytes()),prefix=prefixes))
        shutil.copyfile(w/'libsubject.rmeta',w/'raw'/label/'libsubject.rmeta')
        compiler(role,label+'-reader',['reader.rs','--extern','subject=libsubject.rlib','-o','reader'])
        run(role,label+'-run',['./reader'])
    visit('old','train-old','not-loaded');visit('old','reopen-old','loaded')
    if a.new:
        for src,dst in [('old','new'),('new','old')]:
            inc='reopen-'+src
            bad=compiler(dst,'reject-user-'+src,['reader.rs','--emit=metadata','--error-format=json','--extern','subject='+str(w/'raw'/inc/'libsubject.rmeta')],False)
            errors=[j for line in bad.stderr.splitlines() if line.startswith(b'{') and (j:=json.loads(line)).get('level')=='error']
            assert any((e.get('code') or {}).get('code')=='E0514' for e in errors),errors
            visit(dst,'switch-'+dst,'not-loaded');visit(dst,'reopen-'+dst+('2' if dst=='old' else ''),'loaded')
    else:
        # This control changes only the on-disk dep graph generation. Keep the real version stamp,
        # both adjacent query/work-product files and a separate copy of the original intact.
        g,=graph_files(w/'inc');b=bytearray(g.read_bytes());(w/'raw'/'original.dep-graph').write_bytes(b)
        b[4:6]=struct.pack('<H',gens['old']+1)
        tmp=g.with_name('replacement.tmp');tmp.write_bytes(b);tmp.replace(g)
        visit('old','switch-synthetic-generation','not-loaded');visit('old','reopen-repaired','loaded')
    out=dict(compiler_versions=rustc_versions,issuer='actual rustc -Zassert-incr-state',forced_graph_stamp=stamp,commands=visits,
             fresh_user_cross_rejected=bool(a.new),snapshots=snapshots,locality='owned canonical paths each arm; no compilation timing')
    q=w/'completed.json';q.write_text(json.dumps(out,indent=2)+'\n')
    print('commands',len(visits),'graph_states',[(x['label'],x['graph']['version']) for x in snapshots],digest(q.read_bytes()))
if __name__=='__main__': main()
