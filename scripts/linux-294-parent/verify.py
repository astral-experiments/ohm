"""Reopen all successful execs, independent emitted bytes, actual provider/loader probes and Cargo verdicts."""
import collections,gzip,hashlib,json,os,re,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import observed
roles=('parent','signed','matched294','combined','defaults-off','stock-cargo')
phases=('warm-absent','settled-absent','insert-83','same-inode-47','same-inode-bad','removed','empty-absent','empty-83','empty-47','empty-bad')
def sha(b):return hashlib.sha256(b).hexdigest()
def gz(p):return gzip.decompress(p.read_bytes())
def jd(p):return json.loads(p.read_bytes())
def same(x,y):assert x==y,(x,y)
def verify(root):
    completed=jd(root/'complete.json');same(set(completed),set(roles))
    proto=jd(root/'protocol.json')
    same('93526150df078af7dd8fc4226cdcc469539d2001',proto['source'])
    same(set(proto['env'])&{'RUSTFLAGS','CC','LIBRARY_PATH','LD_PRELOAD','CARGO_UNSTABLE_OHM_LINKER','CI','GH_TOKEN'},set())
    same(proto['sdk'],['f7663fb7dec7e5c7ea613a85ff1d6e4c00bf97b8c50534f17e5c95cd599712b9',
                       'dae4f8dc64b2b2ac9dc04dfe2cfad633d6af1a87da2dfc532e757ffe758680e3','0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5'])
    same({p.name:sha(p.read_bytes()) for p in (root/'native-fixture').iterdir()},proto['native_sources'])
    same(proto['native_sources']['generator-provider.c'],'6d0b6d6a618c047ab78a894b70aa8cb8a693cde2b1d1ef73e290aec60994f3d4')
    obj={p.stem:gz(p) for p in (root/'objects').glob('*.gz')}
    for h,b in obj.items():same(sha(b),h)
    out={};runtimes=[]
    for role in roles:
        folder=root/role;runtime=jd(folder/'runtime.json');runtimes.append(runtime)
        same(runtime['cargo'],proto['cargo'][role][2]);side=runtime['side'];wild=str(Path(side).with_name('ld.bfd'))
        same(runtime['wild']['sha256'],proto['sdk'][2])
        report=folder/'complete.json';same(sha(report.read_bytes()),completed[role]);records=jd(report)
        rows={x['phase']:x for x in records};same(tuple(rows),phases)
        summary={};checked={}
        for name,row in rows.items():
            d=folder/name;r=jd(d/'observation.json');same(r,row['result']);same(r['command'],runtime['command'])
            trace=gz(d/'exec-and-provider-open.gz')
            same(sha((d/'exec-and-provider-open.gz').read_bytes()),r['trace'])
            again=observed.search(trace,side,wild);same(again,r['search'])
            actual=trace.decode().splitlines()
            rcs=[]
            for l in actual:
                m=re.search(r' execve\("[^"]*/rustc", .*?"--crate-name", "([^"]+)"',l)
                if m and l.endswith('= 0') and m[1]!='___':rcs.append([int(l.split()[1]),m[1]])
            same(sorted(rcs),sorted(r['physical']['rustc']))
            same(sorted(again['physical_ld']),sorted(v[1] for v in r['physical']['ld']))
            rawstdout=gz(d/'cargo.stdout.gz');stderr=gz(d/'cargo.stderr.gz')
            typed=[json.loads(l) for l in rawstdout.splitlines()]
            same(typed[-1],{'reason':'build-finished','success':r['status']==0})
            same(len([t for t in typed if t['reason']=='compiler-artifact']),r['typed'])
            if r['status']==0:
                native=gz(d/'reader-exec.stdout.gz').decode().splitlines();same(native,r['reader'])
                assert obj[r['reader_sha256']].startswith(b'\x7fELF') and len(r['generated'])==3
                alias=obj[r['generated']['generated_alias.rs']]
                encoded,=re.findall(rb'\(b"NULL", .*?\\u\{(\w{4})\}',alias)
                same(native,['Some(%d)'%int(encoded,16),'Some(0)'])
                assert all(v in obj for v in r['generated'].values());value=int(encoded,16)
            else:
                same(r['status'],101);error_msgs=[t for t in typed if t['reason']=='compiler-message' and t['message']['level']=='error']
                assert error_msgs and b'linking' in rawstdout+stderr and b'libutil.so' in rawstdout+stderr
                value=None
            higher=[p for p in again['probes'] if p['kind']=='higher']
            def opens(exe_pred):
                return sorted({p['pid'] for p in higher if p['call'] in ('openat','openat2') and p['result']>=0 and p['exe'] is not None and exe_pred(p['exe'])})
            def gen(p):return 'ruff_unicode_names2' in p and Path(p).name in {'build_script_build','build-script-build'}
            v1=0
            for dep in r['chacha']:
                raw=gz(d/(dep['sha256']+'.d.gz'));same(sha(raw),dep['sha256'])
                words=raw.split();v1+=int(b'/dev/null/ohm-recheck-dependent-links' in words)
                assert b'/dev/null/ohm-recheck-dependent-links-v2' not in words
            summary[name]=dict(status=r['status'],value=value,rustcs=[x[1] for x in r['physical']['rustc']],links=len(r['physical']['ld']),v1_chacha_files=v1,
                               linker_higher_open=opens(lambda e:e==wild),generator_higher_open=opens(gen),higher_enoent_by_wild=sum(p['enoent'] and p['exe']==wild for p in higher),
                               private_wild_exec=sum(p==wild for p in again['physical_ld']),
                               collect2_private_L=sum(Path(p['exe']).name=='collect2' and p['wild_L'] for p in again['build_script_drivers']),
                               cc_private_B=sum(Path(p['exe']).name in ('cc','gcc','clang') and p['wild_B'] for p in again['build_script_drivers']),
                               higher_probes=len(higher),fallback_open_by_wild=sum(p['kind']=='fallback' and p['exe']==wild and p['call'] in ('openat','openat2') and p['result']>=0 for p in again['probes']))
            checked[name]=r
        # Require a real first link, and require independent clean references to agree on
        # whether adding that candidate to this ordinary mode's native search is observable.
        for name in ('warm-absent','empty-absent','empty-83','empty-47','empty-bad'):
            assert summary[name]['links']>=1,(role,name,'no native link')
        same(summary['empty-absent']['value'],0)
        comparable=summary['empty-83']['private_wild_exec']>0 or summary['empty-83']['higher_probes']>0
        if comparable:
            for state in ('83','47'):
                e=summary['empty-'+state];same(e['value'],int(state))
                assert e['collect2_private_L'] and e['cc_private_B'] and e['linker_higher_open'] and e['generator_higher_open'],(role,state,e)
            e=summary['empty-absent'];assert e['higher_enoent_by_wild'] and e['fallback_open_by_wild']
            e=summary['empty-bad'];same(e['status'],101);assert e['linker_higher_open'] and not e['generator_higher_open']
            # Explicit relink decisions may differ; consider only observable same-state parity for the verdict.
        else:
            for e in summary.values():assert not e['private_wild_exec'] and not e['higher_probes'] and not e['collect2_private_L'] and not e['cc_private_B']
            for n in ('empty-83','empty-47','empty-bad'):same(summary[n]['value'],0)
        if role in ('parent','matched294','signed','combined'):
            assert comparable and summary['warm-absent']['v1_chacha_files'] and all(k['v1_chacha_files'] for k in summary.values())
        for name,row in rows.items():
            if name.startswith('empty-'):continue
            u=checked[name];e=checked['empty-'+row['state']]
            keys=('status','reader','reader_sha256','generated')
            parity=all(u.get(k)==e.get(k) for k in keys)
            summary[name]['same_state_empty']=parity
            if u['status']==0:
                refs=[key for key in ('absent','83','47','bad') if all(u.get(k)==checked['empty-'+key].get(k) for k in keys)]
                assert refs,(role,name,'no byte-identical own reader and generated files at any enrolled state')
                summary[name]['clean_identity_matches']=refs
            if name in ('warm-absent','settled-absent','removed'):assert parity,(role,name,e,u)
        for n in ('same-inode-47','same-inode-bad'):
            a=rows['insert-83']['provider'];b=rows[n]['provider']
            same([a[k] for k in ('dev','ino','size','mtime')],[b[k] for k in ('dev','ino','size','mtime')]);assert a['sha256']!=b['sha256']
        out[role]={'head':runtime['descriptor']['head'],'cargo':runtime['cargo'],'shared_native_search':comparable,'visits':summary}
    for key in ('driver','rustc','wild'):
        assert all(r[key]==runtimes[0][key] for r in runtimes)
    return {'roles':out,'shared_physical_runtime':{k:runtimes[0][k] for k in ('driver','rustc','wild')},'native_elf_and_generated_blobs':len(obj),'commands':len(roles)*len(phases)}
if __name__=='__main__':print(json.dumps(verify(Path(sys.argv[1])),sort_keys=True,indent=2))
