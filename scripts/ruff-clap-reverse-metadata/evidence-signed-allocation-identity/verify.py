"""Reopen signed physical metadata, projected graph topology, arithmetic, and native verdicts."""
from collections import Counter,defaultdict
from pathlib import Path
import hashlib,json,subprocess,sys,zipfile
here=Path(__file__).resolve().parent
sys.path.insert(0,str(here/'helpers'))
import extract_alloc as a
import reverse_graph as g
file=here/'public-graph-and-metadata.zip'
assert hashlib.file_digest(file.open('rb'),'sha256').hexdigest()=='3b7a4a9e1fbacf0d50ae1efb28fa85a805aa567946d51244b11fb88d97cafcdb'
mod=1<<128
jread=lambda n:json.loads(z.read(n))

def shapes(d,groups,intern,fold):
    cc,parts=g.scc(d['edges'])
    successors=[set()for _ in parts]
    for j,edges in enumerate(d['edges']):
        for v in edges:
            if cc[j]!=cc[v]:
                assert cc[j]<cc[v]
                successors[cc[j]].add(cc[v])
    ids=d['ident'];index={h:i for i,h in enumerate(groups)};leaves={}
    for i,ident in enumerate(ids):
        if ident in index:
            assert d['kind'][i]==21 and not d['edges'][i] and len(parts[cc[i]])==1
            leaves[cc[i]]=ident
    tags=[None]*len(parts);weights=[None]*len(parts)
    for k in reversed(range(len(parts))):
        own=tuple(sorted((d['kind'][i],ids[i],tuple(map(tuple,d['payload'].get(str(i),[]))))for i in parts[k]))
        vector=[0]*len(groups);seen=set();children=[]
        if k in leaves:vector[index[leaves[k]]]=1
        for child in successors[k]:
            if fold and child in leaves:
                ident=leaves[child]
                if ident in seen:continue
                seen.add(ident)
            children.append(tags[child])
            vector=[(l+r)%mod for l,r in zip(vector,weights[child])]
        shape=(own,tuple(sorted(children)));tags[k]=intern.setdefault(shape,len(intern));weights[k]=tuple(vector)
    return ({key:tags[cc[n]]for key,n in d['locals'].items()},{key:weights[cc[n]]for key,n in d['locals'].items()})

def all_bytes(z,lane,phase):
    rec=jread(lane+'/'+phase+'/selected.json');raw=subprocess.check_output(['zstd','-qdc'],input=z.read('metadata/'+rec['meta_sha']+'.zst'))
    assert g.sha(raw)==rec['meta_sha'] and len(raw)==rec['bytes'];return raw

def allocations(lane):
    states=[a.recover(z,stage,lane) for stage in ('initial-consumer','producer-OLD')]
    leaf=[];vts=[]
    for phase,(rows,mem,kinds,*_) in zip(('initial-consumer','producer-OLD'),states):
        raw=all_bytes(z,lane,phase);counts=Counter(row for i,row in enumerate(rows)if i in mem and not mem[i][1]);leaf.append(counts)
        vt,=[row for row in rows if row[0]==2];encoded,end=a.scope['read'](vt,1);off=encoded-128;assert 0<=off<len(raw)-208
        vts.append((off,raw[off:off+208],vt[end:]))
    before,after=leaf;rs,rd=states;la,lb=rs[0],rd[0];assert [len(la),len(lb)]==[214,232]
    assert set(before)==set(after);changed=sorted(row for row in before if before[row]!=after[row])
    assert len(changed)==18 and all(before[r]==1 and after[r]==2 and r[1]==0 for r in changed)
    assert Counter(row for row in la if row[0]==3)==Counter(row for row in lb if row[0]==3)
    assert sum(row[0]==3 for row in la)==4 and vts[0][1:]==vts[1][1:] and vts[0][0]!=vts[1][0]
    # Each side has one vtable. Keep its separately recorded type-abbreviation difference.
    def classify(rows,decoded,tag,intern):
        memo={};active=set()
        def visit(i):
            if i in memo:return memo[i]
            assert i not in active;active.add(i)
            if i in decoded:
                pref,refs,suffix=decoded[i];shape=(0,pref,tuple((off,visit(j),immut,shared)for off,j,immut,shared in refs),suffix)
            elif rows[i][0]==2:shape=(2,tag[1],tag[2])
            else:shape=(rows[i][0],rows[i])
            active.remove(i);memo[i]=intern.setdefault(shape,len(intern));return memo[i]
        groups=defaultdict(list)
        for i in range(len(rows)):groups[visit(i)].append(i)
        return groups
    names={};aa=classify(la,rs[1],vts[0],names);bb=classify(lb,rd[1],vts[1],names);assert aa.keys()==bb.keys()
    move={}
    for key,sub in bb.items():
        ref=aa[key]
        assert len(sub)==len(ref)or(len(ref)==1 and len(sub)==2 and lb[sub[0]]==lb[sub[1]]==la[ref[0]] and la[ref[0]] in changed)
        for ix,i in enumerate(sub):move[i]=ref[ix if len(ref)==len(sub) else 0]
    for i,rec in rd[1].items():assert a.scope['pack'](rec,move)==la[move[i]]
    return {'counts':[len(la),len(lb)],'native_memory_rows_checked':[len(rs[1]),len(rd[1])],
            'preserved_provenance_edges':[sum(len(x[1]) for x in state[1].values())for state in states],
            'same_four_named_static_records':True,'vtable_type_abbreviation_targets':[v[0]for v in vts],
            'same_208_byte_type_prefix_sha256':g.sha(vts[0][1]),'doubled_memory_strings':sorted(a.literal(row)for row in changed)}

with zipfile.ZipFile(file)as z:
    sources=jread('sources.json');all_rows={};by_name={};pub={};native={}
    for lane in sorted(sources):
        (ma,ta),(mb,tb)=[g.rawmeta(z,lane+'/'+s)for s in ('initial-consumer','producer-OLD')]
        assert ma[1]==mb[1] and ta['path_by_index']==tb['path_by_index'] and ma[3]==mb[3] and ma[4]==mb[4]
        fp={k:(int.from_bytes(bytes.fromhex(mb[2][k]),'little')-int.from_bytes(bytes.fromhex(x),'little'))%mod for k,x in ma[2].items()}
        assert len(fp)==1671 and sum(bool(x)for x in fp.values())==1098
        assert ma[0]['public']!=mb[0]['public'] and ma[0]['private']==mb[0]['private'] and ma[0]['global_hash']==mb[0]['global_hash']
        pub[lane]={'headers':[ma[0],mb[0]],'same_definitions':len(ma[1]),'same_expansions':len(ma[3]),'same_required_crates':len(ma[4]),'public_rows':len(fp),'changed':1098}
        all_rows[lane]=fp;by_name[lane]={(ix,n):fp[sid]for ix,(sid,n)in ta['path_by_index'].items()if sid in fp}
        phase=[jread(lane+'/'+s+'/native.json') for s in ('initial-consumer','unchanged-consumer')]
        assert phase[0]==phase[1]
        native[lane]={'initial_restored_binary_sha256':phase[0]['sha256'],'runtime_stdout':phase[0]['help'],
                      'actual_unchanged_consumer':jread(lane+'/unchanged-consumer/real-compiler.json')}
    join=set.intersection(*(set(v)for v in by_name.values()))
    comparison={k:len({v[k]for v in by_name.values()})for k in join}
    eq=sum(n==1 for n in comparison.values());prior=by_name['first-normal-ruff'];agreed_nonzero=sum(n==1 and prior[k]!=0 for k,n in comparison.items())
    lane='later-observed-ruff';old,new=[jread(lane+'/'+ph+'/topology.json')for ph in ('initial-consumer','producer-OLD')]
    left,right=map(lambda x:Counter(x['ident']),(old,new));assert left.keys()==right.keys()
    groups=sorted(k for k in left if left[k]!=right[k]);assert len(groups)==18 and all((left[k],right[k])==(1,2)for k in groups)
    sites=[]
    for data in (old,new):
        by=defaultdict(Counter)
        for i,j,pc,count in data['allocation_sites']:
            assert j in data['edges'][i] and data['kind'][j]==21 and count>0
            by[data['ident'][j]][pc]+=count
        assert all(set(by[h])=={0x600e6b6} for h in groups)
        sites.append(sum(by[h][0x600e6b6] for h in groups))
    actual=all_rows[lane];changed={k for k,v in actual.items() if v};out={}
    for fold in (False,True):
        memo={};ta,wa=shapes(old,groups,memo,fold);tb,wb=shapes(new,groups,memo,fold);structure={k for k in ta if ta[k]!=tb[k]};vec={k for k in wa if wa[k]!=wb[k]}
        assert structure==vec==(set()if fold else changed)
        raw=defaultdict(set)
        for k,x in wa.items():raw[tuple((r-l)%mod for l,r in zip(x,wb[k]))].add(actual[k])
        if not fold:assert len(raw)==25 and all(len(v)==1 for v in raw.values())
        out[str(fold)]={'changed_observed_graph_signatures':len(structure),'changed_selected_leaf_vectors':len(vec),'different_vectors':len(raw)}
    assert len(join)>1000 and eq==len(join) and agreed_nonzero>=1084
    result={'source_files':sources,'publications':pub,'unchanged_programs':native,'numeric_same_definition_index_and_path_in_three_histories':{'common':len(join),'all_actual_128_bit_deltas_equal':eq,'common_nonzero':agreed_nonzero},
            'signed_graph_rows':[len(x['ident'])for x in (old,new)],'signed_edges':[sum(map(len,x['edges']))for x in(old,new)],'actual_class_delta_groups':25,'actual_alloc_registration_PC':'0x600e6b6','resolved_leaf_registration_calls':sites,'structural_signed_and_counterfactual':out,
            'allocations':{key:allocations(key)for key in sorted(sources)}}
print(json.dumps(result,indent=2,sort_keys=True))
