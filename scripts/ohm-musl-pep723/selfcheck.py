"""Price and validate the new study's source and native oracles on the actual retained signed baseline."""
import argparse, importlib.util, json, os, subprocess, tempfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
sp=importlib.util.spec_from_file_location('case',HERE/'run.py');case=importlib.util.module_from_spec(sp);sp.loader.exec_module(case)
def sink(source, original, tmp, execute):
    git=lambda *a:subprocess.check_output(['git','-C',source,*a])
    a,b=(case.SRC[n] for n in ['old','new'])
    for role,rec in [('old',a),('new',b)]:
        assert git('rev-parse',rec['commit']+'^{tree}').decode().strip()==rec['tree']
        assert case.digest(git('show',rec['commit']+':Cargo.lock'))==rec['cargo_lock_sha256']
        assert case.digest(git('show',rec['commit']+':'+rec['path']))==rec['file_sha256']
    assert git('rev-parse',b['commit']+'^').decode().strip()==a['commit']
    src=git('show',b['commit']+':'+b['path']);wrong=case.wrong_source(src);invalid=case.invalid_source(src)
    assert case.digest(wrong)==case.PLAN['states']['wrong'] and case.digest(invalid)==case.PLAN['states']['invalid']
    assert wrong.split(b'#[cfg(test)]',1)[1]==src.split(b'#[cfg(test)]',1)[1]
    at=case.PLAN['E0308'];assert invalid[at['byte_start']:at['byte_end']]==b'"ohm_26693_type_error"'
    at_line=invalid[:at['byte_start']].count(b'\n')+1;assert at_line==at['line']
    assert len(case.PLAN['venues'])==11 and len(set(case.PLAN['venues']))==11 and len(case.ADDED)==4
    result={'source_tree_pair':[a['tree'],b['tree']],'wrong_src':case.digest(wrong),'invalid_src':case.digest(invalid),'E0308_bytes_line':at,'source_changed_only_in_production_for_wrong_semantics':True,'tested_enrolled_roles':False,'preexisting_signed_baseline':{}}
    if execute:
        test=object.__new__(case.Study);test.source=source;test.products=original/'elf';test.env={'PATH':'/usr/bin:/bin','LC_ALL':'C','TZ':'UTC'}
        p=case.load(original/'result.json')
        for st,n in [('old','old-cold'),('new','new-edit')]:
            hs=p['visits'][n]['elf']['sha256'];raw=subprocess.check_output(['zstd','-dc',test.products/(hs+'.zst')]);assert case.digest(raw)==hs
            fd=os.memfd_create('qualified-signed-test',0);os.fchmod(fd,0o700)
            with os.fdopen(os.dup(fd),'wb') as f:f.write(raw)
            try:
                dest=tmp/st;dest.mkdir();r=test.test_program(Path('/proc')/str(os.getpid())/'fd'/str(fd),st,dest)
                assert r['sha256']==hs and r['inventory']['stdout']==p['visits'][n]['inventory_sha256']
                result['preexisting_signed_baseline'][st]={'elf':hs,'count':len(r['names']),'inventory':r['inventory']['stdout'],'all_tests_exit':r['all']['exit'],'selections':{k:[v['selected'],v['failed']] for k,v in r['individual'].items()}}
            finally:os.close(fd)
    return result
if __name__=='__main__':
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('--ruff',type=Path,required=True);a.add_argument('--original',type=Path);a.add_argument('--execute',action='store_true');s=a.parse_args()
    with tempfile.TemporaryDirectory() as tmp:print(json.dumps(sink(s.ruff,s.original,Path(tmp),s.execute),sort_keys=True,indent=2))
