"""Native cold producers, observed Cargo build-script output directories, and the complete off-clock unit graph."""
from pathlib import Path
import json,os,subprocess
from basis import EVENTS,filehash,read,receive,writez
def cold(e,out):
    out.mkdir();fid=EVENTS['file_id'](e.bin);workspace={};scripts={};base=e.target/'debug/build'
    def visit(pid,old,im):
        if im['file']==fid:workspace[pid]=os.readlink('/proc/'+str(pid)+'/cwd')
        exe=Path(im['exe'])
        if not exe.is_relative_to(base)or exe.parent.name!='out' or len(exe.relative_to(base).parts)!=4:return
        vals={}
        for item in Path('/proc/'+str(pid)+'/environ').read_bytes().split(b'\0'):
            key,sep,value=item.partition(b'=')
            if sep and key in (b'CARGO_PKG_NAME',b'CARGO_PKG_VERSION',b'CARGO_MANIFEST_DIR',b'OUT_DIR',b'TARGET',b'HOST'):vals[key.decode()]=os.fsdecode(value)
        if vals.get('OUT_DIR'):
            assert len(vals)==6 and Path(vals['OUT_DIR']).is_relative_to(base)
            scripts[pid]={'exe':im['exe'],'file':im['file'],'variables':vals,'binary_sha256':filehash(exe)}
    EVENTS['capture'](out,e.argv,e.env,str(e.src),fid,visit)
    original=read(out/'kernel-events.json');t=EVENTS['decode'](original);accepted=receive(e,t,workspace,'cold');assert not(out/'stdout').stat().st_size and b'Finished 'in(out/'stderr').read_bytes()
    real={z['pid']:z for z in t['images']if z['file']==fid};producers=[];dirs={}
    for name,pid,parent in accepted['all_units']:
        argv=real[pid]['argv'];directory=Path(argv[argv.index('--out-dir')+1]);source,=[i for i in argv[1:]if i.endswith('.rs')and not i.startswith('-')]
        source_path=Path(workspace[pid])/source;assert source_path.is_file()
        for file in directory.iterdir():
            if file.is_file()and not file.is_symlink()and file.suffix in('.rmeta','.so','.rlib'):
                key=str(file.relative_to(e.target))
                if key not in dirs:dirs[key]=[file.stat().st_size,filehash(file)]
        producers.append({'pid':pid,'cargo':parent,'argv':argv,'source_file_sha256':filehash(source_path),'cwd':workspace[pid]})
    writez(out/'producer-evidence.json.gz',{'compilers':producers,'build_scripts':scripts,'products':dirs,'target':str(e.target),'workspace':str(e.src),'registry_src':str(e.cargo/'registry/src')})
    writez(out/'kernel.json.gz',original);(out/'kernel-events.json').unlink();writez(out/'argv.json.gz',accepted);writez(out/'cwd.json.gz',workspace)
    target=e.root/'graph-only';proc=subprocess.run([*e.argv,'-Z','unstable-options','--unit-graph'],cwd=e.src,env=dict(e.env,CARGO_TARGET_DIR=str(target)),capture_output=True,check=True)
    graph=json.loads(proc.stdout);assert graph['version']==1 and len(graph['roots'])==1;writez(out/'full-unit-graph.json.gz',graph)
    return accepted
