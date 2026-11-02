"""Resolve genuine Cargo target paths through the full unit graph and the products of real processes."""
from collections import Counter
from pathlib import Path
import re,runpy
from basis import EVENTS,HERE,SIX,canon,digest,filehash,option,readz,writez
scope=HERE/'kit/unit-scope.py';assert filehash(scope)=='d9374e7c793da56fd2fa27f0fedf76a7cb40da82a1a2c9b3754ef3930ac03265'
U=runpy.run_path(str(scope))
def one(rows,why):
    assert len(rows)==1,(why,rows)
    return rows[0]
def resolved_extern_names(argv,source,target,raw):
    names={}
    for i,x in enumerate(argv[:-1]):
        if x!='--extern':continue
        alias,sep,value=argv[i+1].partition('=')
        assert sep and alias
        names.setdefault(alias,[]).append(Path(value))
    for alias,paths in names.items():
        if len(paths)==1:continue
        # The native build-mode compiler gets both link and metadata products
        # of the one dependency. These are not separate Cargo unit graph edges.
        assert len(paths)==2 and {p.suffix for p in paths}=={'.rlib','.rmeta'} and len({p.with_suffix('')for p in paths})==1,(source,alias,paths)
        for p in paths:
            row=raw['products'][str(p.relative_to(target))]
            assert row[0]>0 and len(bytes.fromhex(row[1]))==32
    return sorted(names)
def cargo_features(form,raw):
    if form['source']!=['registry','target-lexicon-0.13.5/src/lib.rs']:return form['features']
    # This exact upstream build script emits the synthetic feature directly
    # via cargo:rustc-cfg on rustc >=1.40. It is not a Cargo-resolved feature.
    assert form['features']==['rust_1_40']
    prod=one([n for n in raw['compilers']if n['source_file_sha256']=='678ba872ef2254e8901d6a00536f64d74d375d919f845113bd3ded709b6edb4a'],'target-lexicon 0.13.5 build.rs')
    build=Path(option(prod['argv'],'--out-dir'))/option(prod['argv'],'--crate-name')
    script=one([s for s in raw['build_scripts'].values()if s['exe']==str(build)and s['variables']['CARGO_PKG_NAME']=='target-lexicon'and s['variables']['CARGO_PKG_VERSION']=='0.13.5'],'actual target-lexicon 0.13.5 build-script invocation')
    source=one([x for x in prod['argv']if x.endswith('.rs')and not x.startswith('-')],'build.rs source')
    assert (Path(prod['cwd'])/source)==Path(script['variables']['CARGO_MANIFEST_DIR'])/'build.rs' and len(bytes.fromhex(script['binary_sha256']))==32
    return []
def prepare(folder):
    cold=folder/'cold-A';raw=readz(cold/'producer-evidence.json.gz');graph=readz(cold/'full-unit-graph.json.gz');ws=Path(raw['workspace']);reg=Path(raw['registry_src']);target=Path(raw['target'])
    g=U['structural'](graph,ws,reg);namespace,={U['registry_relative'](r['target']['src_path'],reg)[0]for r in graph['units']if r['pkg_id'].startswith(U['REGISTRY'])}
    assert len(raw['compilers'])==497 and len({n['pid']for n in raw['compilers']})==497
    dirs={};native={};unmatched=[];records={}
    for n in raw['compilers']:
        a=n['argv'];clean=list(a)
        if 'proc_macro'in clean:
            idx=clean.index('proc_macro');assert clean[idx-1]=='--extern'and option(a,'--crate-type')=='proc-macro';del clean[idx-1:idx+1]
        form=U['form'](clean,ws,reg,namespace)
        features=cargo_features(form,raw);externs=resolved_extern_names(clean,form['source'],target,raw)
        matches=[k for k in U['match_form'](g,form)if sorted(g['units'][k]['attributes']['features'])==features and U['extern_names'](g,k)==externs]
        out=Path(option(a,'--out-dir'));assert out.is_relative_to(target)and out not in dirs;dirs[out]=(n,form,matches)
        if len(matches)!=1:unmatched.append([n['pid'],form['name'],str(out),matches])
        else:
            key=matches[0];records.setdefault(key,[]).append({'pid':n['pid'],'unit':key,'directory':str(out),'command_sha256':digest(canon(a)),'entry_sha256':n['source_file_sha256'],'name':form['name'],'mode':form['mode'],'target':form['crate_types']})
    for pid,s in raw['build_scripts'].items():
        exe=Path(s['exe']);v=s['variables'];out=Path(v['OUT_DIR']);assert out.is_relative_to(target)
        if exe.parent not in dirs:continue
        n,form,opts=dirs[exe.parent]
        if not exe.name==form['name']or len(opts)!=1:continue
        key=opts[0];u=g['units'][key]['attributes']
        if u['target']['kind']!=['custom-build']:continue
        selected=[k for k,el in g['units'].items()if el['attributes']['mode']=='run-custom-build'and el['attributes']['pkg_id']==u['pkg_id']and el['attributes']['target']==u['target']and key in{x['unit']for x in el['dependencies']}]
        src=Path(n['cwd'])/one([z for z in n['argv']if z.endswith('.rs')and not z.startswith('-')],key)
        assert src.is_relative_to(Path(v['CARGO_MANIFEST_DIR']))and src.is_absolute()and v['CARGO_PKG_NAME'] and v['CARGO_PKG_VERSION'];native.setdefault(out,[]).append({'graph':selected,'compile':key,'compile_pid':n['pid'],'script_pid':int(pid),'executable':s['exe'],'executable_sha256':s['binary_sha256'],'variables':v})
    assert not unmatched and len(records)==len(dirs)==497 and all(len(x)==1 for x in records.values())
    executed=[one(one(rows,'one actual run script')['graph'],'one run-custom-build unit')for rows in native.values()]
    assert len(executed)==len(set(executed))==46 and set(g['units'])==set(records)|set(executed)and len(g['units'])==543
    # Verify both genuine link and metadata inputs carry the same producer
    # edge, including native code needed to compile procedural macros.
    for n,_,ids in dirs.values():
        uid,=ids;a=n['argv'];items={}
        for i,x in enumerate(a[:-1]):
            if x=='--extern'and '='in a[i+1]:
                alias,path=a[i+1].split('=',1);items.setdefault(alias,[]).append(Path(path))
        for alias,paths in items.items():
            if len(paths)<2:continue
            target_id,=dirs[paths[0].parent][2]
            assert [row['unit']for row in g['units'][uid]['dependencies']if row['extern_crate_name']==alias and row['unit']==target_id]==[target_id]
    return {'graph':g,'graph_sha':digest(canon(g)),'target':target,'dirs':dirs,'native':native,'products':raw['products'],'records':records,'unmatched':unmatched}
def project(case,folder,state):
    rec=readz(folder/('warm-'+state)/'argv.json.gz');assert sorted(rec['forms'])==SIX and len(rec['all_units'])==6 and not rec['all_other_rustcs']
    output={};terms=[];used=set();paths={};script_rows={};slot_map={};g=case['graph']
    pids={n:pid for n,pid,parent in rec['all_units']if parent==rec['root']};assert sorted(pids)==SIX
    live={};recorded=folder/('warm-'+state)/'products.json.gz';products=readz(recorded)['workspace']if recorded.is_file()else {}
    for n,arg in rec['forms'].items():
        target=Path(option(arg[0],'--out-dir'));raw,form,matches=case['dirs'][target];uid=one(matches,('actual new producing unit',n))
        product=rec['workspace_rmeta_from_argv'][n];assert Path(product).parent==target.relative_to(case['target'])
        evidence={'pid':pids[n],'argv_sha256':digest(canon(arg[0])),'produced_workspace_rmeta':product}
        if products:
            assert products[n][0]==product;evidence['bytes_sha256']=products[n][1:]
        live[uid]=evidence
    def supplier(out):
        assert out in case['dirs'],('missing actual compiler output directory',str(out))
        raw,form,matches=case['dirs'][out];key=one(matches,('ambiguous actual compiler',form['name'],str(out)));one(case['records'][key],key);used.add(key)
        return key,raw
    def slot(out,key):
        suffix=out.parent.name;assert re.fullmatch('[0-9a-f]{16}',suffix)and out.name=='out'and out.parents[2].name=='build'
        assert slot_map.setdefault(suffix,key)==key;paths[str(out)]=key;return suffix
    for name,rows in rec['forms'].items():
        a=one(rows,name);own=Path(option(a,'--out-dir'));key,actual=supplier(own);self_id=slot(own,key);assert option(actual['argv'],'--crate-name')==name
        proof=[]
        for i,x in enumerate(a):
            prev=a[i-1]if i else '';value=x
            if prev=='-C'and x.startswith('extra-filename='):
                assert x=='extra-filename=-'+self_id and x in actual['argv'];value=['own Cargo filename',key]
            elif prev=='-C'and x.startswith('metadata='):
                assert re.fullmatch('metadata=[0-9a-f]{16}',x)and x in actual['argv'];value=['own Cargo crate metadata',key]
            elif prev=='--out-dir':
                assert Path(x)==own;value=['own output directory',key]
            elif prev=='--extern':
                alias,separator,dst=x.partition('=');assert separator;path=Path(dst);origin,origin_argv=supplier(path.parent);sid=slot(path.parent,origin);kind=path.suffix
                ext_orig=g['units'][origin]['attributes']['target'];assert kind in('.rmeta','.so')and path.name=='lib'+option(origin_argv['argv'],'--crate-name')+'-'+sid+kind
                assert [edge['unit']for edge in g['units'][key]['dependencies']if edge['extern_crate_name']==alias and edge['unit']==origin]==[origin]
                observed=case['products'][str(path.relative_to(case['target']))];assert observed[0]>0 and len(bytes.fromhex(observed[1]))==32
                if kind=='.so':assert ext_orig['crate_types']==['proc-macro']
                value=['external product',alias,origin,kind]
            elif prev=='-L':
                mode,sep,rest=x.partition('=');assert sep;directory=Path(rest)
                if mode=='dependency':
                    origin,_=supplier(directory);slot(directory,origin);value=['dependency search directory',origin]
                elif mode=='native':
                    row=one(case['native'].get(directory,[]),('native output had no unique executed producer',str(directory)));origin=one(row['graph'],('build-script run',row));slot(directory,origin);used.add(row['compile']);script_rows[origin]=row;value=['native search directory',origin]
                else:raise AssertionError(('unexpected search kind',mode,directory))
            if isinstance(value,list):terms.append([name,i,value])
            proof.append(value)
        output[name]=proof
    return {'projected':output,'bound_arguments':len(terms),'used_compiler_unit_ids':sorted(used),'slots':slot_map,'scripts':script_rows,'current_edit_producers':live,'raw':{n:r[0]for n,r in rec['forms'].items()},'phase':state}
def compare(left,right):
    a,b=prepare(left),prepare(right);assert a['graph']==b['graph'];summary={};forward={};back={};cc={}
    for st in 'BCD':
        x,y=project(a,left,st),project(b,right,st);assert x['projected']==y['projected'],('unaccounted raw arg beyond a typed dependency',st);assert x['used_compiler_unit_ids']==y['used_compiler_unit_ids']and x['scripts'].keys()==y['scripts'].keys()
        # The same local unit number must refer to one complete graph node
        # across all consumers, phases and both genuine compiler histories.
        for inv in (x['slots'],y['slots']):assert len(inv)==len(set(inv.values()))
        xa={v:k for k,v in x['slots'].items()};yb={v:k for k,v in y['slots'].items()};assert xa.keys()==yb.keys()
        for k,v in xa.items():assert forward.setdefault(v,yb[k])==yb[k]and back.setdefault(yb[k],v)==v
        for uid in x['used_compiler_unit_ids']:
            old=one(a['records'][uid],uid);new=one(b['records'][uid],uid);assert old['entry_sha256']==new['entry_sha256'] and old['target']==new['target'];cc[uid]={'left':old,'right':new}
        differences=sum(t!=u for n in SIX for t,u in zip(x['raw'][n],y['raw'][n]));assert all(len(x['raw'][n])==len(y['raw'][n])for n in SIX)
        summary[st]={'all_six_raw_commands':{n:[digest(canon(x['raw'][n])),digest(canon(y['raw'][n]))]for n in SIX},'literal_token_differences':differences,'typed_source_argv_sha256':digest(canon(x['projected'])),'typed_arguments':x['bound_arguments'],'current_edit_producers':{k:[x['current_edit_producers'][k],y['current_edit_producers'][k]]for k in x['current_edit_producers']},'actual_compilers':len(x['used_compiler_unit_ids']),'actual_native_script_domains':{k:[x['scripts'][k],y['scripts'][k]]for k in x['scripts']}}
    return {'graph':a['graph_sha'],'full_units':len(a['graph']['units']),'unique_cargo_discriminator_map':forward,'actual_unit_producers':cc,'stages':summary,'ambiguous_or_unmatched_unused_cold_commands':[a['unmatched'],b['unmatched']]}

def verify_observed_pids(folder,material):
    d=folder/'cold-A';proof=readz(d/'producer-evidence.json.gz');raw=EVENTS['decode'](readz(d/'kernel.json.gz'));images={i['pid']:i for i in raw['images']};root=raw['root'];assert images[root]['file']==material['cargo_kernel_identity'] and raw['exits'][root]==0
    for obj in proof['compilers']:
        pid=obj['pid'];assert images[pid]['file']==material['rustc_kernel_identity']and images[pid]['argv']==obj['argv']and raw['exits'][pid]==0
        par=raw['births'][pid]
        while par not in images:par=raw['births'][par]
        assert par==obj['cargo']==root
    for key,v in proof['build_scripts'].items():
        i=images[int(key)];assert i['file']==v['file']and i['exe']==v['exe']and raw['exits'][int(key)]==0
    return len(proof['compilers'])

def same_raw_roster(a,b):
    return {k:sorted(v)for k,v in a.items()}=={k:sorted(v)for k,v in b.items()}

def eligible_histories(root):
    from basis import read
    mat=read(root/'actual-inputs.json');qual=read(root/'qualification/accepted.json')
    base=root/'qualification';ctrl=qual['control'];folders={'P':base/('signed-1'if ctrl=='R'else'corrected'),'T':base/'treatment'}
    proof=compare(folders['P'],folders['T']);assert proof==readz(base/'producer-bijection.json.gz')
    for char,folder in folders.items():
        role=ctrl if char=='P'else'F';assert verify_observed_pids(folder,mat[role])==497
        initial=readz(folder/'cold-A/argv.json.gz')['forms']
        for idx in range(1,9):
            measured=root/'pairs'/str(idx)/char
            assert same_raw_roster(initial,readz(measured/'cold-A/argv.json.gz')['forms'])
            for st in 'BCD':
                prior=readz(folder/('warm-'+st)/'argv.json.gz')['forms']
                assert prior==readz(measured/('native-'+st)/'argv.json.gz')['forms']
    return proof['graph']
