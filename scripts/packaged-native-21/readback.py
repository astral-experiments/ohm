"""Replay build and executable verdicts from raw bytes, either from a receipts directory or ZIP."""
from __future__ import annotations
import gzip,io,json,os,re,subprocess,sys,tempfile,unittest,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from fixture import CASES,PARITY,STATES,allocated_sections,cargo_messages,digest,form,native_state
from packages import ASSETS,CARGO,HEAD,RUN,need
from probe import expected

class Corpus:
    def __init__(self,p):
        self.p=p;self.z=zipfile.ZipFile(p) if not isinstance(p,Path) or p.is_file() else None
        self.names={n.filename for n in self.z.infolist() if not n.is_dir()} if self.z else {str(n.relative_to(p)) for n in p.rglob('*') if n.is_file()}
        need(not self.z or len(self.names)==len([n for n in self.z.infolist() if not n.is_dir()]),'duplicate ZIP paths')
    def get(self,k):need(k in self.names and '..' not in Path(k).parts and not k.startswith('/'),'foreign receipt');return self.z.read(k) if self.z else (self.p/k).read_bytes()
    def json(self,k):return json.loads(self.get(k))
    def raw(self,k):return gzip.decompress(self.get(k))

def parse(c,base,selected,caches):
    q=c.json(base+'/observed.json');a=c.raw(base+'/cargo-stdout.gz');b=c.raw(base+'/cargo-stderr.gz');need(digest(a)==q['stdout'] and digest(b)==q['stderr'],'raw Cargo streams differ');rows,build_text=cargo_messages(a);need(build_text==q['decoded_verbose_build_outputs'],'wrong verbose build-script text');need(rows[-1]=={'reason':'build-finished','success':q['exit']==0},'raw typed Cargo final result differs');art=[r for r in rows if r['reason']=='compiler-artifact'];need(q['units']==[[e['target']['name'],e['target']['kind'],e['fresh']] for e in art],'incorrect typed artifact inventory');main=[r for r in art if r['target']['name']==selected and r['executable']];need('-vv' in q['argv'] and q['argv'][:2]==['cargo','+ohm'] and '--offline' in q['argv'] and '--locked' in q['argv'] and ('--no-run' in q['argv'])==(selected=='qa_release_test'),'wrong Cargo entrypoint');
    markers=[]
    for path,h,hard,recheck in q['dep_info']:
        d=c.raw('dep-info/'+h+'.gz');need(digest(d)==h and (b'ohm-untracked-relink-inputs' in d)==hard and (b'/dev/null/ohm-recheck-dependent-links' in d)==recheck,'wrong raw dep-info markers');markers.append([hard,recheck]);
    codes=[r['message']['code']['code'] for r in rows if r['reason']=='compiler-message' and r['message'].get('code')];need(codes==q['codes'],'diagnostic changed');logs=b.decode(errors='replace')+'\n'+'\n'.join(r['message'].get('rendered','') or r['message']['message'] for r in rows if r['reason']=='compiler-message');need('internal compiler error' not in logs.lower() and 'panicked at' not in logs.lower(),'raw Cargo contained a panic');
    if q['exit']==0:
        unit,=main;p=q['product'];need(unit['executable']==p['path'],'wrong returned path');h=p['sha256'];
        if h not in caches:
            data=c.raw('executables/'+h+'.gz');need(digest(data)==h and len(data)==p['bytes'],'wrong physical returned binary');caches[h]=allocated_sections(data)
        need(caches[h]==p['sections'],'physical sections differ');out=c.raw(base+'/program-stdout.gz');err=c.raw(base+'/program-stderr.gz');need(p['program_exit']==0 and not err and digest(err)==p['stderr'] and digest(out)==p['stdout'] and len(re.findall(rb'QA_RESULT=(\d+) (\d+)',out))==1,'wrong actual program streams');found,=re.findall(rb'QA_RESULT=(\d+) (\d+)',out);val=list(map(int,found));need(selected!='qa_release_test' or b'1 passed; 0 failed; 0 ignored' in out,'libtest did not execute its sole named native test');typ='ok'
    else:
        need(q['exit']==101 and not main and q['product'] is None,'unsuccessful build returned native executable');val=None
        typ='rust-error' if 'E0425' in codes and 'qa_missing_declared_symbol' in logs else 'native-error' if 'qa_release_boundary' in logs and any(k in logs.lower() for k in ('linking with','linker','archive','library not found','could not find native static library')) else 'unexpected-failure'
    need(q['outcome']==typ and q['value']==val,'fabricated native verdict');return q

def verify(c,roles):
    all_results={};certs={};caches={};factory=c.json('factory/originals.json')
    for n in ('17','29'):
        a=c.get('factory/'+n+'.a');o=c.get('factory/'+n+'.o');need(digest(a)==factory['items'][n]['archive'] and digest(o)==factory['items'][n]['object'] and a.startswith(b'!<arch>\n') and o in a,'real C library source bytes did not survive ar')
    for role in roles:
        prefix=role+'/';cust=c.json(prefix+'custody.json');prov=cust['provenance'];triple=prov['target'];sdk=c.json(prefix+'sdk.json');installed=c.json(prefix+'installed.json');need(prov['sources']['cargo']['revision']==CARGO and CARGO in sdk['cargo'] and prov['sources']['rust']['revision'] in sdk['rustc'],'wrong packaged source');certs[role]=installed
        if role=='20':need(cust['archive_sha256']==ASSETS[triple][2] and cust['bytes']==ASSETS[triple][1] and cust['source']['release_id']==428741333,'baseline package differs')
        else:
            art=cust['source']['artifact'];need(cust['source']['head_sha']==prov['coordinator']['revision']==HEAD and cust['source']['run_id']==art['workflow_run']['id']==RUN and art['workflow_run']['head_sha']==HEAD and art['name']=='ohm-1.99.0-21-'+triple,'different private release artifact')
        env=c.json(prefix+'env.json');need(not({'CI','TF_BUILD','RUSTFLAGS','CARGO_INCREMENTAL','GH_TOKEN','GITHUB_TOKEN'}&env.keys()) and env['CARGO_NET_OFFLINE']=='true','different developer process');terminal=c.json(prefix+'terminal.json');seen={};totals={'declared_transitions':0,'declared_verdict_failures':[],'parity':{},'native_section_differences':[],'matching_native_images':0,'separately_reported_build_ids':0,'real_returns':0,'native_errors':0,'rust_errors':0,'cold_marker_forms':{}}
        for owner,watch in CASES:
            key=owner+'-'+watch;p=prefix+key;registered=STATES if watch in ('dir','file') else PARITY;scope='declared' if registered is STATES else 'parity';selected='qa_release_app' if owner=='direct' else 'qa_release_test';src=c.json(p+'/source.json');script=src['build.rs' if owner=='direct' else 'owned/build.rs'];need(('d.join("early")' in script)==(watch=='dir') and ('rerun-if-changed={}' in script)==(watch!='undeclared') and ('single/libqa_release_boundary.a' in script)==(watch in ('file','same-mtime')),'native declarations differ');results=c.json(p+'/result.json');need(results==terminal[key] and results['scope']==scope,'changed role terminal');old=None
            for (label,state,v),summary in zip(registered,results['rows'],strict=True):
                d=p+'/warm/'+label;e=p+'/empty/'+state+'-'+str(v);q=parse(c,d,selected,caches);ref=parse(c,e,selected,caches);need(all(n==0 for n in c.json(e+'/entry-count.json').values()),'not an independent empty reference');typ,val=expected(state,v);need(q['state']==ref['state']==state and q['rust']==ref['rust']==v and (ref['outcome'],ref['value'])==(typ,val),'bad independent reference');good=(q['outcome'],q['value'])==(typ,val);need(summary['verdict_matches']==good and summary['warm']==[q['outcome'],q['value']] and summary['empty']==[typ,val],'wrong warm vs clean verdict');
                if label=='cold':
                    old=q;need(not any(c.json(d+'/entry-count.json').values()) and q['incremental_rustcs'] and q['dep_info'] and q['declared_search'],'normal compiler or declared path absent');totals['cold_marker_forms'][key]=sorted({f'{int(h)}/{int(r)}' for _,_,h,r in q['dep_info']})
                if watch=='same-mtime' and label=='changed-native':
                    a=old['native']['single'];b=q['native']['single'];need(a['sha256']!=b['sha256'] and all(a[k]==b[k] for k in ('bytes','inode','mtime_ns','parent_mtime_ns')),'timestamp parity did not preserve inode, mtime and size')
                if q['product']:
                    totals['real_returns']+=1
                    if ref['product']:
                        x=q['product']['sections'];y=ref['product']['sections'];diff=sorted(k for k in x.keys()|y.keys() if x.get(k)!=y.get(k));need(diff==summary['different_sections'],'unreported native section difference');
                        if q['product']['sha256']==ref['product']['sha256']:totals['matching_native_images']+=1
                        if '.note.gnu.build-id' in diff:totals['separately_reported_build_ids']+=1
                        actual=[k for k in diff if k!='.note.gnu.build-id']
                        if actual:totals['native_section_differences'].append([key,label,actual])
                elif q['outcome']=='rust-error':totals['rust_errors']+=1
                elif q['outcome']=='native-error':totals['native_errors']+=1
                if scope=='declared':
                    totals['declared_transitions']+=1
                    if not good:totals['declared_verdict_failures'].append([key,label,summary['warm'],summary['empty']])
                else:totals['parity'].setdefault(key,{})[label]={'verdict':summary['warm'],'clean':summary['empty']}
            aa=parse(c,p+'/empty/independent-old',selected,caches);ref=parse(c,p+'/empty/lower-7',selected,caches);need(aa['value']==ref['value']==[17,7] and aa['outcome']==ref['outcome']=='ok','original source A/A failed');seen[key]=True
        need(len(seen)==6 and totals['declared_transitions']==48,'incomplete source matrix');all_results[role]=totals
    if set(roles)=={'20','21'}:
        a,b=all_results['20'],all_results['21'];all_results['comparison']={'same_physical_cargo_bytes':certs['20']['bin/cargo']==certs['21']['bin/cargo'],'parity_matches_baseline':a['parity']==b['parity'],'new_in_contract_issues':[v for v in b['declared_verdict_failures'] if v not in a['declared_verdict_failures']],'persisting_in_contract_issues':[v for v in b['declared_verdict_failures'] if v in a['declared_verdict_failures']]}
    return all_results

class Controls(unittest.TestCase):
    def test_verbose_cargo_framing(self):
        msg=b'{"reason":"build-finished","success":true}';line=b'[owned 0.0.1] cargo:rerun-if-changed=build.rs';r,b=cargo_messages(line+b'\n'+msg+b'\n');self.assertEqual((r,b),([{'reason':'build-finished','success':True}],['cargo:rerun-if-changed=build.rs']))
        for bad in (b'extra',b'[foreign 0.0.1] cargo:rerun-if-changed=build.rs',b'[owned 0.0.1] debug-text',b'[owned 0.0.1] cargo:rustc-link-arg=-x'):
            with self.assertRaises(RuntimeError):cargo_messages(bad+b'\n'+msg+b'\n')
    def test_independent_expected(self):
        self.assertEqual(expected('higher',11),('ok',[29,11]));self.assertEqual(expected('malformed',11),('native-error',None));self.assertEqual(expected('missing',None),('rust-error',None))
    def test_filename_owner_and_same_timestamp_control(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);sources={17:b'aa',29:b'bb'};s=form(root,'direct','same-mtime');a=native_state(s,'same-mtime','lower',sources);b=native_state(s,'same-mtime','higher',sources,preserve=True);self.assertNotEqual(a['single']['sha256'],b['single']['sha256']);self.assertEqual(a['single']['mtime_ns'],b['single']['mtime_ns']);self.assertEqual(a['single']['inode'],b['single']['inode'])
            with self.assertRaises(RuntimeError):native_state(s,'same-mtime','malformed',sources,preserve=True)
    def test_native_code_parser_rejects_truncated_or_foreign(self):
        for data in (b'foreign',b'\x7fELF'+bytes(80),bytes.fromhex('cffaedfe0c000001')+bytes(99)):
            with self.assertRaises((RuntimeError,ValueError,struct.error)):allocated_sections(data)

if __name__=='__main__':
    import struct
    if sys.argv[1:]==['--controls']:unittest.main(argv=[sys.argv[0]])
    else:
        c=Corpus(Path(sys.argv[1]));role=sys.argv[2];q=verify(c,['20','21'] if role=='both' else [role]);output=json.dumps(q,indent=2,sort_keys=True)+'\n';print(output,flush=True)
        if not c.z:
            with (c.p/('independent-'+role+'.json')).open('x') as f:f.write(output)
        if role=='both':need(not q['comparison']['new_in_contract_issues'],'new in-contract -21 mismatch against role-specific independent native references')
