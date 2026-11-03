"""One real jobserver and section-group study. Always performs a full native link."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os,subprocess,json,gzip,shutil,threading,hashlib,sys,time
sys.path.insert(0,str(Path(__file__).resolve().parent))
import audit,prepare_groups,group_matrix,elf_container
P=audit.P;w=audit.w;b=audit.b;H=audit.H
def warm_calibration(stock,env,state):
    tiny=w.root/'boundary-smoke';arg=[str(stock),'--build-id','-o',str(tiny/'group-stock'),str(tiny/'start.o')]
    facts=[]
    for n in (1,2):
        r,wr=os.pipe()
        try:
            if n>1:os.write(wr,b'+')
            e=dict(env,CARGO_MAKEFLAGS=f'-j --jobserver-fds={r},{wr} --jobserver-auth={r},{wr}',WILD_LOG='libwild::args=trace,wild::args=trace')
            p=subprocess.run(arg,cwd=tiny,env=e,pass_fds=(r,wr),capture_output=True,timeout=5);log=p.stderr+p.stdout
            facts.append([p.returncode,log.decode()]);b.write(P/'signed-jobserver-accounting.json',facts)
            deadline=time.monotonic()+5
            while group_matrix.occupancy(r)!=n-1 and time.monotonic()<deadline:time.sleep(.002)
            assert p.returncode==0 and group_matrix.occupancy(r)==n-1
            if b'Acquired jobserver tokens'in log:assert (b'count='+str(n-1).encode())in group_matrix.re.sub(rb'\x1b\[[0-9;]*m',b'',log),(n,log)
        finally:os.close(r);os.close(wr)
def main():
    assert os.environ['REVIEWED_HEAD']==os.environ['GITHUB_SHA']and os.environ['GITHUB_RUN_ATTEMPT']=='1'
    assert w.git('rev-parse','HEAD')==b.NEW and w.git('rev-parse','HEAD^')==b.OLD and w.hf(w.src/'sdk.json')==b.SPEC['sdk_manifest'];w.guard();assert shutil.disk_usage(w.root).free>45*2**30
    reg={'run':os.environ['GITHUB_RUN_ID'],'head':os.environ['GITHUB_SHA'],'boot':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
         'source':audit.donor.prepare_source.BASE,'sdk':b.SPEC['sdk_manifest'],'never_reuse':True,'inherited_fds_omitted_zero_thread_fallback':41708042435,'fixed_order':'actual-then-disabled, private 1,2,2,1, traced/explicit/private source 1,2, real-last'}
    b.write(P/'registration.json',reg);b.save_elf=w.hf;env=w.install();state=w.root/'native-donor-state';state.mkdir()
    # Source preparation runs the same checked stock ABI/build as the previously admitted actor.
    audit.prepare_reuse=prepare_groups
    stock,llvm=audit.build(env)
    source=json.loads((H/'group-source-registration.json').read_bytes());assert source['changed']==json.loads((P/'actor.json').read_bytes())['source']and source['parent']==audit.donor.prepare_source.BASE
    audit.calibrate(env,state);warm_calibration(stock,env,state)
    subprocess.run(['cc','-Wall','-Wextra','-Werror','-O2',H.parent/'whole_count.c','-o',w.root/'whole_count'],check=True)
    b.select(b.OLD);b.write(P/'registry.json.gz',b.inputs(env));meta=json.loads(subprocess.check_output(['cargo','+ohm','metadata','--format-version=1','--locked','--offline','--no-deps'],cwd=w.work,env=env));assert len(meta['workspace_default_members'])==55
    results={}
    for tag in ('old','edit'):
        if tag=='edit':
            b.select(b.NEW);assert b.verdict(output,'withheld-old-changed-fixture',env,101)==audit.contact.LITERALS['list']
        (state/'coordinate').touch(exist_ok=False);(state/'stock-reference').touch(exist_ok=False)
        before=set(state.glob('actor-*.tsv'));oldready=set(state.glob('ready-*'));stop=threading.Event()
        try:
            with ThreadPoolExecutor(max_workers=1)as pool:
                control=pool.submit(group_matrix.run,tag,state,stop,stock,llvm,oldready)
                try:inv=b.inventory(tag,env,meta);output=w.root/inv['binary'];assert len(inv['executables'])==102
                finally:stop.set()
                result=control.result()
        finally:
            for path in set(state.glob('actor-*.tsv'))-before:
                (P/tag/('native-'+path.stem+'.tsv.gz')).write_bytes(gzip.compress(path.read_bytes(),mtime=0))
        own=state/result['actor_file'];native=group_matrix.group_rows(own.read_bytes());full=elf_container.inspect(output,llvm)
        b.write(P/(tag+'-ordinary-elf.json.gz'),full)
        idx=next(s for s in full['sections']if s['section']=='.rodata');assert native['available_threads']==result['primary_threads']and native['last_entsize']==idx['header'][9]
        match=[r for r in result['rows'].values()if r['source']=='stock' and r['controlled_threads']==native['available_threads']]
        assert match and all(r['sha256']==full['sha256']for r in match)
        outs={}
        for name,d in result['rows'].items():
            if d['source']=='stock' and d['requested_diagnostic'] is None:
                x=json.loads(gzip.decompress((P/(tag+'-'+name+'-elf.json.gz')).read_bytes()));diff=elf_container.compare(full,x)
                if x['sha256']!=full['sha256']:
                    assert diff['different_section_payloads']==['.note.gnu.build-id']and len(diff['different_section_headers'])==1 and diff['different_section_headers'][0][:2]==('.rodata',9)
                outs[name]=diff
        if tag=='old':assert full['sha256']in ('6d3724468395065d8eb0721eac41893b01e38ffe69eeeb88a59419886ab7a893',audit.contact.LITERALS['old'])
        assert b.verdict(output,tag+'-ordinary-verdict',env,0)==audit.contact.LITERALS['list']
        result.update({'ordinary_sha256':full['sha256'],'ordinary_groups':native,'complete_signed_relations':outs,'isolated_default_members':55,'executables':102});b.write(P/(tag+'-complete.json.gz'),result);results[tag]=result['ordinary_sha256']
        for marker in ('coordinate','stock-reference'):(state/marker).unlink()
        for path in state.glob('local-env-*'):path.unlink()
    b.write(P/'complete.json',results)
if __name__=='__main__':main()
