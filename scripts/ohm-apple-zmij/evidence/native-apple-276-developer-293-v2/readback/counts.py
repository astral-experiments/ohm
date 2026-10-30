"""Independent local arm counts and exact member identity, including two fresh empty builds."""
from collections import Counter
import gzip,hashlib,json,re
from pathlib import Path
from archive_differences import census as ar
from study import digest,need

def product(verb,row):
    if verb=="test":return {**row["product"],"debug_identity":row.get("test_debug")}
    keys={"value","sha256","archive_sha256","archive_metadata","archive_objects","macho_text"}
    return {k:v for k,v in row["reader"].items() if k in keys}

def match(verb,a,b):
    if verb=="build":return a==b
    return bool(a["debug_identity"] and b["debug_identity"]) and {k:v for k,v in a.items() if k!="raw"}=={k:v for k,v in b.items() if k!="raw"}

def census(z):
    names=set(z.namelist());outputs={};differences={};comparison=[]
    def load(n):return json.loads(z.read(n))
    def native(phase,role):
        rec=load(phase+'/verified.json');events=json.loads(gzip.decompress(z.read(phase+'/exec.json.gz')))
        cargo=[r for r in events if r['path'].endswith('/native/bin/cargo')]
        native=[r['argv'] for r in events if r['path'].endswith('/native/bin/rustc') and '--crate-name' in r['argv']]
        full=sorted(x[x.index('--crate-name')+1] for x in native if not any('link-only' in s for s in x) and any(y.startswith('--emit=') or y=='--emit' for y in x))
        # Cargo's Ohm real linker-driver may launch extra rustc --link-only with no
        # --crate-name. Reopen full original native counts as their specific invocation.
        allrust=[r for r in events if r['path'].endswith('/native/bin/rustc')]
        linkonly=[r for r in allrust if any('link-only' in s for s in r['argv'])]
        ld=[r for r in events if Path(r['path']).name in ('ld','ld-prime','ld-classic','ld64')]
        need(full==rec['native']['full'] and len(ld)==len(rec['native']['linkers']) and len(linkonly)==len(rec['native']['link_only']),phase+' independent native events differ')
        out={'full_compilers':len(full),'full_crates':full,'link_only_compilers':len(linkonly),'xcode_links':len(ld),'zmij_fresh':rec['fresh_zmij']}
        return rec,out
    cache={}
    def state(k):
        if k not in cache:
            data=gzip.decompress(z.read('ast-rlib/'+k+'.rlib.gz'));need(digest(data)==k,'registered full archive digest');cache[k]=data
        return cache[k]
    def compare(verb,base,a,b):
        u,v=[product(verb,x) for x in (a,b)]
        d={'arm':base,'own_or_across_clean':base.rsplit('/',1)[-1],'registered_equal':match(verb,u,v),'full_raw_exact':u==v,'differing_fields':[k for k in u if u[k]!=v[k]]}
        if verb=='build':
            uu,vv=u['archive_sha256'],v['archive_sha256']
            d['reader_raw_equal']=u['sha256']==v['sha256'];d['reader_code_equal']=u['macho_text']==v['macho_text'];d['typed_value_equal']=u['value']==v['value']
            if uu!=vv:
                key=uu+'/'+vv;d['archive_difference']=key
                if key not in differences:differences[key]=ar(state(uu),state(vv))
        comparison.append(d)
    for verb in ('build','test'):
        top='ast-'+verb+'-structural'
        if top+'/result.json' not in names:continue
        result=load(top+'/result.json');outside={}
        for i in (1,2):
            pair=f'{top}/pair-{i:02}';outside[i]={}
            for role in 'PC':
                d=f'{pair}/{role}'
                refs={}
                for s in ('old','new'):
                    label='clean-'+s if verb=='build' else 'clean';rec,count=native(f'{d}/empty-{s}/{label}',role);refs[s]=rec
                outside[i][role]=refs
                phase_totals={}
                for label in ('cold','edit','repeat-1','repeat-2','invalid','repair'):
                    rec,counts=native(d+'/actual/'+label,role);phase_totals[label]=counts
                    if label!='invalid':compare(verb,d+'/actual/'+label,rec,refs[rec['state']])
                outputs[f'{verb}/{i}/{role}']={'order':result['pairs'][i-1]['order'],'phases':phase_totals}
        for role in 'PC':
            for s in ('old','new'):compare(verb,verb+'/'+role+'/independent-empty-'+s,outside[1][role][s],outside[2][role][s])
    return {'counts':outputs,'complete_body_comparisons':comparison,'original_full_ar_member_changes':differences,'scores':0}
