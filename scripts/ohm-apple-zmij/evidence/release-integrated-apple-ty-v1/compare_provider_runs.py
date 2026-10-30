"""Compare the independent observations on two Apple hosts. Keep native work differences visible."""
from pathlib import Path
import argparse,gzip,hashlib,json
READ=lambda fn:json.loads(gzip.decompress(fn.read_bytes()) if fn.suffix=='.gz' else fn.read_bytes())
def summary(folder, archive):
    m=READ(folder/'matrix.json');q=READ(folder/'provider-rows.json.gz')
    mig=READ(folder/'migration-rows.json.gz');old=READ(folder/'legacy.json.gz')
    rows={}
    def program(key,d):
        assert key not in rows
        rows[key]={'semantic':[d['status'],d['answer']],'native':{'full':sorted(d['full']),'link_only':len(d['link_only']) if isinstance(d['link_only'],list) else d['link_only'],'ld':d['ld']}}
    def symbols(key,d):
        assert key not in rows
        from zipfile import ZipFile
        category,*parts=key.split('/')
        prefix={'registry':'versioned/registry','literal-v1':'versioned/legacy-named','literal-v2':'versioned/named'}[category]
        if category=='registry': obs=archive.read(prefix+'/'+'/'.join(parts)+'/verified.json'); program=json.loads(obs)['observation']; assert program=='1.234 cbf43926\n'
        else:
            obs=archive.read(prefix+'/'+'/'.join(parts)+'/verified.json');record=json.loads(obs);assert record['exit']==0 and record['stdout']=='17\n';program=record['stdout']
        rows[key]={'semantic':program,'observed_linker_output_path_sha256':d['output'],'native':{'full':sorted(d['actual_full']),'link_only':len(d['link_only']) if isinstance(d['link_only'],list) else d['link_only'],'ld':d['stock_linkers'],'program_links':d['reader_links']}}
    for role,qs in q.items():
        for visit,phase in qs.items():
            for arm in ('warm','empty'):
                program(f'v2/{role}/{visit}/{arm}',phase[arm])
    for case,phases in mig.items():
        for step,phase in phases.items():
            for arm in ('warm','reference'):
                program(f'move/{case}/{step}/{arm}',phase[arm])
    for name,group in [('v1',old['named']),('v2',READ(folder/'named.json'))]:
        for role,cases in group.items():
            for case,phases in cases.items():
                for stage,phase in phases.items():symbols(f'literal-{name}/{role}/{case}/{stage}',phase)
    for role,cases in old['native'].items():
        for case,phases in cases.items():
            for stage,phase in phases.items():
                for arm in ('warm','empty'):program(f'v1/{role}/{case}/{stage}/{arm}',phase[arm])
    for role,stages in READ(folder/'registry.json').items():
        for stage,phase in stages.items():
            key=f'registry/{role}/{stage}';symbols(key,phase)
            rows[key]['native']['real_producers']={c:q['physical'] for c,q in phase['producer'].items()}
    assert len(rows)==1596
    return m['subjects'],rows

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('old',type=Path);parser.add_argument('new',type=Path);parser.add_argument('out',type=Path)
    parser.add_argument('old_zip',type=Path);parser.add_argument('new_zip',type=Path)
    from zipfile import ZipFile
    a=parser.parse_args()
    with ZipFile(a.old_zip) as before,ZipFile(a.new_zip) as after:
        parent,b=summary(a.old,before);child,c=summary(a.new,after)
    assert b.keys()==c.keys()
    assert parent['signed_archive']==child['signed_archive'] and parent['stock_ld']==child['stock_ld']
    for r in 'CP':assert [parent['rust'][r][k] for k in ('source','tree','compiler_tree','members','std')]==[child['rust'][r][k] for k in ('source','tree','compiler_tree','members','std')]
    for r in ('classic','signed','aware'):
        assert parent['cargo'][r]['source']==child['cargo'][r]['source']
        if r!='classic':assert parent['cargo'][r]['sha']==child['cargo'][r]['sha']
    def changes(where):return {k:{'first':b[k][where],'repeat':c[k][where]} for k in b if b[k][where]!=c[k][where]}
    out={'observations':len(c),'semantic_differences':changes('semantic'),'native_work_differences':changes('native'),'relocated_standalone_linker_output_paths':[k for k in b if b[k].get('observed_linker_output_path_sha256')!=c[k].get('observed_linker_output_path_sha256')],
         'compiler_drivers':{r:[s['rust'][r]['driver'] for s in (parent,child)] for r in 'CP'},
         'cargo':{r:[s['cargo'][r]['sha'] for s in (parent,child)] for r in ('classic','signed','aware')}}
    payload=(json.dumps(out,sort_keys=True,indent=2)+'\n').encode()
    if a.out.exists():assert a.out.read_bytes()==payload
    else:a.out.write_bytes(payload)
    print('Compared',len(c),'commands;',len(out['semantic_differences']),'verdict differences;',len(out['native_work_differences']),'native work differences.',hashlib.sha256(payload).hexdigest())
if __name__=='__main__':main()
