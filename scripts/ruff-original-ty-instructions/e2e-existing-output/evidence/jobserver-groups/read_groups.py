"""Read every present signed/source operand before classifying this one-boot native diagnostic."""
from pathlib import Path
import base64,gzip,hashlib,json,os,re,stat,struct,sys,zipfile
sys.path.insert(0,str(Path(__file__).resolve().parent))
from read_relation import validated_container,differences
def sha(v):return hashlib.sha256(v).hexdigest()
def group_rows(raw):
    lines=raw.decode().splitlines()
    get=lambda typ:[x.split('\t')[1:]for x in lines if x.startswith(typ+'\t')]
    [(objects,scripts,stubs,lto,threads,per,new)]=get('TYPED');assert int(objects)>3500 and (scripts,stubs,lto,per)==('3','0','0','None')
    ev=lambda v:int(re.search(r'entsize:\s*(\d+)',v)[1])
    inputs=get('RO-INPUT');groups={int(i):ev(attr)for i,attr in get('RO-GROUP')};actual={}
    for group,count,file,section,attributes in inputs:
        group=int(group);assert int(count)>0 and file and section
        actual.setdefault(group,[]).append({'count':int(count),'file_or_member':file,'section':section,'entsize':ev(attributes),'actual_attrs':attributes})
    assert set(actual)==set(groups)
    for num,selections in actual.items():
        size={r['entsize']for r in selections};assert groups[num]==(next(iter(size))if len(size)==1 else 0)
    i=max(actual)
    return {'threads':int(threads),'contributing_groups':len(actual),'last_group_index':i,'last_group_size':groups[i],'last_group_inputs':actual[i],
            'sections_reduced':sum(r['count']for rs in actual.values()for r in rs)}
def read(p,archive_sha,head,run):
    P=Path(p)
    with P.open('rb')as f:assert hashlib.file_digest(f,'sha256').hexdigest()==archive_sha
    with zipfile.ZipFile(P)as z:
        assert z.testzip()is None and len(set(z.namelist()))==len(z.namelist())
        names=set(z.namelist())
        get=lambda n:json.loads(gzip.decompress(z.read(n))if n.endswith('.gz')else z.read(n))
        reg=get('registration.json');assert reg['run']==run and reg['head']==head and reg['never_reuse']and reg['source']=='e856d81f6683cad80b9fe0ebf1a0c3c403c6fe11'
        result={'registration':reg,'archive':{'bytes':P.stat().st_size,'sha256':archive_sha},'stages':{},'complete':'complete.json'in names}
        for stage in ('old','edit'):
            pre=stage+'-';pos=sorted(n for n in names if n.startswith(pre)and n.endswith('-role.json'));rows={}
            for name in pos:
                role=name[len(pre):-len('-role.json')];v=get(name);x=get(pre+role+'-elf.json.gz');hdr,_=validated_container(x)
                sec=next(s for s in x['sections']if s['section']=='.rodata');assert (v['sha256'],v['entsize'],v['rodata_bytes'])==(x['sha256'],sec['header'][9],sec['header'][5])
                if role.startswith('tokens-'):
                    assert v['mode']=='private' and v['source']=='stock'and not v['requested_diagnostic']
                    assert v['token_pre']==v['token_post']==v['controlled_threads']-1
                    if v['controlled_threads']>1:assert v['minimum_observed_tokens']==0
                if v['source']=='source':
                    native=group_rows(gzip.decompress(z.read(pre+role+'-native.tsv.gz')));assert native['last_group_size']==v['entsize']and native['threads']==v['controlled_threads']
                    v['reopened_source_groups']=native
                rows[role]={'artifact':x,'values':v}
            if not rows:continue
            info={'present_roles':sorted(rows),'pipe_controls':{},'source_inputs':{}}
            a=rows.get('tokens-0-1',{}).get('artifact')
            if a is not None:
                for role,r in rows.items():
                    comp=differences(a,r['artifact']);v=r['values'];a0=r['artifact'];source=v.get('reopened_source_groups')
                    if source:info['source_inputs'][role]=source
                    info['pipe_controls'][role]={**{k:v[k]for k in ('sha256','source','mode','token_pre','token_post','minimum_observed_tokens','controlled_threads','requested_diagnostic','entsize','rodata_bytes','libelf','signed_trace_token_count','argv_sha256')},'delta_vs_one':{'sha256':comp['whole'],'sections':comp['different_section_payloads'],'headers':comp['headers'],'complement':comp['outside_section_byte_changes']}}
                    if 'elfutils_strip'in v:info['pipe_controls'][role]['system_elfutils']=v['elfutils_strip']
                    if not comp['full_equal']:
                        assert comp['different_section_payloads']==['.note.gnu.build-id']and len(comp['outside_section_byte_changes'])==1
                        assert len(comp['headers'])==1 and comp['headers'][0][:2]==['.rodata','sh_entsize']
                        offset=hdr[6]+64*next(x['index']for x in a0['sections']if x['section']=='.rodata')+56
                        assert comp['outside_section_byte_changes'][0][0]==offset
            complete=pre+'complete.json.gz'
            if complete in names:
                r=get(complete);f=get(pre+'ordinary-elf.json.gz');validated_container(f)
                raw=gzip.decompress(z.read(stage+'/'+('native-'+r['actor_file']+'.gz')));main=group_rows(raw)
                assert main['threads']==r['primary_threads']and main['last_group_size']==next(x['header'][9]for x in f['sections']if x['section']=='.rodata')
                assert f['sha256']==r['ordinary_sha256']==next(x['values']['sha256']for x in rows.values()if x['values']['controlled_threads']==main['threads']and x['values']['source']=='stock')
                proof=get(stage+'/inventory.json.gz');assert len(proof['executables'])==102 and proof['executables'][proof['binary']]['elf']['sha256']==f['sha256']
                values=[rows['tokens-'+str(i)+'-'+str(n)]['values']for i,n in enumerate((1,2,2,1))]
                assert len({v['argv_sha256']for v in values})==1 and values[0]['sha256']==values[3]['sha256']!=values[1]['sha256']==values[2]['sha256']
                n=get(pre+'409-live-inputs.json.gz');assert len(n)==409 and len({x[0]for x in n})==409
                info.update({'complete':True,'complete_native_inputs':len(n),'native_bytes':sum(x[1][3]for x in n),'actual_cargo_source':proof['state'],'actual_cargo_elf':f['sha256'],'actual_cargo_groups':main,'actual_pipe':get(pre+'physical-original-descriptors.json')})
                # Avoid repeating 446 full arguments once per source state in the compact readback.
                info['actual_pipe']['argv_digest']=sha(b'\0'.join(os.fsencode(arg)for arg in info['actual_pipe'].pop('argv')))
            result['stages'][stage]=info
        return result
if __name__=='__main__':print(json.dumps(read(*sys.argv[1:]),sort_keys=True,indent=2))
