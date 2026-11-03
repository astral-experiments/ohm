"""Verify a complete original two-compiler Ruff build parcel and independently price the registered gates."""
import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import struct
import subprocess
import tempfile
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parent))
import mono_rows
import partitions

STAGES = ('cold-old', 'old-unchanged', 'edit', 'edited-unchanged', 'repair', 'reverse', 'observed-edit', 'empty-new')
OLD = {'cold-old', 'old-unchanged', 'reverse'}
ELF = b'\x7fELF\x02\x01\x01'
HERE = Path(__file__).resolve().parent
def demand(value, reason):
    if not value:
        raise ValueError(reason)
def sha(b):
    return hashlib.sha256(b).hexdigest()
def whole(j):
    demand(j['status'] == 0 and j['instructions'] > 0 and j['enabled'] == j['running'] > 0, 'unqualified whole hardware')
    return j['instructions']
def body(z, key, total=False):
    """Use a short-lived compressed scratch file and cap every uncompressed product."""
    digest = hashlib.sha256(); size = 0; data = bytearray()
    with tempfile.TemporaryFile() as f, z.open(key) as comp:
        shutil.copyfileobj(comp, f, 1 << 18); f.seek(0)
        with subprocess.Popen(['zstd','-qdc'],stdin=f,stdout=subprocess.PIPE) as proc:
            for b in iter(lambda:proc.stdout.read(1 << 18),b''):
                if total or not data:
                    data.extend(b if total else b[:32])
                size += len(b); digest.update(b)
                demand(size < 512 * 2**20, 'oversized raw product')
            demand(proc.wait() == 0, 'truncated retained product')
    demand(key.rsplit('/',1)[-1] == digest.hexdigest() + '.zst', ('unbound raw product',key))
    return size, bytes(data)
def roster(z,prefix):
    """Join the ar reader's actual native member to its independently identified physical work product."""
    read = lambda name: json.loads(z.read(prefix + '/' + name))
    ar=read('selected-ruff-members.json'); members={r[2]+'.o':(r[3],r[4]) for r in ar['members']}
    demand(len(members)==len(ar['members']) and ar['symbols']>0 and len(ar['symbol_map'])==64,'GNU ar index and complete member names')
    all_sessions=read('incremental-native-sessions.json')
    # The E0308 probes leave incomplete working dirs. Only final generation names can supply rustc's actual product.
    observed={k:v for k,v in all_sessions.items() if not k.endswith('-working')}
    demand(all(re.fullmatch(r's-[0-9a-z]+-[0-9a-z]+-[0-9a-z]{25}',k.split('/')[-1]) for k in observed),'unrecognized final rustc generation')
    matched=[]
    for session,rows in observed.items():
        demand(len({r[0] for r in rows})==len(rows) and all(len(r)==6 and r[4]>0 and len(r[5])==64 for r in rows),'malformed physical WIPs')
        if {r[0]:(r[5],r[4])for r in rows} == members:
            matched.append(session)
    demand(len(matched)==1 and len(observed)==2,'inconsistent matching lib and bin WIPs')
    lib=matched[0];other,=set(observed)-{lib}
    return {n:{r[0]:r for r in observed[k]}for n,k in (('lib',lib),('bin',other))}, ar, lib
def lifetimes(z,prefix):
    """Decode the original image argv and kernel counter stream without trusting derived counts."""
    images={};rust=[];link=[];w=[]
    for l in z.read(prefix+'/epochs.tsv').splitlines():
        f=l.split()
        if f[0]==b'I':
            i,pid=map(int,f[1:3]);raw=z.read(f'{prefix}/{i:05}.nul').split(b'\0')
            demand(i not in images and raw.pop()==b'' and int(raw[0])==pid,'ambiguous process image')
            images[i] = (pid,os.fsdecode(raw[3]),list(map(os.fsdecode,raw[4:])))
        if f[0]==b'R':
            i,pid,n,e,r,status=map(int,f[1:]);owner,exe,args=images[i]
            demand(owner==pid and n>0 and e==r>0 and status==0,'unqualified actual process')
            if exe.endswith('/bin/rustc') and '--crate-name' in args:
                crate=args[args.index('--crate-name')+1];kind=args[args.index('--crate-type')+1] if '--crate-type'in args else None
                rust.append((crate,kind,n))
            elif exe.endswith('/wild-ld/ld.bfd'):
                link.append(n)
        if f[0]==b'W':
            n,e,r,status=map(int,f[1:]);demand(n>0 and e==r>0 and status==0,'partial enclosing collection');w.append(n)
    demand(len(w)==1,'missing whole process period')
    return dict(whole=w[0],rustcs=rust,wild=link)
def verdict(z,path,case,state,reg,prod):
    v=prod['verdict']
    for name,info in v['cases'].items():
        code,h,e=([info['exit'],info['out'],info['err']] if isinstance(info,dict) else info)
        raw=z.read(f'{path}/{name}.stdout');err=z.read(f'{path}/{name}.stderr')
        demand(sha(raw)==h and sha(err)==e,'different native verdict bytes')
        if name.endswith('help')or name=='help':
            demand(code==0 and not err,'invalid help')
            text=b' '.join(raw.split())
            if case=='28392':demand((b'--config "lint.line-length = 100"'in text)==(state=='old')and(b'--config "line-length = 100"'in text)==(state=='new'),'wrong real example')
            else:demand((b'--extend-exclude'in text)==(state=='new'),'wrong real Format option')
        elif name in ('valid-config','lint'):
            demand(code==1 and b'F401'in raw and not err,'wrong real lint')
        elif name in ('invalid-config','bad-config'):
            demand(code==2 and b'--config'in err and b'line-length'in err,'wrong real invalid option')
        else:
            demand(name=='actual-files','unknown runtime case')
            if state=='old':demand(code==2 and b'unexpected argument'in err and b'--extend-exclude'in err,'old flag unexpectedly accepted')
            else:demand(code==1 and b' '.join(raw.split())==b'Would reformat: main.py 1 file would be reformatted'and not err,'different real directory verdict')
    if case=='28392':
        commit=json.loads(z.read(path+'/version.stdout'))['commit_info']['commit_hash'];demand(commit==reg['native_sources'][0 if state=='old'else 1],'wrong executable Git hash')
    return v
def get_fns(data):
    """Read each defined native ELF function and its full emitted size."""
    demand(data.startswith(ELF) and struct.unpack_from('<HH',data,16)==(1,62),'non-ordinary x86_64 object')
    h=struct.unpack_from('<16sHHIQQQIHHHHHH',data);s,n,off=h[11],h[12],h[6]
    demand(s==64 and 0<n<65535 and off+n*s<=len(data),'bad section table')
    sections=[struct.unpack_from('<IIQQQQIIQQ',data,off+i*s) for i in range(n)]
    syms,=[v for v in sections if v[1]==2];strings=sections[syms[6]]
    demand(strings[1]==3 and syms[9]==24 and syms[5]%24==0,'bad .symtab layout');out=[]
    buf=data[strings[4]:strings[4]+strings[5]]
    for i in range(syms[4],syms[4]+syms[5],24):
        offset,kind,vis,idx,pos,length=struct.unpack_from('<IBBHQQ',data,i)
        if kind&15!=2 or not 0<idx<n:continue
        demand(pos+length<=sections[idx][5],'function outside section')
        name=buf[offset:buf.index(b'\0',offset)]
        if name.startswith((b'_R',b'_ZN')):out.append((name.decode('ascii'),length,kind>>4))
    return out
def clap_owners(rows):
    names=sorted({name for items in rows.values() for name,_,_ in items})
    demangled=subprocess.check_output(['c++filt','-n'],input=''.join(x+'\n' for x in names).encode()).decode().splitlines()
    demand(len(names)==len(demangled),'demangler omitted a symbol')
    method={}
    for old,s in zip(names,demangled):
        m=re.fullmatch(r'<ruff::args::([A-Za-z0-9_]+) as clap_builder::derive::(Args|FromArgMatches|Subcommand|CommandFactory)>::(.+)',re.sub(r'\[[a-f0-9]{4,16}\]','',s))
        if m:method[old]=m.group(1)
    grouped=collections.defaultdict(lambda:collections.defaultdict(lambda:[0,0,0]))
    for unit,items in rows.items():
        for n,b,linkage in items:
            if n in method:
                rec=grouped[method[n]][unit];rec[0]+=1;rec[1]+=b;rec[2]+=linkage==1
    return {k:dict(v)for k,v in grouped.items()}
def verify_role(z,role,reg,case):
    read=lambda name:json.loads(z.read(role+'/'+name))
    src=read('factory/source.json');sdk=read('factory/sdk.json');name={'P':'parent','C':'candidate'}[role];spec=reg['transports'][role]
    demand(src['source']==reg['registration'][name] and src['tree']==reg['registration'][name+'_tree'] and sdk['driver']==spec['driver'] and sha(z.read(role+'/factory/bootstrap.json'))=='3129eb48157c6b610c65b818ac9f86269ab1257020cf12d29701a36111460993','different immutable SDK')
    products={};states={};price={};cgas={};ars={};sizes={};runtime={};scanned={};have_elf={};scans={};partial=collections.Counter()
    actual_stages=tuple(('restored-old' if s=='reverse'else s) for s in STAGES) if role+'/initial-old-namespace.json'in z.namelist() else STAGES
    if 'restored-old' in actual_stages:
        a=read('initial-old-namespace.json');b=read('restored-old-namespace.json');demand(a==b and len(a['sha256'])==64 and a['logical_unique_bytes']>0,'incomplete original namespace')
    for ph in actual_stages:
        pre=role+'/'+ph;prod=read(ph+'/products.json');products[ph]=prod;price[ph]=whole(read(ph+'/hardware.json'));verdict(z,pre,case,'old'if ph in OLD|{'restored-old'} else'new',reg,prod)
        for k in ('elf','rmeta','embedded_rmeta'):
            if k in prod:
                r=prod[k]['sha256'];key=role+'/bodies/'+r+'.zst'
                if r not in have_elf:have_elf[r]=body(z,key)
                length,header=have_elf[r];demand(length==prod[k]['size']and(k!='elf'or header.startswith(ELF)),'wrong original CLI/metadata')
        states[ph],ars[ph],session=roster(z,pre)
        if ph in ('cold-old','edit','empty-new'):
            decl=read(ph+'/library-ordinary-partition.json');demand(decl['session']==session and decl['members']=={k:v[5]for k,v in states[ph]['lib'].items()},'real selected RSIC/ELF relation')
            n,raw=body(z,role+'/native/'+decl['cache']+'.zst',True);demand(n==decl['bytes']and raw.startswith(b'RSIC'+{'P':57124,'C':60597}[role].to_bytes(2,'little')),'wrong compiler-specific RSIC')
            census=None
            try:
                table=partitions.table(raw,{'objects':decl['members']},None,len(decl['members']));demand(table==read(ph+'/complete-cgu-table.json'),'original query vectors differ')
            except (IndexError,ValueError) as exc:
                demand(pre+'/cgu-decode-refusal.json'in z.namelist(),'unexpected query-table failure');census={'refused':str(exc)}
            if census is None:
                verified={};refused={}
                for unit,row in table['rows'].items():
                    try:v=mono_rows.read(raw,row)
                    except (IndexError,UnicodeError,ValueError) as exc:refused[unit]=str(exc)[:360];continue
                    verified[unit]={'roots':sum(not x[4]for x in v),'root_mir':sum(x[7]for x in v if not x[4]),'inline_memberships':sum(x[4]for x in v),'inline_mir':sum(x[7]for x in v if x[4])}
                saved=read(ph+'/typed-inline-census.json');demand(verified==saved['decoded']and refused==saved['refused']and sum(x['size']for x in table['rows'].values())==saved['total_mir']and sum(x['items']for x in table['rows'].values())==saved['total_memberships'],'ordinary inline data does not match')
                sums=collections.Counter();[sums.update(v)for v in verified.values()];census={'units':len(table['rows']),'refused_units':len(refused),'memberships':saved['total_memberships'],'estimated_mir':saved['total_mir'],'decoded':dict(sums)}
            cgas[ph]=census
            now={}
            for key,row in states[ph]['lib'].items():
                h=row[5]
                if h not in scanned:
                    n,data=body(z,role+'/native/'+h+'.zst',True);demand(n==row[4],'bad physical native object size');scanned[h]=get_fns(data)
                now[key]=scanned[h]
            scans[ph]=clap_owners(now);sizes[ph]=read(ph+'/footprint.json')
            rr={}
            for label in ('top-help','format-help'):
                prices=[]
                for i in range(3):
                    prices.append(whole(read(f'{ph}/native-{label}-{i}.json')))
                    out=read(f'{ph}/native-{label}-{i}-output.json');demand(out['elf']==prod['elf']['sha256']and out['stderr']==sha(b''),'invalid native runtime')
                rr[label]=prices
            runtime[ph]=rr
    for ph in ('invalid','invalid-unchanged'):
        err=z.read(f'{role}/{ph}/stderr');demand(b'error[E0308]'in err and b'owner_cgu_invalid'in err,'bad edit falsely succeeded')
    for ph in actual_stages:
        ref='cold-old'if ph in OLD|{'restored-old'} else'edit'
        demand(products[ph]['verdict']==products[ref]['verdict']and products[ph]['elf']==products[ref]['elf'],'unwanted CLI program change')
        for kind in ('lib','bin'):
            f=lambda key:{k:(r[4],r[5])for k,r in states[key][kind].items()}
            demand(f(ph)==f(ref),'independently reconstructed native output changed')
    demand(products['cold-old']['elf']!=products['edit']['elf']and products['cold-old']['verdict']!=products['edit']['verdict'],'edit had no native effect')
    for ph in (['old-unchanged','edited-unchanged','observed-edit']+(['restored-old']if 'restored-old'in actual_stages else [])):
        k=lifetimes(z,f'{role}/{ph}/kernel-execs');trusted=read(ph+'/lifetime.json');demand(k['whole']==trusted['whole']and list(map(list,k['rustcs']))==trusted['rustcs']and k['wild']==trusted['wild_lifetimes'],'derived lifetime prices differ')
        if ph=='observed-edit':
            demand(sorted((n,t)for n,t,_ in k['rustcs'])==[('ruff','bin'),('ruff','lib')] and k['wild'],'wrong re-edited Rust or linker workload')
            detail={**k,'lib':next(x for _,t,x in k['rustcs']if t=='lib'),'bin':next(x for _,t,x in k['rustcs']if t=='bin')}
        else:demand(not k['rustcs']and not k['wild'],'actual settled Rust/link work')
    transitions={}
    for kind in ('lib','bin'):
        a,b=states['cold-old'][kind],states['edit'][kind];shared=a.keys()&b.keys()
        kept={k for k in shared if a[k][1:]==b[k][1:]};same={k for k in shared if a[k][4:]==b[k][4:]}
        transitions[kind]={'before':len(a),'after':len(b),'new_names':sorted(b.keys()-a.keys()),'removed_names':sorted(a.keys()-b.keys()),'physical_donors':len(kept),'rebuilt_unchanged':sorted(same-kept),'changed_in_place':sorted(shared-same),'non_donor_full_bytes':sum(r[4]for k,r in b.items()if k not in kept)}
    mini=read('mini/verdict.json');guards=read('guards/guard-verdict.json');demand(mini['edit']==mini['clean']and len(set(mini['named_native_units'].values()))==(1 if role=='P'else 3),'derive native control')
    return dict(compiler=src,driver=sdk['driver'],ordinary=price,lifetime=detail,transitions=transitions,census=cgas,storage=sizes,runtime=runtime,native_clap=scans,guards=guards,metadata_warm_clean={k:products['edit'].get(k)==products['empty-new'].get(k)for k in ('rmeta','embedded_rmeta','rlib','canonical_archive')},elf={k:products[k]['elf']for k in('cold-old','edit','empty-new')},source_verdicts={k:products[k]['verdict']for k in('cold-old','edit','empty-new')},original_objects=len(scanned),raw_bodies=len(have_elf))
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('archive',type=Path);p.add_argument('digest');p.add_argument('output',type=Path);args=p.parse_args()
    with args.archive.open('rb')as f:demand(hashlib.file_digest(f,'sha256').hexdigest()==args.digest,'wrong complete Actions ZIP')
    with zipfile.ZipFile(args.archive)as z:
        demand(len(z.namelist())==len(set(z.namelist())),'duplicate ZIP members')
        reg=json.loads(z.read('registration.json'));case=reg['case'];demand(reg['registration']==json.loads((HERE/'registration.json').read_bytes())and reg['transports']==json.loads((HERE/'transports.json').read_bytes())and reg['order']=={'28392':'PC','26372':'CP'}[case],'wrong source cohort')
        demand(json.loads(z.read('terminal.json'))=={'case':case,'paired':True,'order':reg['order']},'worker refusal')
        results={role:verify_role(z,role,reg,case)for role in reg['order']};a,b=results['P'],results['C'];demand(a['source_verdicts']==b['source_verdicts'],'cross-role native answers differ')
    cu=lambda x:100*(1-b['ordinary'][x]/a['ordinary'][x]);delta={k:cu(k)for k in a['ordinary']};case_result={'sha256':args.digest,'case':case,'boot':reg['boot'],'order':reg['order'],'roles':results,'whole_reduction_pct':delta,'library_rustc_reduction_pct':100*(1-b['lifetime']['lib']/a['lifetime']['lib']),'whole_only_this_registered_pair':True}
    args.output.write_text(json.dumps(case_result,sort_keys=True,indent=1)+'\n')
    print(case,reg['order'],a['ordinary']['edit'],b['ordinary']['edit'],round(delta['edit'],3),round(case_result['library_rustc_reduction_pct'],3))
if __name__=='__main__':main()
