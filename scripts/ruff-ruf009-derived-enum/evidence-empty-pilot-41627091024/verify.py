"""Reopen the recorded refusal, physical metadata and descriptive counters."""
import argparse,gzip,hashlib,json,subprocess,sys,tempfile,zipfile
from pathlib import Path
H=Path(__file__).resolve().parent
sys.path.insert(0,str(H.parent))
import external,metadata
def sha(raw):return hashlib.sha256(raw).hexdigest()
def read(p):return json.loads(p.read_bytes())
def diff(a,b):return [k for k in sorted(a.keys()|b.keys())if a.get(k)!=b.get(k)]

def main():
    raw=H/'original-records.zip'; manifest={n:(b,h)for n,b,h in read(H/'original-member-commitments.json')}
    for p in (H/'members').iterdir():assert manifest['members/'+p.name]==(p.stat().st_size,sha(p.read_bytes()))
    ordered={};products={};tables={};native={}
    with tempfile.TemporaryDirectory()as tmp,zipfile.ZipFile(raw)as z:
        tmp=Path(tmp);get=lambda n:json.loads(z.read(n));worker=get('worker.json')
        assert worker['run']==41627091024 and worker['order']=='CP' and worker['phase']=='pilot' and worker['sha']=='0c7d0e75a80252dac126704cbc05eaaae6129421'
        for n in z.namelist():
            b=z.read(n);assert manifest[n]==(len(b),sha(b))
        assert set(z.namelist())=={n for n in manifest if not n.startswith('members/')}
        decoded={}
        def table(r,s,name,ver):
            v=get(r+'/'+s+'/check.json')['metadata'][name];key=v['sha256']
            if key not in decoded:
                arc=H/'members'/(key+'.rmeta.zst');rows=H/'members'/(key+'.rows.json.gz')
                assert sha(arc.read_bytes())==v['archive']and sha(rows.read_bytes())==v['decoded']
                body=subprocess.check_output(['zstd','-qdc',arc]);assert len(body)==v['bytes'] and sha(body)==key
                value=metadata.table(body,name,ver,worker['source']['edition']);assert value==json.loads(gzip.decompress(rows.read_bytes()));decoded[key]=value
            return decoded[key]
        for r in 'PC':
            ordered[r]={};tables[r]={}
            version=get(r+'/kit.json')['rustc_version'].splitlines()[0]+' (Ohm metadata 3)'
            for s in ('ordinary-buggy-cold','ordinary-edited','ordinary-fixed-idle2','kernel-buggy-return','kernel-edited','kernel-fixed-idle2','empty-edit'):
                base=r+'/normal-external-inputs/';mark=get(base+s+'.json');work=tmp/(r+'-'+s);work.mkdir()
                for k in ('command.json','stdout','stderr'):(work/k).write_bytes(z.read(base+'expansion-'+s+'/'+k))
                observed=external.read_expansion(work);assert observed==mark['expansion']
                record,=[row for row in get(r+'/'+s+'/external-products.json')if row[3]==mark['file']]
                body=subprocess.check_output(['zstd','-qdc',H/'members'/(record[5]+'.external.zst')])
                assert record[5]==sha(body)==observed['macro'] and len(body)==record[4]
                ordered[r][s]=observed
            warm=ordered[r]['ordinary-edited'];empty=ordered[r]['empty-edit']
            assert all(v==warm for s,v in ordered[r].items()if s!='empty-edit')
            assert warm['macro']!=empty['macro'] and warm['stderr']!=empty['stderr'] and warm['errors'][0]!=empty['errors'][0]
            assert warm['expanded']==empty['expanded'] and warm['errors'][1:]==empty['errors'][1:]
            sets={}
            for s in ('ordinary-buggy-cold','ordinary-edited','kernel-edited','empty-edit'):
                rows=get(r+'/'+s+'/external-products.json')
                sets[s]={(x[0],x[1],tuple(x[2]),x[3]):x[5] for x in rows};assert len(rows)==len(sets[s])
            assert sets['ordinary-edited']==sets['kernel-edited']==sets['ordinary-buggy-cold']
            a,b=sets['ordinary-edited'],sets['empty-edit']
            products[r]={'observed':len(a),'changed':[[[k[0],k[1],list(k[2]),k[3]],a.get(k),b.get(k)]for k in diff(a,b)]}
            owners=sorted(get(r+'/ordinary-edited/check.json')['metadata'])
            for f,t in (('ordinary-buggy-cold','ordinary-edited'),('ordinary-edited','kernel-edited'),('ordinary-edited','empty-edit')):
                transition={}
                for name in owners:
                    first,last=[table(r,s,name,version)for s in (f,t)];different=diff(first['rows'],last['rows'])
                    transition[name]={'headers':[first['header'],last['header']],'row_counts':[len(first['rows']),len(last['rows'])],
                        'changed_rows':len(different),'first_changed_rows':[[k,first['rows'].get(k),last['rows'].get(k)]for k in different[:2]],
                        'changed_upstream':diff(first['requires'],last['requires'])}
                tables[r][f+'/'+t]=transition
            native[r]={}
            for s in ('native-buggy','native-edited','native-fixed-idle','native-reverse','native-repair','native-fully-empty-fixed'):
                item=get(r+'/'+s+'/native.json');native[r][s]=item['sha256'];assert len(item['probes'])==4 and manifest['members/'+item['sha256']+'.elf.zst'][1]==item['compressed']
            v=native[r];assert v['native-buggy']==v['native-reverse']and len({v[k] for k in v if k not in ('native-buggy','native-reverse')})==1
        target=tmp/'counters.json';subprocess.run([sys.executable,'-IB',H/'reopen-counter-records.py',raw,sha(raw.read_bytes()),target],check=True)
        perf=read(target);prior=read(H/'original-counter-readback.json')
        for k in ('zip_sha256','zip_bytes'):perf.pop(k);prior.pop(k)
        perf.pop('native_compressed_members_verified_against');assert perf==prior
        assert [len(perf['original_roles'][r]['traced']['kernel-edited']['roster']) for r in 'PC']==[7,2]
    return {'accepted':False,'confirmation_workers':0,'scored_pairs':0,'cause':'independently compiled macro and genuinely ordered diagnostic differ in both roles',
        'ordered':ordered,'external':products,'physical_metadata':tables,'native_sha256':native,'descriptive_instructions':perf['edited_instructions'],
        'descriptive_fraction':perf['edited_reduction_fraction'],'original':read(H/'original-counter-readback.json')['zip_sha256']}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();result=main()
    if (H/'verified.json').exists():assert result==read(H/'verified.json')
    a.out.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
