"""Join real compiler work-products, kernel thread names, and exact per-thread counters."""
import collections
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import zipfile

def require(ok,msg):
    if not ok:raise ValueError(msg)
def openzip(path,digest):
    with path.open('rb')as f:require(hashlib.file_digest(f,'sha256').hexdigest()==digest,'artifact SHA')
    return zipfile.ZipFile(path)
def get(z,key):
    return json.loads(z.read(key))

def module_rows(z):
    stages={};ledger={}
    for ph in ('old','edit','independent-clean-new'):
        listing=get(z,ph+'/selected-ruff-members.json')
        members={r[2]:r for r in listing['members']};require(len(members)==len(listing['members'])==236,'expected full library')
        groups=get(z,ph+'/incremental-native-sessions.json');matches=[]
        for here,items in groups.items():
            physical={r[0][:-2]:r for r in items if r[0].endswith('.o')};require(len(physical)==len(items),'unknown object')
            if physical.keys()==members.keys():
                require(all(tuple(physical[k][4:6])==(m[4],m[3]) for k,m in members.items()),'physical bytes vs ranlib member')
                matches.append(here)
        require(len(matches)==1 and len(groups)==2,'ambiguous library or bin session')
        lib=matches[0];other,=set(groups)-{lib}
        require(len(groups[other])==20,'unexpected binary object inventory')
        stages[ph]={f:{r[0][:-2]:r for r in groups[s]}for f,s in [('lib',lib),('bin',other)]}
        ledger[ph]={'native_roster':sorted(members),'ranlib':listing['symbol_map'],'ranlib_count':listing['symbols'],'canonical_link_wrapper':listing['link_wrapper'],'metadata':listing['metadata'],'session_paths':{'lib':lib,'bin':other}}
    transitions={}
    for fr,to in [('old','edit'),('edit','independent-clean-new')]:
        transitions[fr+' to '+to]={}
        for f in ('lib','bin'):
            a,b=stages[fr][f],stages[to][f];require(a.keys()==b.keys(),'wrong object names')
            names=sorted(a);retained=[n for n in names if a[n][1:]==b[n][1:]];equal=[n for n in names if a[n][4:]==b[n][4:]];unseen=sorted(set(names)-set(retained))
            transitions[fr+' to '+to][f]={'roster':len(a),'same_device_inode_mtime_size_sha':len(retained),'same_size_sha':len(equal),'new_physical_names':unseen if fr=='old'else None,'changed_body_names':sorted(set(names)-set(equal))}
    return stages,ledger,transitions

def kernel_comm(z):
    key='sampled-edit/kernel.perf'
    try:data=z.read(key)
    except KeyError:data=subprocess.check_output(['zstd','-dcq'],input=z.read(key+'.zst'))
    require(data[:8]==b'PERFILE2','perf format');at,size=struct.unpack_from('<QQ',data,40);end=at+size
    require(end<=len(data),'kernel section bounds');records=collections.Counter();names=collections.defaultdict(list)
    while at<end:
        ty,misc,width=struct.unpack_from('<IHH',data,at)
        require(8<=width<=end-at,'kernel record bounds');records[ty]+=1
        if ty==3:
            pid,tid=struct.unpack_from('<II',data,at+8)
            raw=data[at+16:at+width].split(b'\0',1)[0]
            require(len(raw)<=15,'kernel task name')
            names[pid,tid].append(raw.decode(errors='replace'))
        at+=width
    require(records[2]==records[13]==0 and records[9]>0,'lost records')
    return names,records

def exact_clocks(z,phase):
    owners=get(z,phase+'/owners.json');capture=phase+'-actual-execs';rows=z.read(capture+'/epochs.tsv').decode().splitlines()
    counters=collections.Counter();images={};times={};all_count=None
    for row in rows:
        fields=row.split();tag=fields[0]
        if tag=='I':
            image,pid,tid,stamp=map(int,fields[1:5]);parts=z.read(capture+f'/{image:05}.nul').split(b'\0')
            require(int(parts[0])==pid and parts[-1]==b'','kernel image/argv')
            images[image]=(pid,(int(parts[1]),int(parts[2])),parts[3].decode(),fields[5]);times[image]=stamp
        elif tag=='C':
            im,pid,tid,ir,enabled,running=map(int,fields[1:])
            require(enabled==running and ir>=0 and (im==0 or (im in images and images[im][0]==pid)),'bad per-thread work')
            counters[im,pid,tid]+=ir
        elif tag=='R':
            im,pid,ir,en,run,status=map(int,fields[1:])
            require(status==0 and en==run>0 and ir>0,'incomplete target')
        elif tag=='W':
            all_count,en,run,status=map(int,fields[1:])
            require(status==0 and en==run>0 and all_count>0,'incomplete whole')
    require(all_count==owners['whole_observed'],'whole boundary')
    results={};proc_counter=collections.Counter();images_ir=collections.Counter()
    selected={tuple(v['identity']):('wild'if v['owner']=='wild'else 'rustc')for v in owners['lifetimes']}
    for k,n in counters.items():
        image,pid,tid=k;images_ir[image]+=n
        if image not in images:proc_counter['not yet identified']+=n;continue
        t,image_identity,path,origin=images[image]
        f=selected.get(image_identity,Path(path).name)
        if f=='rustc':
            anchors=[v for v in owners['lifetimes']if v['image']==image and v['pid']==pid]
            f=anchors[0]['owner']if anchors else 'other physical rustc process'
        elif f=='wild':f='wild fork worker'if origin=='first'else 'wild launcher'
        proc_counter[f]+=n
    for owner in owners['lifetimes']:
        i,p=owner['image'],owner['pid'];part={tid:n for(im,pid,tid),n in counters.items()if (im,pid)==(i,p)}
        require(sum(part.values())==owner['instructions'],'selected whole task vs sum of distinct exact thread counters')
        results[p]={'owner':owner['owner'],'threads':part}
    return results,{'whole':all_count,'sum_of_all_thread_events':sum(counters.values()),'by_image_role':dict(proc_counter)}

def main(ordinary,osum,diag,dsum,out):
    with openzip(ordinary,osum)as z,openzip(diag,dsum)as p:
        stages,ledgers,t=module_rows(z);actual=get(z,'admission.json')
        require(actual['same_check_or_runtime_verdict']and actual['edit']['elf']==actual['clean']['elf'],'true clean native CLI')
        for l in ('true-edit','sampled-edit'):
            ph=get(p,l+'/products.json')
            require(all(ph[k]==actual['edit'][k]for k in ('canonical_archive','elf','rmeta','embedded_rmeta','verdict')),'selected native/metadata control')
        comm,records=kernel_comm(p);task,trace=exact_clocks(p,'sampled-edit');_,un=exact_clocks(p,'true-edit')
        groups={};details={}
        for pid,r in task.items():
            if not r['owner'].startswith('rustc:ruff:'):continue
            kind=r['owner'].rsplit(':',1)[-1];roster=stages['old'][kind]
            seen=set();cost=collections.Counter();by_module={}
            for tid,n in r['threads'].items():
                names=comm.get((pid,tid),[]);labels=[v for v in names if v.startswith(('opt ','cpy '))]
                if not labels:cost['other']+=n;continue
                require(len(set(labels))==1,'worker changed codegen assignment');mark,prefix=labels[0].split(' ')
                match=[k for k in roster if k.startswith(prefix)]
                require(len(match)==1 and match[0]not in seen,'ambiguous kernelCGU identity')
                unit=match[0];seen.add(unit);cost[mark]+=n
                require((mark=='opt')==(unit in t['old to edit'][kind]['new_physical_names']),'worker classification conflicts with genuine prior inode')
                if mark=='opt':
                    a,b=stages['old'][kind][unit],stages['edit'][kind][unit];by_module[unit]={'thread':tid,'full_thread_user_instructions':n,'changed_bytes':a[5]!=b[5],'old_size':a[4],'new_size':b[4],'old_sha':a[5],'new_sha':b[5]}
            require(seen==roster.keys(),'kernel names do not explain every actual object')
            groups[kind]={'counts':dict(cost),'full_lifetime':sum(r['threads'].values()),'unique_worker_names':len(seen),'typed_opt_modules':by_module}
        raw={'ordinary':osum,'diagnostic':dsum,'old_to_new_and_clean':t,'physical_archive_ledger':{k:{i:v for i,v in val.items()if i!='native_roster'} for k,val in ledgers.items()},'unprofiled_reedit_clock':un,'sampled_reedit_clock':trace,'raw_kernel_lifecycle_and_sample_records':records,'pc_refused':bool(records[5]or records[6]),'exact_cgu_thread_clock':groups}
        out.write_text(json.dumps(raw,sort_keys=True,indent=2)+'\n')
        print({k:x['counts']for k,x in groups.items()})
if __name__=='__main__':main(Path(sys.argv[1]),sys.argv[2],Path(sys.argv[3]),sys.argv[4],Path(sys.argv[5]))
