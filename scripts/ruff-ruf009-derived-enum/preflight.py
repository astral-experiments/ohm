"""Local source, decoder, native verdict, clock and fault checks. Never starts rustc or Cargo."""
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import review
from review import need, read

def rejects(fn):
    try:fn()
    except (ValueError,AssertionError):return
    raise AssertionError('false acceptance')

def main(ruff, signed):
    with tempfile.TemporaryDirectory()as td:
        temp=Path(td);os.environ['RUNNER_TEMP']=os.environ['GITHUB_WORKSPACE']=str(temp)
        import case, qualification
        cfg=case.REG
        need(subprocess.check_output(['git','-C',ruff,'rev-parse',cfg['base']+'^{tree}']).decode().strip()==cfg['tree'],'wrong pinned Ruff Git tree')
        repo=temp/'source';repo.mkdir();q=repo/cfg['path'];q.parent.mkdir(parents=True)
        for name in (cfg['path'],'Cargo.lock'):
            (repo/name).write_bytes(subprocess.check_output(['git','-C',ruff,'show',cfg['base']+':'+name]))
        need(case.sha(q)==case.PORT['fixed'] and case.sha(repo/'Cargo.lock')==cfg['lock']['sha256'],'wrong original files')
        for args in (['init','-q'],['add','.'],['-c','user.name=preflight','-c','user.email=case@example.invalid','commit','-qm','private source fixture']):
            subprocess.run(['git','-C',repo,*args],check=True)
        original_base,original_tree=cfg['base'],cfg['tree'];case.w.SRC=repo
        cfg['base']=case.w.git(repo,'rev-parse','HEAD');cfg['tree']=case.w.git(repo,'rev-parse','HEAD^{tree}')
        try:
            for state in ('buggy','buggy','fixed','fixed','buggy','fixed'):
                old=q.stat().st_mtime_ns;before=case.sha(q);need(case.source(state)==state and case.sha(q)==case.PORT[state],'bad transition')
                if before==case.PORT[state]:need(q.stat().st_mtime_ns==old,'no-op rewrote source')
            q.write_bytes(q.read_bytes()+b' ');rejects(lambda:case.source())
            q.write_bytes((signed/'modern/fixed.rs').read_bytes())
            junk=repo/'unexpected';junk.write_text('x');rejects(lambda:case.source());junk.unlink()
        finally:cfg['base'],cfg['tree']=original_base,original_tree
        version='rustc 1.99.0-dev (d57fd1515 2026-11-02) (ohm-1.99.0-23) (Ohm metadata 3)'
        pair=[]
        for label in ('buggy-edit','repaired-edit'):
            f=signed/'modern'/label;body=subprocess.check_output(['zstd','-dcq',f/'original.rmeta.zst'])
            record=review.metadata.table(body,'ruff_linter',version,cfg['edition'])
            need(record==json.loads(json.dumps(record)),'wire identity')
            h=read(f/'result.json')['metadata']['ruff_linter']
            need(record['header']['full']==h['sha256'] and h['public']=='Public hash: '+bytes.fromhex(record['header']['public'])[::-1].hex(),'page identity or raw public display mismatch')
            rejects(lambda:review.metadata.table(body,'ruff_graph',version,cfg['edition']))
            rejects(lambda:review.metadata.table(body,'ruff_linter',version,'2021'))
            rejects(lambda:review.metadata.table(b'X'+body[1:],'ruff_linter',version,cfg['edition']))
            pair.append(record)
        changes=review.metadata.compare(*pair)
        need(len(changes)==31884 and [len(a['rows']) for a in pair]==[42149,42149],'original RDR changed')
        actual=[]
        for label in ('buggy-unchanged1','buggy-unchanged2','repaired-unchanged1','repaired-unchanged2'):
            a=qualification.typed_rows(signed/'modern'/label,True)
            need(len(a)==cfg['unit_count'] and all(r['fresh']for r in a),'wrong real idle')
        for phase,state in [('old','buggy'),('edited','fixed')]:
            bounds=read(signed/'ruf009/build'/phase/'result.json')['behavior']
            for key,decorator,expr,bad,good in qualification.PROBES:
                v=bounds[key];expected=good if state=='fixed'else bad
                need(v['returncode']==expected and [d['code']for d in v['diagnostics']]==['RUF009']*expected,'wrong original real RUF009 case')
                if expected:need(v['diagnostics'][0]['location']=={'row':4,'column':24} and v['diagnostics'][0]['end_location']=={'row':4,'column':24+len(expr)},'wrong real underline')
                actual.append([phase,key,expected])
        rows=[]
        for i,order in enumerate(review.REG['confirm_orders'],1):
            rows.append({'worker':{'block':i,'boot':str(i),'job':i,'phase':'confirmation','order':order,'recipe':'selftest','sha':'test','run':1,'factory':{}},'roles':{'P':{'cost':{'edited':1000+i}},'C':{'cost':{'edited':800+i}}},'reduction':1-(800+i)/(1000+i),'eligible_shape':True})
        stats=review.aggregate(rows)
        need(stats['admit'] and stats['one_sided_sign_p']==1/256 and stats['randomization_p']==1/70,'positive allocation math')
        tie=copy.deepcopy(rows)
        for k in tie:k['roles']['C']['cost']['edited']=k['roles']['P']['cost']['edited'];k['reduction']=0
        q0=review.aggregate(tie);need(not q0['admit'] and q0['one_sided_sign_p']==q0['randomization_p']==1,'tie falsely accepted')
        tie[1]['worker']['boot']=tie[0]['worker']['boot'];rejects(lambda:review.aggregate(tie))
        import artifacts
        raw=temp/'transport.zip'
        def transport(name):
            with zipfile.ZipFile(raw,'w') as archive:archive.writestr(name,b'original')
            return {'id':13,'name':'test','workflow_run':{'id':12},'expired':False,'size_in_bytes':raw.stat().st_size,'digest':'sha256:'+case.sha(raw)}
        a=transport('phase/physical')
        artifacts.gh=lambda _:['/bin/cat',str(raw)]
        artifacts.api=lambda _:{'total_count':1,'artifacts':[a]}
        def pull(name):
            location=temp/name;location.mkdir()
            return artifacts.download(12,'test',location)[0]
        need((pull('good')/'phase/physical').read_bytes()==b'original','actual ZIP readback')
        a['digest']='sha256:'+'0'*64;rejects(lambda:pull('wrong-sha'))
        a=transport('../outside');rejects(lambda:pull('bad-member'))
        print(json.dumps({'source_transitions':6,'original_source_bytes':[case.PORT['buggy'],case.PORT['fixed']],'signed_raw':[v['header'] for v in pair],
                          'signed_published_rows':[len(v['rows'])for v in pair],'different_rows':len(changes),'inspected_native_probes':actual,'authentic_settled_rosters':4,
                          'reader_refusals':['wrong source body','untracked source','wrong metadata crate','wrong metadata edition','modified metadata magic','duplicate boot','wrong ZIP checksum','traversing ZIP member'],
                          'counter_tests_synthetic':{'min_sign_p':stats['one_sided_sign_p'],'min_balanced_p':stats['randomization_p'],'all_ties':q0['one_sided_sign_p']},
                          'note':'previous signed histories and synthetic mathematical checks only; no candidate or scored observations'},sort_keys=True,indent=1))
if __name__=='__main__':main(*(Path(x).resolve(strict=True)for x in sys.argv[1:]))
