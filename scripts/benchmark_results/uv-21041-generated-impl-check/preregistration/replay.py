"""Price a preregistered set of b9 provider visits, admitting native products and the ordinary dependency graph."""
from collections import Counter
from pathlib import Path
import fcntl, hashlib, json, os, re, runpy, shlex, subprocess, sys
h=Path(__file__).resolve().parent
d=h.parents[1]
sel=h.parent/'trait-selection-21041'
domain=h.parent/'incoherent-crate-domain-21041'
ground=h.parent/'incoherent-critical-paths'
q=d/'ohm-session-parser'
dbg=h.parent/'post-callable-21041-costs/metadata-diagnostic/debugger/root'
def j(p): return json.loads(Path(p).read_bytes())
def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f,'sha256').hexdigest()
def put(p, value): p.write_text(json.dumps(value,sort_keys=True,separators=(',',':'))+'\n')
def cmd(*args): return subprocess.check_output(args,text=True).strip()
def union(rows):
    last=-1
    merged=0
    for start,end in sorted((sum(r['start'].values()),sum(r['end'].values())) for r in rows):
        assert start<end
        merged+=max(0,end-max(start,last))
        last=max(last,end)
    return merged
def run(bank):
    assert bank in [1,2] and sha(sel/'price-enrollment.json')=='be490ac08199e409aff4ff9ec6fb72a1b30588cb4b92b6d84c2f894ab183318b'
    enroll=j(sel/'price-enrollment.json')['roles']
    assert {k:(len(v),sum(r['enrolled'] for r in v)) for k,v in enroll.items()}=={'typeck_root':(82,50),'mir_borrowck':(52,47)}
    assert [r['delta_all_threads'] for r in j(sel/'counter-control/sample/cost.json')['rows']]==[9014,18014,27014]
    out=h/('bank-'+str(bank)+'-'+(sys.argv[2]if len(sys.argv)>2 else '01'));out.mkdir()
    acc=runpy.run_path(str(d/'instructions/account.py'));acc['verify_profiler']()
    nr=domain/f'study/run-02/native-seed-candidate-{bank}.json';native=j(nr)
    original=ground/f'transfer-candidate-{bank}-01'
    prior=j(original/'setup.json');ordinary=j(original/'accepted.json')['phases']['native']
    sdk=Path(j(domain/'retry01/run-41407590585/artifact-receipt.json')['physical_sdk'])
    driver,=(sdk/'lib').glob('librustc_driver-*.so')
    identity=sha(driver)
    assert native['source']=='b9b3f6bba90145e25eb3b76864cfd0b5f4cbdc1f' and prior['bank_sha256']==sha(nr)
    assert identity==j(sel/'mark-elf.json')['driver']
    a,b=Path(native['a_seed']),Path(native['b_history'])
    seq=Path(native['native_argv']);assert sha(seq)==native['native_argv_sha256']
    ar,=[v for v in j(seq) if v[v.index('--crate-name')+1]=='uv_client']
    slot=Path(ar[0]).parents[1];inc=Path(next(x.split('=',1)[1] for x in ar if x.startswith('incremental=')))
    dest=Path(ar[ar.index('--out-dir')+1]);t=inc.parents[1];src=q/'source-21041';case=j(q/'open-21041/case.json')['source']
    for root,meta in [(a,j(native['a_products'])['metadata']),(b,j(native['b_products'])['metadata'])]:
        assert len(meta)==37 and all(sha(root/k)==v['sha256'] for k,v in meta.items())
    ext={ar[i+1].partition('=')[0]:sha(b/Path(ar[i+1].partition('=')[2]).relative_to(t))
         for i,k in enumerate(ar) if k=='--extern' and '='in ar[i+1]}
    assert ext==prior['all_terminal_externs'] and len(ext)==58
    unit,=(a/inc.relative_to(t)).glob('uv_client-*')
    seed=prior['prior_incremental_files']
    assert {f.relative_to(unit).as_posix():sha(f)for f in unit.rglob('*') if f.is_file()}==seed
    expected={f.name:sha(f) for f in (b/dest.relative_to(t)).iterdir() if f.is_file()}
    assert expected==ordinary['products']
    elf=cmd('nm','-anS','-C','--defined-only',driver).splitlines()
    symbols={};opcodes={};disasm={}
    for role,fullname in [('typeck_root','rustc_hir_typeck::typeck_root'),('mir_borrowck','rustc_borrowck::mir_borrowck')]:
        row,=[l.split(maxsplit=3) for l in elf if l.endswith(' T '+fullname)]
        addr=int(row[0],16);symbols[role]=addr
        disasm[role]=cmd('objdump','-dC','--start-address='+hex(addr),'--stop-address='+hex(addr+min(96,int(row[1],16))),driver)
        # The previous independent ELF inspection proves the executable segment offset for this exact driver.
        with driver.open('rb') as f:
            f.seek(addr-j(sel/'mark-elf.json')['ELF_va_minus_file']);opcodes[role]=f.read(min(16,int(row[1],16))).hex()
    assert 'mov    %esi,%ebp' in disasm['mir_borrowck'] and 'is_typeck_child' in disasm['mir_borrowck']
    put(out/'disassembly.json',disasm)
    spec={'argv':ar,'driver':str(slot/'lib'/driver.name),'digest':identity,'symbols':symbols,'opcodes':opcodes,
          'vgdb':str(acc['VALGRIND'].parent/'vgdb'),'valgrind':str(acc['VALGRIND']),'valgrind_lib':str(acc['LIB']),
          'translator':str(acc['TRANSLATOR']),'gdb':str(dbg/'usr/bin/gdb'),'gdb_lib':str(dbg/'usr/lib/x86_64-linux-gnu'),
          'ground':sha(original/'accepted.json'),'enrollment':sha(sel/'price-enrollment.json'),'bank':sha(nr),
          'expected_graph':ordinary['dep_graph'],'counter_program':sha(h/'charge.py'),'runner':sha(__file__),
          'inner':sha(h/'inner.py'),'unobserved_guest_Ir':j(domain/f'study/run-02/guest-candidate-{bank}.json')['counts']['uv_client']['Ir']}
    put(out/'request.json',spec)
    ref,=[shlex.split(line.strip().removeprefix('Running `').removesuffix('`')) for line in (seq.parent/'first-b.stderr').read_text().splitlines() if line.lstrip().startswith('Running `') and ' --crate-name uv_client 'in line]
    cut=ref.index(ar[0]);assert ref[cut:]==ar
    env=dict(x.split('=',1) for x in ref[:cut]);assert all(k.startswith('CARGO') for k in env)
    env.update(PATH=str(slot/'bin')+':/usr/bin:/bin', HOME='/tmp', CARGO_HOME=str(q/'cargo-home'),
               CARGO_TARGET_DIR=str(t),RUSTC=str(slot/'bin/rustc'),RUSTDOC=str(slot/'bin/rustdoc'),
               LC_ALL='C.UTF-8',SSL_CERT_FILE='/usr/lib/ssl/cert.pem',SSL_CERT_DIR='/usr/lib/ssl/certs')
    wi=out/'inc';wo=out/'out';wi.mkdir();wo.mkdir()
    subprocess.run(['cp','-a','--reflink=auto','--',unit,wi/unit.name],check=True)
    assert all(sha(wi/unit.name/f)==ds and not (wi/unit.name/f).samefile(unit/f)for f,ds in seed.items())
    with (q/'source-lease.lock').open() as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        assert cmd('git','-C',src,'hash-object',case['file'])==case['original_blob_B']
        present=t.exists()
        if not present:t.mkdir()
        try:
            cl=['/usr/bin/bwrap','--die-with-parent','--unshare-net','--ro-bind','/','/','--proc','/proc','--dev','/dev',
                '--tmpfs','/tmp','--ro-bind',b,t,'--ro-bind',sdk,slot,'--bind',wi,inc,'--bind',wo,dest,'--bind',out,
                '/tmp/evidence','--chdir',src,'--','/usr/bin/python3','-ISB',h/'inner.py']
            subprocess.run(cl,env=env,check=True,timeout=1420)
        finally:
            if not present:t.rmdir()
    graph,=wi.glob('uv_client-*/s-*/dep-graph.bin')
    obtained={f.name:sha(f)for f in wo.iterdir()if f.is_file()}
    assert sha(graph)==ordinary['dep_graph'] and obtained==expected and all(sha(unit/f)==ds for f,ds in seed.items())
    cost=j(out/'cost.json');assert cost['exit']==0 and not cost['fault'];rows=cost['rows']
    exact=Counter((k,v['local_index']) for k,vs in enroll.items()for v in vs)
    assert Counter((r['symbol'],r['index']) for r in rows)==exact and all(n==1 for n in exact.values())
    selected={(k,v['local_index'])for k,vs in enroll.items()for v in vs if v['enrolled']}
    hit=[r for r in rows if (r['symbol'],r['index']) in selected]
    items=(out/'raw.cg').read_text();tot,=map(int,re.findall(r'^summary: (\d+)$',items,re.M))
    assert len(rows)==134 and len(hit)==97 and max(sum(r['end'].values())for r in rows)<=tot
    assert abs(tot/spec['unobserved_guest_Ir']-1)<.005
    scope={role:{'all':union([r for r in rows if r['symbol']==role]),
                 'selected':union([r for r in hit if r['symbol']==role])}for role in enroll}
    put(out/'accepted.json',{'source':native['source'],'scope':scope,'whole_guest_Ir':tot,'prior_without_debugger':spec['unobserved_guest_Ir'],
        'all_provider_union_Ir':union(rows),'enrolled_union_Ir':union(hit),'enrolled_percentage':100*union(hit)/tot,
        'counts':[len(rows),len(hit)],'index_and_multiplicity_matched':True,'ordinary_graph':sha(graph),'ordinary_products':obtained,
        'aggregate_cost':sha(out/'raw.cg'),'subintervals':sha(out/'cost.json'),'request':sha(out/'request.json'),'kernel':sha(out/'kernel.json')})
    print(out,j(out/'accepted.json')['enrolled_percentage'])
if __name__=='__main__':run(int(sys.argv[1]))
