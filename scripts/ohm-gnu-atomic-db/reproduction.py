"""Check the two registered runs independently, including distinct workers and inputs."""
import json
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import pairs


def main():
    evidence=HERE/'evidence'
    source=json.loads((evidence/'source-41141810291.json').read_text())
    roles=[('primary',41141112097,'7ce6296e7b007c0a7de32a91421831e1829874c5',None),
           ('replication',41143416626,'20cf3bd81dd7d30009ae75062eed9acf113f935a',41141810291)]
    output={};used={k:set() for k in ('id','runner_id','runner_name')}
    for name,run,head,source_run in roles:
        directory=evidence/(name+'-'+str(run))
        stats=pairs.offline(directory)
        manifest=json.loads((directory/'manifest.json').read_text())
        assert (manifest['run'],manifest['head'],manifest.get('source_run'))==(run,head,source_run)
        if source_run:assert (source['run'],source['head'])==(source_run,head)
        hosts=json.loads((directory/'workers.json').read_text())['workers']
        for key,previous in used.items():
            values={h[key] for h in hosts}
            assert len(values)==12 and not previous&values
            previous.update(values)
        coverage=[];images={'old':set(),'new':set()};objects=set();cpu=[]
        for n,record in enumerate(manifest['pairs'],1):
            rows=json.loads(subprocess.check_output(['zstd','-qdc',directory/record['file']]))
            doc=lambda path:json.loads(rows['atomic-measurements/'+path])
            cpu.append(doc('calibration/summary.json')['tree_cpu'])
            if source_run:
                origin=json.loads(rows['atomic-subjects/origin.json'])
                assert origin['run']==source_run and origin['head']==head
                assert {k:[v['id'],v['digest']] for k,v in origin['artifacts'].items()}=={
                    k:source['artifacts'][k] for k in ('gnu-atomic-source-parent-sdk','gnu-atomic-registered-compiler')}
            for role in 'PC':
                for phase in ('edit','repeat'):
                    c=doc(role+'/'+phase+'/clock.json')
                    assert pairs.valid_clock(c)
                    coverage.append(c['running']/c['enabled'])
                terminal=doc(role+'/terminal.json')
                for phase,g in [('old','old'),('empty','new'),('repeat','new'),('repair','new')]:
                    client=terminal['products'][phase]['consumer']
                    images[g].add((client['elf'],client['bytes']))
                arc=doc(role+'/repeat/archive-members.json')
                canonical=sorted((n,s,h) for n,_,s,h in arc['objects'])
                assert len(canonical)==216
                objects.add(pairs.digest(json.dumps(canonical,sort_keys=True).encode()))
        assert all(len(d)==1 for d in images.values()) and len(objects)==1 and len(coverage)==48
        output[name]={'run':run,'head':head,'source_qualification':source_run,
                      'jobs':len(hosts),'scheduled_hardware_coverage':[min(coverage),max(coverage)],
                      'qualified_tree_cpu_positions':sum(cpu),'source_appropriate_consumers':{k:list(next(iter(v))) for k,v in images.items()},
                      'fully_hashed_216_objects':next(iter(objects)),'results_sha256':pairs.digest((directory/'results.json').read_bytes()),
                      'whole_independent_median_and_interval':{
                          s:[stats[s]['instructions']['paired_median'],stats[s]['instructions']['ordered_median_interval_96_14']]
                          for s in ('repeat','edit','edit+repeat')}}
    assert all(len(v)==24 for v in used.values())
    assert output['primary']['source_appropriate_consumers']==output['replication']['source_appropriate_consumers']
    assert output['primary']['fully_hashed_216_objects']==output['replication']['fully_hashed_216_objects']
    pairs.write(evidence/'two-cohort-inventory.json',{'unique_hosted_runner_ids':24,'cohorts':output})
    print('Verified two separate 12-pair instruction estimates on 24 distinct registered runners.')


if __name__=='__main__':main()
