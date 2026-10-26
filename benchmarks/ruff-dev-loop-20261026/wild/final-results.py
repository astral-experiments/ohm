#!/usr/bin/env python3
"""Export paired measurements after checking independent native and process receipts."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys

FIELDS=['mode','block','position','edit','arm','units','executables','cargo','rustc','clang','wild','total','source_sha256','outputs_sha256']
ORACLES=['mode','phase','edit','arm','units','executables','dirty','outputs_sha256']
ENGINES={'cargo':'DynamoRIO','clang':'Cachegrind','ld.bfd':'Cachegrind','rustc':'Cachegrind'}

def read(p):return json.loads(p.read_bytes())
def digest(outputs):
    ids=sorted((key,row['sha256']) for key,row in outputs.items())
    return hashlib.sha256(json.dumps(ids,separators=(',',':')).encode()).hexdigest()

def reports(directory,arm):
    record=read(directory/'processes.json');counts=record['counts'];images=record['images']
    assert record['engines']==ENGINES and set(counts)==set(images)==set(ENGINES)
    assert len({x['pid'] for x in images.values()})==4
    driver=Path(record['selected_driver']);assert driver.parent.name==arm
    cargo=images['cargo'];pid=str(cargo['pid']);f=directory/f'cargo.{pid}.ir'
    lines=[x.split() for x in f.read_text().splitlines()]
    assert lines[0]==['B',pid,'0','0'] and lines[-1]==['P',pid,'0','0']
    ts=[x[2] for x in lines if x[0]=='T'];fs=[x[2] for x in lines if x[0]=='F']
    assert sorted(ts)==sorted(fs) and len(ts)==len(set(ts))==cargo['threads']
    assert counts['cargo']==sum(int(x[3]) for x in lines if x[0]=='F')
    for name in ('rustc','clang','ld.bfd'):
        pid=images[name]['pid'];p=directory/f'guest.{pid}';log=(directory/f'vg.{pid}').read_text()
        assert log.count(' I refs:')==1 and not 'Process terminating' in log
        with p.open() as fd:
            for line in fd:
                if line.startswith('cmd: '):assert Path(line[5:].split()[0]).resolve()==Path(images[name]['image'])
                if line.startswith('summary: '):assert int(line.split()[1])==counts[name];break
            else:raise ValueError(('missing counter',name))
        if name=='rustc':
            mapped={Path(x.split('Reading syms from ',1)[1].strip()) for x in log.splitlines()
                    if 'Reading syms from ' in x and x.rstrip().endswith('/'+driver.name)}
            assert {x.resolve() for x in mapped}=={driver.resolve()}
    arg,=directory.glob('all-rustc.*.argv');assert hashlib.sha256(arg.read_bytes()).hexdigest()==record['one_rustc_argv_sha256']
    return record

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ['plan','build','test','output','analysis']:ap.add_argument(name,type=Path)
    args=ap.parse_args();locked=read(args.plan)
    assert hashlib.sha256(args.plan.read_bytes()).hexdigest()=='d27388648b45b0b12b54f02c82bbd2f9f98db8f1342d65a296f9f515f210cb43'
    raw=[];native=[];audits={};specimens={}
    for mode,source,unit,num,exes in [('build',args.build,'ruff',501,6),('test',args.test,'fixtures',619,102)]:
        assert read(source/'outcome.json')['status']=='native-oracles-match'
        assert read(source/'counter-audit.json')['status'].startswith('one complete DynamoRIO Cargo, three complete Cachegrind children')
        assert read(source/'plan.json')=={'seed':locked['seeds'][mode],'plan':locked['plans'][mode]}
        data=[json.loads(line) for line in (source/'observations.jsonl').read_text().splitlines()]
        assert len(data)==24 and len(locked['plans'][mode])==12
        ref={};audits[mode]={'snapshot':read(source/'snapshot.json'),'native_exec':read(source/'audit-native-traces.json'),
            'compiler_state':read(source/'compiler-identities.json'),'tools':read(source/'hybrid-tool-digests.json'),'probes':{}}
        for arm in ['parent','stack']:
            for edit in ['changed','original']:
                r=read(source/(arm+'-native-after-snapshot-'+edit)/'result.json');out=digest(r['outputs'])
                assert (len(r['graph']),len(r['outputs']),r['dirty'])==(num,exes,[unit]);oracle=read(source/('parent-'+edit)/'result.json')
                assert r['graph']==oracle['graph'] and out==digest(oracle['outputs']);ref[edit]=out
                native.append([mode,'independent native',edit,arm,num,exes,unit,out])
            probe=source/('clean-audit-'+arm+'-2');p=read(probe/'result.json');assert digest(p['outputs'])==ref['original'] and p['dirty']==[unit]
            audits[mode]['probes'][arm]=reports(probe,arm)
        for i,block in enumerate(locked['plans'][mode]):
            for pos,arm in enumerate(block['arms']):
                obs=data[2*i+pos];assert (obs['block'],obs['edit'],obs['arm'],obs['units'],obs['executables'])==(i,block['edit'],arm,num,exes)
                assert obs['outputs_sha256']==ref[block['edit']]
                d=source/f'{i:02d}-{pos}';r=read(d/'result.json');assert r['dirty']==[unit] and digest(r['outputs'])==ref[block['edit']]
                reset=read((source/(d.name+'-reset'))/'result.json');assert reset['dirty'] in [[],[unit]]
                other='original' if block['edit']=='changed' else 'changed';assert digest(reset['outputs'])==ref[other]
                proc=reports(d,arm);assert proc['counts']==obs['counts'];c=proc['counts'];assert sum(c.values())==obs['guest_ir']
                raw.append([mode,i,pos,block['edit'],arm,num,exes,c['cargo'],c['rustc'],c['clang'],c['ld.bfd'],obs['guest_ir'],obs['source_sha256'],obs['outputs_sha256']])
                specimens[f'{mode}-{i}-{pos}']=proc
    args.output.mkdir(exist_ok=True,parents=True)
    for name,headers,records in [('integrated.csv',FIELDS,raw),('integrated-native.csv',ORACLES,native)]:
        with (args.output/name).open('w',newline='') as f:
            w=csv.writer(f,lineterminator='\n');w.writerow(headers);w.writerows(records)
    (args.output/'integrated-audit.json').write_text(json.dumps({'cohort':'shared prebuilt baseline dependencies','audits':audits,'scored_processes':specimens},indent=2)+'\n')
    subprocess.run([sys.executable,args.analysis,args.output/'integrated.csv','parent','stack'],check=True)
if __name__=='__main__':main()
