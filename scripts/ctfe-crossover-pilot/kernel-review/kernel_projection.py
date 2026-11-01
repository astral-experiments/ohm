"""Independent physical role projection; no worker process classifier or filesystem-path lookup."""
import gzip, hashlib, json, re, stat
from pathlib import Path, PurePosixPath as P
from read_events import parse, Refused, need
WILD='lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd'
STRICT='035e681081683f4141e4c544b8cf9492b73784051e4541c12bb3cbdb73a798a4'
STOCK='0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5'
COMMAND=['cargo','+ohm','build','-p','ruff','--bin','ruff','--locked','--offline','-j4','--message-format=json']
REFERENCE_SHA='d758bb61c2747b4910ecdba43c5078a6c6d622cdcb535984a5d4487c05705d8f'
REFERENCE_ON_SHA='40995c81397360c7348dae86e845ce0a24f0eb98ac6809f7aca47609c3a9bef9'
REFERENCE_WARM_SHA='0fb40e69f5f258b47d99904b1439cb58a4d0259f0a5a9bb0d14cd75d2df4095a'
QUERIES={'-v','--version','--help','--print-output-format'}
ROLES={'cargo':'bin/cargo','rustc':'bin/rustc','wild':WILD}
LINK_NAME=re.compile(r'(?:[\w.]+-)*ld(?:\.bfd|\.lld|\.gold)?|rust-lld|wild|mold')
def j(z,key):
    b=z.read(key);return json.loads(gzip.decompress(b) if key.endswith('.gz') else b)
def sha(x):return hashlib.sha256(x).hexdigest()
def time_ns(s):
    a,b=s.split('.');need(bool(re.fullmatch(r'-?\d+',a) and re.fullmatch(r'\d{9}',b)),'stat timestamp');return int(a)*10**9+int(b)
def signature(img):
    return [img['sha256'],img['dev'],img['ino'],stat.S_IMODE(img['mode']),img['size'],time_ns(img['mtime']),time_ns(img['ctime'])]
def catalog_guard(cat):
    need(set(cat)=={'cargo','rustc','wild','proxy','sysld'},'incomplete native catalog')
    ids={}
    for name,row in cat.items():
        sig=row['identity']
        need(isinstance(sig,list) and len(sig)==7 and re.fullmatch(r'[0-9a-f]{64}',sig[0]) and all(type(i) is int for i in sig[1:]) and
             sig[1]>=0 and sig[2]>0 and 0<sig[3]<=0o7777 and sig[4]>0 and sig[5]>0 and sig[6]>0 and
             all(P(row[k]).is_absolute() and '..' not in P(row[k]).parts for k in ('path','resolved')),'invalid measured executable identity')
        key=tuple(sig[1:3]);need(key not in ids,'role files aliased');ids[key]=name
    need(cat['sysld']['path']=='/usr/bin/ld','undeclared platform linker')
    return ids
def verified_catalog(z,slot,arm):
    cat=j(z,slot+'/catalog.json');catalog_guard(cat)
    active=j(z,slot+'/arm.json');physical=j(z,'sdk/'+arm[0]+'.json');man=j(z,'sdk/manifest.json');p=j(z,'sdk/proxy.json')
    need(active['arm']==arm and active['role']==physical['role']==arm[0] and physical['driver']==man['driver'] and
         active['files'][physical['driver']]==physical['files'][physical['driver']] and
         active['source_manifest']==sha(z.read('sdk/manifest.json')),'wrong physical role/driver')
    for role,path in ROLES.items():
        sig=cat[role]['identity']
        need(sig==active['files'][path]==physical['files'][path] and man['files'][arm[0]][path]==[sig[0],sig[4],sig[3]] and
             cat[role]['path']==str(P(active['sdk'])/path),'catalog/active SDK physical identity')
    need(cat['cargo']['identity'][0]==STRICT and cat['wild']['identity'][0]==STOCK and
         cat['proxy']['identity'][0]==p['sha256'] and cat['proxy']['path'] in p['paths'] and
         all(row==cat['proxy']['identity'][1:] for row in p['paths'].values()),'strict compiler/stock linker/proxy')
    return cat,tuple(p['paths'])
def opt(args,key):
    n=args.count(key);need(n==1 and args.index(key)+1<len(args),'missing or ambiguous '+key);return args[args.index(key)+1]
def link_mode(args):
    v=[a[2:] if a.startswith('-Z') else a for i,a in enumerate(args) if a.startswith('-Z') or (i and args[i-1]=='-Z')]
    return 'link-only' if any(x in ('link-only','ohm-link-only') or x.startswith(('link-only=','ohm-link-only=')) for x in v) else 'full'
def system_link(args):
    if '-o' in args:
        out=opt(args,'-o')
        need(P(out).name.startswith('conftest') and not any(x.endswith(('.rlib','.rcgu.o')) or x.startswith('@') for x in args),'undeclared platform output')
        return 'configure C executable',out
    if args[1:] and set(args[1:])<=QUERIES:return 'query',None
    traced=[re.sub(r'/tmp/cc[A-Za-z0-9]+\.(o|res)',r'/tmp/cc-TEMP.\1',x) for x in args]
    need(sha(json.dumps(traced,separators=(',',':')).encode())=='e0c317edf030a2c132af8e380e62baec0092887d07c9d139209baa0c0e87e38d',
         'unknown unlabelled platform link')
    return 'historical GCC configure default executable','a.out'
def classify(raw,cat,proxies,command,arm,code,cwd,expected_sha=None):
    closed=parse(raw,code,expected_sha);ids=catalog_guard(cat);es=iter(closed['execs'])
    rows={k:[] for k in ('rustcs','wild_processes','wild_queries','other_linkers','cargos','cargo_queries')}
    ancestry={}; selected=set(); count=0
    for line in raw.splitlines():
        f=line.split(b'\t',5);tag=f[0]
        if tag==b'R':ancestry[int(f[1])]=(None,None)
        elif tag==b'N':ancestry[int(f[4])]=ancestry[int(f[1])]
        elif tag==b'L':
            need(int(f[3]) not in selected,'required role interrupted before syscall completion')
        elif tag==b'E':
            e=next(es);count+=1
            seq,g=e['ordinal'],e['lifetime'];need((seq,g)==(int(f[1]),int(f[2])),'independent order')
            cmd,comp=ancestry[g];args=e['argv'];phys=e['exe'];path=e['execfn'];img=e['image']
            sig=signature(img);role=ids.get(tuple(sig[1:3]));names={P(a).name for a in (path,phys,args[0])}
            if role:
                selected.add(seq)
                need(cat[role]['identity']==sig,'changed enrolled physical '+role)
                if role!='proxy':need(path in {cat[role]['path'],cat[role]['resolved']} and phys==cat[role]['resolved'] and
                                      (role!='sysld' or path=='/usr/bin/ld'),'changed enrolled path or binary')
                else:need(path in proxies and phys in set(proxies)|{cat[role]['resolved']},'foreign proxy spelling')
            if any(LINK_NAME.fullmatch(n) for n in names):need(role in ('sysld','wild'),'foreign image with native linker spelling')
            if '--crate-name' in args:need(role in ('rustc','proxy'),'compiler operands presented to a foreign ELF')
            if ('cargo' in names and (args[1:]==command[2:] or args[1:]==command[1:])):need(role in ('cargo','proxy'),'foreign Cargo impersonation')
            if seq==1:need(role=='proxy' and args==command and e['cwd']==cwd,'wrong root+cwd for ordinary Cargo')
            row={'pid':e['pid'],'event':seq,'lifetime':g,'image':img['id'],'exe':path,'physical_exe':phys,'cwd':e['cwd'],'argv':args}
            if role=='cargo':
                if args[1:] in (['-V'],['-Vv'],['--version']):rows['cargo_queries'].append(row)
                else:
                    need(not rows['cargos'] and cmd is None and args[1:]==command[2:] and e['cwd']==cwd,'wrong number, cwd or argv of physical Cargo')
                    rows['cargos'].append(row);cmd=seq
            elif role=='rustc' and '--crate-name' in args and not any(a.startswith('--print') for a in args):
                crate=opt(args,'--crate-name');need(cmd is not None and bool(crate),'compiler above admitted Cargo')
                if crate in {'ruff','ruff_python_ast','ruff_python_parser'}:
                    options=[a[2:] if a.startswith('-Z') else a for i,a in enumerate(args) if a.startswith('-Z') or (i and args[i-1]=='-Z')]
                    need(('ohm-branch-cache=yes' in options)==arm.endswith('on') and 'ohm-check-relink-inputs' in options,
                         'observed branch/native flags')
                comp=(seq,crate);rows['rustcs'].append(dict(row,crate=crate,mode=link_mode(args)))
            elif role=='wild':
                if '-o' in args:
                    out=opt(args,'-o');need(cmd and comp is not None,'link has no actual compiler ancestor')
                    rows['wild_processes'].append(dict(row,output=out,rustc_event=comp[0],rustc_crate=comp[1]))
                else:
                    need(args[1:] and set(args[1:])<=QUERIES,'unknown Wild query');rows['wild_queries'].append(row)
            elif role=='sysld':
                need(cmd is not None,'system linker above Cargo');kind,out=system_link(args)
                rows['other_linkers'].append(dict(row,kind=kind,output=out))
            ancestry[g]=(cmd,comp)
    need(count==len(closed['execs']) and len(rows['cargos'])==1,'root Cargo count')
    rows.update(real_cargo=1,wild=len(rows['wild_processes']),successful_exec_count=count)
    return rows,closed
def bound_launch(z,prefix,rec):
    args=rec['observer_argv']
    need(isinstance(args,list) and len(args)==len(COMMAND)+3 and args[2]=='--' and args[3:]==COMMAND,'unknown kernel command')
    out=P(args[1]);need(out.name=='kernel.tsv' and out.is_absolute() and '..' not in out.parts and tuple(out.parts[-len(prefix.split('/'))-1:-1])==tuple(prefix.split('/')),
         'different visit ledger')
    root=out.parents[len(prefix.split('/'))]
    contact=prefix.startswith('observed/')
    tool=(root.parent if contact else root.parent/'kernel-qualification')/'tools/observe'
    where='fixtures' if contact else 'kernel-qualification/fixtures'
    need(root.name=='logs' and args[0]==str(tool),'observer/ledger is outside fixed canonical input')
    fixture=j(z,where+'/qualified.json')
    need(sha(z.read(where+'/observe.elf'))==fixture['observer_sha256'] and P(args[0]).is_absolute() and
         P(args[0]).name in ('observe','observe.elf') and '..' not in P(args[0]).parts,'observer binary enrollment')
    return args
def match_rows(derived,claimed):
    need(derived==claimed,'positive ledger and claimed physical rows differ')
def structural(z,prefix,arm,sdk_root,proxies):
    slot,phase=prefix.rsplit('/',1);cat,pins=verified_catalog(z,slot,arm)
    need(set(pins)==set(proxies) and str(P(cat['rustc']['path']).parent.parent)==sdk_root,'different SDK or proxy enrollment')
    rec=j(z,prefix+'/cargo.json.gz');bound_launch(z,prefix,rec)
    raw=gzip.decompress(z.read(prefix+'/kernel.tsv.gz'));life=j(z,prefix+'/lifecycle.json')
    rows,closed=classify(raw,cat,pins,COMMAND,arm,101 if phase=='invalid' else 0,rec['cwd'],life['sha256'])
    need(life=={k:(len(v) if isinstance(v,list) else v) for k,v in closed.items()},'changed/pasted family closure')
    phase_gate(phase,raw,rows,arm)
    match_rows(rows,j(z,prefix+'/native-execs.json.gz'))
    return {'rustcs':sorted(r['crate'] for r in rows['rustcs']),'wild':rows['wild'],'successful_execs':rows['successful_exec_count'],
            'system_links':len(rows['other_linkers']),'link_only':sum(r['mode']=='link-only' for r in rows['rustcs']),'kernel_ledger':closed['sha256']}

def phase_gate(phase,raw,rows,arm):
    """Apply the confirmed edit/repeat/invalid topology to positive events; independently bind final native statuses."""
    final_image={};statuses={}
    for line in raw.splitlines():
        f=line.split(b'\t',5)
        if f[0]==b'E':final_image[int(f[2])]=int(f[1])
        elif f[0]==b'T':statuses[int(f[1])]=int(f[3])
    def rc(row,expected):
        g=row['lifetime'];need(final_image.get(g)==row['event'] and statuses.get(g)==expected<<8,'wrong actual terminal compiler/link image or status')
    base=Path(__file__).resolve().parent
    if phase=='cold-A':
        from history import shape
        on=arm.endswith('on');raw_ref=(base/('reference-on-cold.json' if on else 'reference-cold.json')).read_bytes()
        need(sha(raw_ref)==(REFERENCE_ON_SHA if on else REFERENCE_SHA),'cold registration changed')
        ref=json.loads(raw_ref)
        need(shape(rows)==ref['native'] and rows['successful_exec_count']==ref['successful_execs'],'wrong original complete cold roster')
        return
    from history_warm import shape as warm_shape
    raw_ref=(base/'reference-warm.json').read_bytes()
    need(sha(raw_ref)==REFERENCE_WARM_SHA and warm_shape(rows)==json.loads(raw_ref)['reference'][phase],
         'different original whole-command or native per-crate roster')
    if phase=='unchanged-B':
        need([(r['crate'],r['mode']) for r in rows['rustcs']]==[('ruff','link-only')] and rows['wild']==1 and not rows['other_linkers'],'incorrect sole settled relink')
        rustc=rows['rustcs'][0];wild=rows['wild_processes'][0]
        need(wild['rustc_event']==rustc['event'] and wild['rustc_crate']=='ruff','wrong saved link parent');rc(rustc,0);rc(wild,0)
    elif phase=='invalid':
        need([(r['crate'],r['mode']) for r in rows['rustcs']]==[('ruff_python_parser','full')] and not rows['wild'] and not rows['other_linkers'],'different parser failure path')
        rc(rows['rustcs'][0],1)
    elif phase in ('first-B','return-A','return-B','repair'):
        need(len(rows['rustcs'])==(16 if phase=='repair' else 20) and all(r['mode']=='full' for r in rows['rustcs']) and rows['wild']==1 and
             rows['wild_processes'][0]['rustc_crate']=='ruff' and not rows['other_linkers'],'different real historical edit, return, or repair')
        rc(rows['wild_processes'][0],0)
    else:raise Refused('unregistered structural phase')
