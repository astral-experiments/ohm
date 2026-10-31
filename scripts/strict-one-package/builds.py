"""The two separately enrolled ordinary linked Unicode builds with an actual source hunk and reader."""
from pathlib import Path
import gzip,json,os,subprocess
HIST='bfedc614b7670b8766576b64afd426c292f8c2ce';PATH='crates/ruff_unicode_names2_generator/src/lib.rs';OLD=b'    let num_escapes = (lexicon_words.len() + 255) / 256;\n';NEW=b'    let num_escapes = lexicon_words.len().div_ceil(256);\n'
COMMAND=['cargo','+ohm','build','-p','ruff_unicode_names2','--lib','--locked','--offline','-j4','--message-format=json']; READER=b'extern crate unicode_names2; fn main(){for key in ["NULL","NUL","LATIN CAPITAL LETTER A","SNOWMAN"] {println!("{:?}",unicode_names2::character(key).map(u32::from));}}\n'

def study(b,env,select,keep,direction,order):
    m=b.m;src=m.src;lib=src/PATH;baseline=lib.read_bytes();assert m.h(baseline)=='9e66456a0167e332cd50175f529708362c2fa2ce1f5c17daf34d3b87c2e46669' and baseline.count(NEW)==1 and OLD not in baseline
    m.w.git(src,'fetch','-q','--no-tags','--depth=2','https://github.com/astral-sh/ruff.git',HIST);oldhist=m.w.git(src,'show',HIST+'^:'+PATH);newhist=m.w.git(src,'show',HIST+':'+PATH);assert oldhist.count(OLD)==newhist.count(NEW)==1 and NEW not in oldhist and OLD not in newhist
    parent=baseline.replace(NEW,OLD);d=m.O/'ordinary-lib';d.mkdir();m.gz(d/'public-commit-diff.gz',m.w.git(src,'diff','--binary',HIST+'^',HIST,'--',PATH));m.save(d/'input.json',{'hunk':HIST,'parent_git_file':m.h(oldhist),'new_git_file':m.h(newhist),'base':m.h(baseline),'reverse':m.h(parent),'argv':COMMAND,'reader':READER.decode()});work=m.R/'reader-stable';work.mkdir();rs=work/'reader.rs';rs.write_bytes(READER);summ={}
    first=parent if direction=='forward' else baseline;second=baseline if direction=='forward' else parent
    def visit(arm,label,mode):
        dest=d/('opt'+arm)/label;dest.mkdir(parents=True);m.w.room(m.R,15);select(env,arm)
        if mode=='score':args=[m.R/'watch',dest/'whole.json',*COMMAND]
        else:
            ext=dest/'kernel';ext.mkdir();args=[m.R/'capture',ext,'/usr/bin/false','cal',*COMMAND]
        proc=subprocess.run(args,cwd=src,env=env,capture_output=True,timeout=240);m.gz(dest/'stdout.gz',proc.stdout);m.gz(dest/'stderr.gz',proc.stderr);assert proc.returncode==0,(proc.stderr[-600:],proc.stdout[-600:]);rows=[json.loads(l) for l in proc.stdout.splitlines()];assert rows[-1]=={'reason':'build-finished','success':True} and not any(r.get('message',{}).get('level')=='error' for r in rows)
        art,=[r for r in rows if r['reason']=='compiler-artifact' and r['target']['name']=='unicode_names2' and r['target']['kind']==['lib']];p,=[Path(v) for v in art['filenames'] if v.endswith('.rlib')];gen,=[Path(r['out_dir']) for r in rows if r['reason']=='build-script-executed' and r['package_id']==art['package_id']];files={f.name:m.sha(f) for f in gen.glob('*.rs')};assert sorted(files)==b.generated_names
        for f in gen.glob('*.rs'):
            blob=m.O/'generated'/(files[f.name]+'.gz');
            if not blob.exists():m.gz(blob,f.read_bytes())
        generator,=[Path(path) for r in rows if r['reason']=='compiler-artifact' and r['package_id']==art['package_id'] and r['target']['kind']==['custom-build'] for path in r['filenames'] if Path(path).name in ('build-script-build','build_script_build')];image=keep(generator,'ordinary-lib/'+label)
        dirs=sorted({x.parent for tree in (m.S/'target',m.S/'shared') for pattern in ('*.rlib','*.rmeta') for x in tree.rglob(pattern)});output=work/'reader';cmd=['rustc','+ohm','--edition=2024',rs,'--extern','unicode_names2='+str(p),*['-Ldependency='+str(q) for q in dirs],'-o',output];m.run(cmd,env=env);read=m.get([output],env=env);assert read==b'Some(0)\nSome(0)\nSome(65)\nSome(9731)\n',read;returned=keep(output,'ordinary-lib-reader/'+label)
        v={'source':m.sha(lib),'generated':files,'generator':image,'reader':read.decode(),'reader_elf':returned,'rlib':[str(p),m.sha(p)],'dirty':[r['target']['name'] for r in rows if r['reason']=='compiler-artifact' and not r['fresh']],'role':arm,'label':label,'mode':mode,'reader_cmd':list(map(str,cmd))}
        if mode=='score':
            counter=m.read(dest/'whole.json');assert b.hw(counter) and counter['code']==0;v['instructions']=counter['instructions'];v['storage']=b.storage(dest)
        else:
            trace=m.argv(ext);wildid=[b.wild.stat().st_dev,b.wild.stat().st_ino];rustid=[b.rust.stat().st_dev,b.rust.stat().st_ino];real=[(pid,a[a.index('-o')+1]) for pid,i,x,f,a in trace if i==wildid and '-o' in a];host=[(pid,f) for pid,i,x,f,a in trace if Path(f).name in ('build_script_build','build-script-build') and 'ruff_unicode_names2' in f];assert len(host)==1 and len([o for p,o in real if o==host[0][1]])==1;v['wild']=real;v['physical_generator']=host;v['physical_rustcs']=[(pid,a[a.index('--crate-name')+1]) for pid,i,x,f,a in trace if i==rustid and '--crate-name' in a and '--out-dir' in a and not any(o.startswith('--print') for o in a)]
        m.save(dest/'build.json',v);return v
    try:
        for arm in order:
            b.clear();lib.write_bytes(first);cold=visit(arm,'cold','score');neutral=visit(arm,'neutral-unchanged','score');lib.write_bytes(second);edit=visit(arm,'historical-hunk','score');warm=visit(arm,'first-unchanged','score');trace=visit(arm,'traced-repeat','trace');b.clear();ref=visit(arm,'independent-empty','trace');assert cold['source']!=edit['source'] and warm['source']==edit['source']==ref['source'] and 'unicode_names2_generator' in edit['dirty']
            assert all(v['generated']==cold['generated'] and v['reader']==cold['reader'] for v in (neutral,edit,warm,trace,ref));assert warm['reader_elf']['sha256']==ref['reader_elf']['sha256'];summ[arm]={'instructions':{v['label']:v['instructions'] for v in (cold,neutral,edit,warm)},'observed_clean':True,'generated':warm['generated']};b.clear()
        assert summ['0']['generated']==summ['1']['generated'];m.save(d/'complete.json',summ)
    finally:lib.write_bytes(baseline)
