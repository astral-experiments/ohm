"""Independently verify one native archive and all its guest profiles, or aggregate every block."""
from pathlib import Path
from itertools import permutations
from math import comb
from statistics import median
import gzip, hashlib, json, re, runpy, sys

HERE=Path(__file__).resolve().parent
subject=runpy.run_path(str(HERE/"reopen-compact-ruff.py"))
Study=subject["Study"]
NATIVE=runpy.run_path(str(HERE/"complete-native-roster.py"))["inspect"]
H=lambda b: hashlib.sha256(b).hexdigest()
source={"A":"444c0273a2e2bc0b161e988d43c882349bc2d7a6","N":subject["BEFORE"],"M":subject["AFTER"]}
drivers={"A":"a1f1eb603214c354827aa24c7176aaa4c349b2cc741526e6e2e87af46105929b","N":"a51424740c111a4cfdfc67b39bf498907eb396b4b1f0800c27c4fcafc9e6eb72","M":"2a232a6c250f30b7c8214be0bbba21ef125f514da3dfd720291c377909d14545"}
hard={"A":{"zmij","compact_str","ruff_python_ast"},"N":{"compact_str","ruff_python_ast"},"M":set()}
schedule=json.loads((HERE/"schedule.json").read_bytes())

def canonical(args):
    assert len(args)==171
    selected=args[args.index("--out-dir")+1]
    (tag,)=re.findall(r"/(v2-[0-9a-f]{16})/",selected)
    result=[];offsets=[]
    for i,arg in enumerate(args):
        if tag in arg:
            assert args[i-1] in ("--out-dir","--extern","-L") and arg.count("/"+tag+"/")==1
            arg=arg.replace("/"+tag+"/","/<compiler-namespace>/");offsets.append(i)
        result.append(arg)
    assert len(offsets)==42
    return result, offsets, tag

def file_sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def calibrate(a):
    expected=a.J('counter-calibrated.json')
    assert expected['source']=='5dadb883fab0adc6f91f23e126634a08a6df2ad354e58c0f58a24759e8b229a1'
    assert expected['valgrind']=='def5fdcf6ae64a4d3e6af3786b622978d8313e0734ecf3f6cbe71d8be9e274c8'
    table={}
    for n in ('ordinary','no-child','parent-thread','child-only','repeat'):
        base='cal-'+n
        observed=a.J(base+'/observed.json')['processes']
        assert set(observed)==({'parent'} if n=='no-child' else {'parent','child'})
        table[n]={}
        for k,row in observed.items():
            pid=row['pid'];raw=gzip.decompress(a.get(f'{base}/profiles/cg.{pid}.gz'));log=a.get(f'{base}/profiles/log.{pid}')
            assert H(raw)==row['profile'] and H(log)==row['log']
            count=subject['lib']['recount'](raw,log,pid,row['argv'])
            assert count==row['Ir'];table[n][k]=count
    assert table==expected['subjects']
    for name,focus in (('parent-thread','parent'),('child-only','child')):
        assert table[name][focus]-table['ordinary'][focus]>3000000
        alternate='child' if focus=='parent' else 'parent'
        assert abs(table[name][alternate]/table['ordinary'][alternate]-1)<.01
    assert all(abs(table['repeat'][k]/v-1)<.01 for k,v in table['ordinary'].items())
    return table

def reopen(path, number, git, remote_digest, order_file=None):
    assert file_sha(path)==remote_digest
    a=Study(path)
    try:
        transitions=runpy.run_path(str(HERE/"verify_transitions.py"))["verify"](a.z)
        calibration=calibrate(a)
        configuration=a.J('heldout-registration.json');terminal=a.J('terminal.json')
        assert a.get('qa-head').decode().strip()==configuration["QA"]==git
        assert terminal["heldout"] and terminal["block"]==configuration["block"]==number
        assert terminal["sources"]==configuration["source"]==source and configuration["drivers"]==drivers
        assert H(a.get('schedule.json'))==configuration['schedule']==file_sha(order_file or HERE/'schedule.json')
        assert configuration["order"]==terminal["order"]==schedule[number]
        rosters={};counts={};shards={};reference_argv=None;reports={};sdk={}
        for role in configuration["order"]:
            prefix="block-"+number+"-"+role
            cycle=prefix+'-edit-cycle'
            owner=a.J('subject-'+role+'.json');assert owner['source']==source[role] and len(owner['files'])==119
            (driver_name,)= [n for n in owner['files'] if n.startswith('lib/librustc_driver')]
            assert owner['files'][driver_name][0]==drivers[role]
            sdk[role]={n:v for n,v in owner['files'].items() if n!=driver_name}
            complete=terminal['values'][role]
            assert H(a.get(prefix+'/complete.json'))==complete['native_terminal']
            assert H(a.get(cycle+'/complete.json'))==complete['cycle_terminal']
            rosters[role]={}
            for root,phases in ((prefix,subject['lib']['PHASES']),(cycle,('old-empty','post-settled'))):
                for phase in phases:
                    group=root+'/' +phase
                    check=a.native(root,phase,'invalid' if phase=='invalid' else 'old' if phase=='old-empty' else 'edited')
                    rows=a.J(group+'/native.json')
                    direct=NATIVE(a.z,group,rows)
                    rosters[role][group[len(prefix):]]={'exit':check['code'],'physical':direct,'typed':check['typed'],'rustc':check['rustc'],
                               'native_record_sha':H(a.get(group+'/native.json')),'full_archive':check.get('raw_archive'),'reader':check.get('reader')}
                    if root==prefix and phase in ('edit','unchanged-1','unchanged-2'):
                        assert check['links']==check['probes']==0 and set(direct)<= {'cargo','rustcs','rustup-dispatch'}
                        assert set(check['rustc'])==(hard[role] | ({'ruff_python_ast'} if phase=='edit' else set()))
                        assert all(check['markers'][c]==[c in hard[role],c not in hard[role]] for c in ('ruff_python_ast','zmij','compact_str'))
                        if phase=='edit':
                            args=next(r['argv'] for r in rows['rustcs'] if r['crate']=='ruff_python_ast')
                            normalized,positions,shards[role]=canonical(args)
                            if reference_argv is None: reference_argv=(normalized,positions)
                            assert reference_argv==(normalized,positions)
            samples={'settled':a.count(prefix+'/counter/whole',prefix+'/counter',prefix+'/unchanged-1',True)}
            for name,phase in (('first-real-edit','edit'),('immediate-repeat','unchanged-1')):
                samples[name]=a.count(cycle+'/'+name,cycle+'/'+name,prefix+'/'+phase,False)
            assert all(sum(samples[k].values())==complete[k] for k in samples)
            counts[role]=samples
            reports[role]={k:H(a.get(p)) for k,p in [('ordinary',prefix+'/complete.json'),('cycle',cycle+'/complete.json')]}
        assert shards==transitions['namespaces']
        initial=a.J('all-named-start-identities.json')
        selects=a.J('physical-selections.json')
        assert H(a.get('physical-selections.json'))==terminal['all_selections']
        order='A'+transitions['order']+''.join(k*2 for k in schedule[number])
        assert ''.join(v['to'] for v in selects)==order
        snapshots=[]
        for i,v in enumerate(selects):
            role=order[i];name=f'physical-selections/{i:02d}-{role}.json'
            assert v['snapshot']==name and v['sha256']==H(a.get(name))
            stream=a.J(name)
            assert stream['files']==initial[role] and {k:d for k,d in stream.items() if k!='files'}=={k:d for k,d in v.items() if k not in ('snapshot','sha256')}
            assert stream['from']==(None if i==0 else order[i-1])
            snapshots.append({'role':role,'from':stream['from'],'snapshot_sha256':H(a.get(name))})
        assert len(set(shards.values()))==3 and sdk['A']==sdk['N']==sdk['M']
        assert len(a.elf)==2 and all(len(s)==95 for s in a.native_refs.values()) and set(a.native_refs)=={'old','edited'}
        return {'block':number,'order':schedule[number],'git':git,'source':source,'drivers':drivers,'boot':configuration['boot_digest'],'cpu':configuration['cpu'],
                'calibrated_controls':calibration,'physical_args':{'namespace_by_role':shards,'namespace_only_fields':len(reference_argv[1]),'total_argv':len(reference_argv[0])},
                'native':rosters,'all_real_selector_transitions':transitions,'all_native_and_counted_role_selections':snapshots,'whole_guest_Ir_by_process':counts,'same_source_complete_reader':a.elf,
                'ordered_objects_sha256':{k:H(json.dumps(v,separators=(',',':')).encode()) for k,v in a.native_refs.items()},
                'raw_archive':remote_digest,'original_terminal':H(a.get('terminal.json')),'source_specific_completions':reports}
    finally:a.z.close()

def analyze(rows):
    assert len(rows)==12
    seq={r['block']:r for r in rows}
    assert set(seq)==set(schedule) and all(seq[b]['order']==v for b,v in schedule.items())
    assert all(list(schedule.values()).count(''.join(p))==2 for p in permutations('ANM'))
    for key in ('git','source','drivers','same_source_complete_reader','ordered_objects_sha256'):
        assert all(r[key]==rows[0][key] for r in rows)
    groups={}
    for parent in ('N','A'):
        for phase in ('first-real-edit','combined','settled'):
            data=[]
            for number,r in sorted(seq.items()):
                def total(k):
                    values={p:sum(c.values()) for p,c in r['whole_guest_Ir_by_process'][k].items()}
                    return values['first-real-edit']+values['immediate-repeat'] if phase=='combined' else values[phase]
                old,new=total(parent),total('M');assert old>0 and new>0
                data.append([number,old,new,old/new])
            ordered=sorted(x[3] for x in data);above=sum(x>2 for x in ordered)
            groups[parent+'/M:'+phase]={'chronological_blocks':data,'median':median(ordered),'range':[ordered[0],ordered[-1]],
                    'simultaneous_median_interval':[ordered[1],ordered[10]],'above_two':above,
                    'one_sided_sign_against_two':sum(comb(12,k) for k in range(above,13))/4096}
    return {'sources':source,'git':rows[0]['git'],'schedule':schedule,'distinct_boot_ids':len({r['boot'] for r in rows}),
            'raw_artifacts':{k:v['raw_archive'] for k,v in sorted(seq.items())},
            'six_endpoint_family_coverage_lower_bound':1-6*26/4096,'all_six_in_all_blocks_above_two':all(v['above_two']==12 for v in groups.values()),
            'full_ruff_guest_instruction_ratios':groups}

def dump(obj,path):
    out=(json.dumps(obj,sort_keys=True,indent=2)+'\n').encode()
    Path(path).open('xb').write(out);print(len(out),H(out))

if __name__=='__main__':
    args=sys.argv[1:]
    if args[0]=='block':
        path,number,git,checksum,out=args[1:];dump(reopen(Path(path),number,git,checksum),out)
    else:dump(analyze([json.loads(Path(p).read_bytes()) for p in args[2:]]),args[1])
