"""Independently check the original selected process and four fixed-input observations of a new live certificate."""
from pathlib import Path
from basis import CASE,HERE,canon,digest,filehash,read,readz
from live_metadata import missing
from fixed_input import RULE

def certificate(folder,role,state,want,forms,source_forms,warm,raw,oracle):
    bound=readz(folder/'live-input-bounds.json.gz');cert=readz(folder/'fixed-input.json.gz')
    assert bound['role']==cert['role']==role and bound['state']==cert['state']==state and bound['source']==cert['source']==CASE['states'][state]['source']
    assert cert['rule']==filehash(HERE/'fixed-layout-rule.json')and set(want)==set(bound['owners'])==set(cert['covered'])
    assert len(bytes.fromhex(bound['target_before_and_after']))==32 and len(bytes.fromhex(bound['source_mtimes_before_and_after']))==32 and len(bound['restored_original_inode'])==2
    for owner,classes in want.items():
        c=cert['covered'][owner];b=bound['owners'][owner];orig,=forms[owner];assert orig==c['checked_argv']and [orig]==source_forms[owner]
        assert b['wanted']==classes and b['forms']==digest(canon(orig))and b['real_baseline']==warm['workspace'][owner][1:]
        expect={orig[i+1].split('=',1)[1]for i,x in enumerate(orig[:-1])if x=='--extern'and '='in orig[i+1]}
        assert set(c['held_inputs'])==expect and c['held_inputs']==b['externs']==raw[owner]['externs']
        assert raw[owner]['held']==b['real_baseline']and c['coverage']==b['proof']and set(classes)<=set(c['coverage'])<=set(RULE['known_prior_physical_kinds'][owner])
        assert [r['threads']for r in c['rows']]==RULE['sequence']and len({tuple(r['result'])for r in c['rows']})>=2
        found=set()
        for i,row in enumerate(c['rows']):
            visits=folder/(owner+'-'+str(i));vals=[readz(p)if p.suffix=='.gz'else read(p)for p in (visits/'argv').glob('*.json*')];selected,=[x for x in vals if x['name']==owner]
            assert read(visits/'live-api.json')==oracle and oracle['baseline']['accepted'] and oracle['VariantPreferences']['accepted']==(state in 'BC')and oracle['SupportedVariantProperties']['accepted']==(state=='D')
            assert sorted(v['name']for v in vals if v is not selected)==sorted(row['other_unit_names'])
            def ordinary(argv):
                assert all(t in ('-Zthreads=1','-Zthreads=8')for t in argv if t.startswith('-Zthreads='))
                return [t for t in argv if not t.startswith('-Zthreads=')]
            for v in vals:
                if v is not selected:assert v['original']==v['executed']and any(ordinary(v['original'])==ordinary(f)for f in forms[v['name']])
            assert selected['original']==orig and selected['inputs']==c['held_inputs']and selected['executed']==orig+['-Zthreads='+str(row['threads'])]and row['argv']==digest(canon(selected['executed']))and row['inputs']==digest(canon(selected['inputs']))
            header=readz(visits/'actual-headers.json.gz');assert header['before']==header['after']and header['before_raw']==b['real_baseline']and header['after_raw']==row['result']
            assert digest(('\n'.join(header['before'])+'\n').encode())==c['original_native_header']and header['scope']['bootstrap']is None and header['scope']['role']==role and header['scope']['state']==state and header['scope']['owner']==owner and header['scope']['original_arglist_sha256']==b['forms']
            sem=row['semantic']
            if row['result']==b['real_baseline']:assert sem=={'exact_bytes':True}
            else:
                assert sem['warm']==b['real_baseline']and sem['cold']==row['result']and all(sem['checks'].values())and set(sem['physical_moved'])<=set(RULE['known_prior_physical_kinds'][owner]);found.update(sem['physical_moved'])
        assert sorted(found)==c['coverage']
    return {k:v['coverage']for k,v in cert['covered'].items()}

def replay(root):
    qual=read(root/'qualification/accepted.json');summary={}
    for i in range(1,9):
        for label,role in [('P',qual['control']),('T','F')]:
            arm=root/'pairs'/str(i)/label;fresh=root/'qualification'/('treatment'if label=='T'else('signed-1'if role=='R'else'corrected'))
            initial_forms=readz(arm/'cold-A/argv.json.gz')['forms']
            for state in 'BCD':
                d=arm/('native-'+state);old=fresh/('fresh-'+state);prior=old/'fixed/fixed-input.json.gz';cover={k:v['coverage']for k,v in readz(prior)['covered'].items()}if prior.is_file()else {}
                first=readz(d/'initial-native-guard/typed-warm-cold.json.gz');last=readz(d/'typed-warm-cold.json.gz');assert first['allowed_only_from_actual_certificates']==cover
                want=missing(first,cover);assert last['accepted']and not last['unresolved']and not last['changed_sidecars']and not last['ctfe_terminal_only']
                if not want:assert first==last and not(d/'new-history-fixed').exists();continue
                raw=readz(d/'live-raw-request.json.gz');warm=readz(d/'products.json.gz');cold=readz(old/'products.json.gz');forms=initial_forms|readz(d/'argv.json.gz')['forms'];co=certificate(d/'new-history-fixed',role,state,want,forms,readz(old/'argv.json.gz')['forms'],warm,raw,read(d/'live-api.json'))
                assert last['allowed_only_from_actual_certificates']==(cover|co)and raw.keys()==want.keys()and all(raw[n]['cold']==cold['workspace'][n][1:]and raw[n]['held']==first['changes'][n]['warm']and raw[n]['cold']==first['changes'][n]['cold']for n in want)
                assert last['changes'].keys()==first['changes'].keys()
                for k,v in last['changes'].items():assert v['all_semantic_guards_passed']and all(v[t]==first['changes'][k][t]for t in ('warm','cold','typed','root_sha256'))
                summary[f'{i}/{label}/{state}']=co
    return summary
