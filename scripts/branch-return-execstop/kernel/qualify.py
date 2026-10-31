"""Check live-collector semantics and independent hostile record mutations, no fork or perf is used here."""
import argparse, ast, collections, gzip, hashlib, json, os, pathlib, re, statistics, sys
here=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(here))
from read_events import Refused, parse, read, need

def sha(p):
    with pathlib.Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def image(e,path):
    digest=sha(path);st=pathlib.Path(path).stat()
    return (e['image']['sha256'],e['image']['dev'],e['image']['ino'],e['image']['size'])==(digest,st.st_dev,st.st_ino,st.st_size)
def cases(d,physical=False):
    """d=output of run_cases.py; physical=True cross-checks fresh dev/ino against this boot."""
    d=pathlib.Path(d);codes={'family':23,'thread':37,'duplicate':19,'abort':13,'signals':14,'long':0}
    result={k:read(d/(k+'.tsv'),c) for k,c in codes.items()};family=result['family'];es=family['execs']
    need(len(es)==6 and family['lifetimes']==7 and family['displaced']==0,'all fork+vfork+helper bodies')
    need([x[2] for x in family['failed_exec_returns']]==[-14,-2],'bad-pointer/missing exec negative controls')
    need(sorted(e['image']['id'] for e in es)==[1,2,2,2,2,3] and len({e['pid'] for e in es[1:5]})==4,'four independent true launches')
    b=[b'identical argv0',b'x',b'x',b'',b'byte-\xff']
    need(all(list(map(os.fsencode,e['argv']))==b and e['exe']=='/usr/bin/true' for e in es[1:5]),'raw duplicate/empty/nonunicode arguments')
    need([e['execfn'] for e in es[1:4]]==['/usr/bin/true']*3 and bool(re.fullmatch('/dev/fd/[0-9]+',es[4]['execfn'])),'execveat(AT_EMPTY_PATH) and name')
    need(es[-1]['execfn'].endswith('/control-script') and es[-1]['argv']==['/bin/sh',es[-1]['execfn'],'script-argument'] and es[-1]['exe'].endswith('/dash'),'kernel binfmt script/interpreter')
    t=result['thread'];need(len(t['execs'])==2 and t['displaced']==1 and t['reaped']==1 and t['execs'][1]['former_tid']!=t['execs'][1]['pid'] and t['execs'][0]['pid']==t['execs'][1]['pid'] and t['execs'][1]['argv']==['nonleader-chosen-argv0','-c','exit 37'],'actual nonleader exec')
    u=result['duplicate']['execs'];need(len(u)==3 and len({(x['lifetime'],x['pid'],x['image']['id'],tuple(x['argv'])) for x in u})==1 and [x['ordinal'] for x in u]==[1,2,3],'identical same-PID reexec')
    a=result['abort'];need(len(a['execs'])==1 and len(a['interrupted_execs'])==1 and a['interrupted_execs'][0][2]==9 and
          (d/'abort.stdout').read_text()==f"opaque kernel notification pid={a['interrupted_execs'][0][1]} pointers=1,2,3\n",'uncopied opaque task killed in real pending kernel exec')
    need(result['signals']['lifetimes']==2 and len(result['signals']['execs'])==1,'job-control stop and continue')
    l=result['long']['execs'];expected=b"A\tB\nC'\xff"*14000+b'end'
    need(len(l)==2 and l[-1]['execfn']=='./relative-exe' and l[-1]['exe']=='/usr/bin/true' and
         list(map(os.fsencode,l[-1]['argv']))==[b'custom argv[0]',expected,b'',b''],'long real exec payload or symlink')
    if physical:
        need(image(es[0],here/'fixture') and image(es[1],'/usr/bin/true') and image(es[-1],'/bin/sh') and image(l[-1],'/usr/bin/true'),'boot-local physical file checks')
        need(pathlib.Path(es[-1]['execfn']).read_bytes()==(here/'control-script').read_bytes(),'observed private frozen shebang fixture')
    escaped={}
    for tag,why in [('escape','CLONE_UNTRACED escape'),('escape3','clone3 CLONE_UNTRACED escape')]:
        raw=(d/(tag+'.tsv')).read_bytes()
        need(b'\nREFUSE\t'+why.encode()+b'\t' in raw and b'\nOK\t' not in raw,'missing escape refusal')
        try:parse(raw,125)
        except Refused:pass
        else:raise Refused('accepted untraced descendant')
        escaped[tag]=hashlib.sha256(raw).hexdigest()
    tests={};source=(d/'family.tsv').read_text().splitlines()
    def mutation(name,rows):
        try:parse(('\n'.join(rows)+'\n').encode())
        except Refused as e:tests[name]=str(e)
        else:raise Refused('mutation accepted: '+name)
    def minus(rows,tag):
        l=list(rows);idx=next(i for i,x in enumerate(l) if x.startswith(tag+'\t'));l.pop(idx);return l
    for tag in ['E','P','B','N','C','X','T','I','OK']:mutation('drop-'+tag,minus(source,tag))
    mutation('duplicate-E',source[:3]+[source[2]]+source[3:])
    trows=(d/'thread.tsv').read_text().splitlines();mutation('missing-nonleader-displacement',minus(trows,'D'))
    mutation('misbound-former-tid',[('\t'.join([*r.split('\t')[:4],r.split('\t')[3],*r.split('\t')[5:]]) if r.startswith('E\t2\t') else r) for r in trows])
    mutation('truncate-argv',[r[:-2] if r.startswith('E\t1\t') else r for r in source])
    mutation('forge-terminal',[r.replace('OK\t23','OK\t22') if r.startswith('OK\t') else r for r in source])
    mutation('unclosed-before-false-terminal',source[:-2]+[source[-1]])
    orig=(d/'family.tsv').read_bytes()
    try:parse(orig,23,'0'*64)
    except Refused as e:tests['wrong-bound-raw-sha']=str(e)
    else:raise Refused('SHA binding ignored')
    out={k:{i:j[i] for i in ('code','sha256','images','lifetimes','spawned','reaped','displaced')}|{'image_installs':len(j['execs'])} for k,j in result.items()}
    return {'positive':out,'negative':escaped,'mutations_rejected':tests,'long_argument_bytes':len(expected),'live_physical_reopen':physical}
def cargo(d):
    d=pathlib.Path(d);t=json.loads((d/'terminal.json').read_text());e=json.loads((d/'enrollment.json').read_text())
    assert len(t['visits'])==18 and len({tuple(x) for x in e['phases']})==6
    counts=[]
    for n in range(1,7):
        prs=d/f'{n:02}-kernel';log=read(prs/'events.tsv.gz',0)
        old=gzip.decompress((d/f'{n:02}-strace'/'exec.raw.gz').read_bytes()).decode().splitlines()
        from historical_execs import execs as original_execs
        oldrows=[(x[1],x[2]) for x in original_execs(old)]
        rows=log['execs'];need(len(rows)==len(oldrows)==14,'genuine ordinary 14 installed processes')
        def typed(p,argv):
            basename=os.path.basename(p)
            if basename=='rustc' and '--crate-name' in argv:
                return basename,argv[argv.index('--crate-name')+1],bool('--print=file-names' in argv)
            return basename
        need(collections.Counter(typed(x['execfn'],x['argv']) for x in rows)==collections.Counter(typed(p,a) for p,a in oldrows),'historical/new native role census')
        need(sum(x['exe'].endswith('wild-ld/ld.bfd') and '-o' in x['argv'] for x in rows)==1,'one native Wild output')
        need([x['argv'][x['argv'].index('--crate-name')+1] for x in rows if '--crate-name' in x['argv'] and 'kernel_exec_small' in x['argv']]==['kernel_exec_small','kernel_exec_small'],'two project compilers')
        for suffix in ['bin/cargo','bin/rustc','wild-ld/ld.bfd']:
            h=next(v for k,v in e['file_sha256'].items() if k.endswith(suffix))
            need(any(row['exe'].endswith(suffix) and row['image']['sha256']==h for row in rows),'SDK image '+suffix)
        counts.append({k:log[k] for k in ('sha256','images','lifetimes','reaped','displaced')}|{'installed':len(rows),'historical_installed':len(oldrows)})
    visits=[]
    for v in t['visits']:
        m=json.loads((d/f"{v['block']:02}-{v['role']}"/'verified.json').read_text())
        need(m==v and v['native_elf']==t['all_elf'] and v['verdict']=='proof=18','bad physical oracle');visits.append(v)
    group={k:[v['elapsed_ns'] for v in visits if v['role']==k] for k in ['plain','strace','kernel']}
    m={k:statistics.median(ns)/1e9 for k,ns in group.items()}
    ratio={b:statistics.median(x/y for x,y in zip(group['kernel'],group[b])) for b in ('plain','strace')}
    need(m==t['median_seconds'] and ratio==t['median_paired_kernel_over'],'diagnostic clock re-open')
    return {'source_sdk':e['file_sha256'],'physical':counts,'visits':len(visits),'median_seconds':m,'median_paired_kernel_over':ratio,'complete_elf':t['all_elf']}
if __name__=='__main__':
    ap=argparse.ArgumentParser();sp=ap.add_subparsers(dest='sub',required=True)
    a=sp.add_parser('cases');a.add_argument('run');a.add_argument('--physical',action='store_true');b=sp.add_parser('cargo');b.add_argument('run')
    args=ap.parse_args();j=cases(args.run,args.physical) if args.sub=='cases' else cargo(args.run)
    print(json.dumps(j,indent=2,sort_keys=True))
