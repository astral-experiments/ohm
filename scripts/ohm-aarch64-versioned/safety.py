"""Exercise the real GNU linker after edits, provider mutations, and physical Cargo migrations."""
from pathlib import Path
import errno
import json
import os
import sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE));sys.path.insert(0,str(HERE.parent/'ohm-aarch64-fallback'))
import native as parent_study
from native_kits import Selection
from outputs import execs,one_cargo,read_files,opened_depfiles
from version_kit import CHILD,PARENT,rt
from study import save,load,sha
from native import edges,GNU,mutations

OLD='/dev/null/ohm-recheck-dependent-links'
NEW=OLD+'-v2'
HARD='/dev/null/ohm-untracked-relink-inputs'

def verify_native(root,placement,spelling,keys):
    j=load(root/'completed.json');cases={r['name']:r for r in j['cases']}
    assert len(cases)==len(j['cases'])
    results={}
    for phase,row in cases.items():
        folder=root/phase;events=execs(folder/'trace.tar.gz',rt.SDK)
        one_cargo(events,row['argv'])
        chosen=[a for a in events if a.get('crate')==('barrier' if placement=='library' else 'qa_owned_test')]
        assert sum(a['kind']=='ld' for a in events)>=1,phase
        assert any(a['kind']=='collect2' for a in events) and any(a['kind']=='gcc' for a in events)
        if row['markers']:
            for n,(_,__,digest) in row['markers'].items():
                data=(root/'raw-depfiles'/digest).read_bytes()
                if not any(line.endswith(b':') for line in data.splitlines()):
                    assert len(data.splitlines())==1 and spelling.encode() in data.splitlines()[0].split(),(phase,n)
                    continue
                assert any(line==spelling.encode()+b':' for line in data.splitlines()) and not any(line==HARD.encode()+b':' for line in data.splitlines()),(phase,n)
                assert not any(line==(NEW if spelling==OLD else OLD).encode()+b':' for line in data.splitlines())
        if row['exit']==0:assert row['selected'] and row['elf'] and row['answer']
        else:assert row['exit']==101 and row['native_lookup']
        results[phase]={'exit':row['exit'],'answer':row['answer'],'elf':row['elf'],'provider':row['selected'],
                         'compiler_kinds':[a['kind'] for a in chosen], 'kernel_trace':row['trace'],'GNU_linker_count':len(row['actual_GNU_linkers'])}
    for actual,ref in keys:
        x,y=cases[actual],cases[ref]
        assert (x['exit'],x['answer'],x['elf'])==(y['exit'],y['answer'],y['elf']),(actual,ref,x['answer'],y['answer'])
        def selected(v):return {side for side in ('early','late') if any('/'+side+'/' in line for line in v['selected'])}
        assert selected(x)==selected(y),(actual,x['selected'],y['selected'])
        if 'missing' in actual:
            for v in (x,y):
                assert not v['selected'] and all(any('/'+side+'/' in l and ('ENOENT' in l or 'ENOTDIR' in l) for l in v['native_lookup']) for side in ('early','late'))
    return results

def migration(choices,first,next_choice):
    def history(root,cwd,early,late,initial,ar,version,visit):
        rec={}
        def v(n,ref=False): return visit(n,ref)
        def pair(n):
            fixed=v(n);empty=v('empty-'+n,True);rec[n]=[fixed['elf'],empty['elf']]
        pair('trained-repeat')
        original=[(p,p.stat().st_dev,p.stat().st_ino) for p in (cwd,rt.ROOT/'edges-work/target',rt.ROOT/'edges-work/shared')]
        alt=ar(29,early);assert len(initial)==len(alt) and initial!=alt
        choices.choose(next_choice);pair('upgrade-higher');pair('upgrade-unchanged')
        early.unlink();parent_study.overwrite(late,alt);pair('upgrade-restamped')
        choices.choose(first);pair('downgrade-unchanged')
        bad=b'!<arch>\n'+b'\0'*(len(initial)-8)
        parent_study.overwrite(late,bad);pair('downgrade-malformed')
        choices.choose(next_choice);pair('upgrade-malformed')
        late.unlink();pair('upgrade-missing')
        late.write_bytes(initial);version(11);pair('upgrade-repaired')
        choices.choose(first);pair('downgrade-repaired')
        for p,dev,ino in original:assert (p.stat().st_dev,p.stat().st_ino)==(dev,ino)
        save(root/'same-physical-roots.json',{'source_target_shared':[[str(p),d,i] for p,d,i in original],'variants':[first,next_choice,first,next_choice,first],'pairs':rec})
    return history

def main(mode,inputs):
    assert mode in ('signed','classic','aware','migrate-signed','migrate-classic','legacy-writer')
    actual=mode.removeprefix('migrate-') if mode!='legacy-writer' else 'aware'
    is_legacy=mode=='legacy-writer'; selector=Selection(inputs,'P' if is_legacy else 'C')
    edges.BARRIER=GNU;old=edges.BUILD;reports={}
    for watch in (('undeclared',) if mode.startswith('migrate-') or is_legacy else ('undeclared','directories','files')):
        decl={'files':'println!("cargo:rerun-if-changed={n}/libqa_owned_external.a");','directories':'println!("cargo:rerun-if-changed={n}");','undeclared':''}[watch]
        edges.BUILD=old.replace('for n in ["early","late"]{','for n in ["early","late"]{'+decl)
        for placement in ('direct','library'):
            selector.choose(actual)
            label='-'.join((mode,watch,placement));folder=rt.LOG/label;folder.mkdir()
            history=migration(selector,actual,'aware') if mode.startswith('migrate-') else mutations
            def scheme(root,cwd,early,late,initial,ar,version,visit):
                def capture(name):
                    roots=[rt.ROOT/'edges-work'/s for s in ('target','shared')]
                    crate='barrier' if placement=='library' else 'qa_owned_test'
                    raw=read_files(root/name,roots,crate)
                    entries={p:r for p,r in raw.items() if r['kind']=='encoded'}
                    opened=opened_depfiles(root/name/'trace.tar.gz',entries)
                    encoded=[entries[p] for p in opened]
                    if not encoded and len(entries)==1:encoded=list(entries.values())
                    assert encoded,(mode,name,crate)
                    wanted=selector.active=='aware'
                    assert all(f['has_LNK1']==wanted for f in encoded),(mode,name,encoded)
                    if is_legacy:assert all(not f['marker_v2'] for f in encoded)
                    else:assert all(f['marker_v2'] for f in encoded)
                    save(root/name/'actual-dep-info-provenance.json',{'selection':selector.active,'crate':crate,'files':raw,'matched_openat':opened})
                capture('cold-lower')
                def v(name,clean=False):
                    row=visit(name,clean)
                    # edges restores the genuine warm roots before returning from an independent empty visit.
                    if not clean and row['exit']==0:capture(name)
                    return row
                return history(root,cwd,early,late,initial,ar,version,v)
            edges.run(folder,'C',placement,True,history=scheme,rust_source=PARENT if is_legacy else CHILD)
            if mode.startswith('migrate-'):
                records=load(folder/'same-physical-roots.json')['pairs'];keys=[(n,'empty-'+n) for n in records]
                expect={'trained-repeat':'17 7','upgrade-higher':'29 7','upgrade-unchanged':'29 7','upgrade-restamped':'29 7','downgrade-unchanged':'29 7','downgrade-malformed':None,'upgrade-malformed':None,'upgrade-missing':None,'upgrade-repaired':'17 11','downgrade-repaired':'17 11'}
            else:
                keys=parent_study.PAIRS;expect={'higher':'29 7','removed-higher':'17 7','same-inode-value':'29 7','real-Rust-edit':'29 11','same-inode-malformed':None,'repaired-edit':'29 13','missing':None,'restored-edit':'17 19','restored-repeat':'17 19'}
            rows=verify_native(folder,placement,OLD if is_legacy else NEW,keys)
            assert rows['cold-lower']['answer']=='17 7'
            for name,value in expect.items():assert rows[name]['answer']==value and rows[name]['exit']==(101 if value is None else 0),(label,name)
            assert any('/early/' in p for p in rows['upgrade-higher' if mode.startswith('migrate-') else 'higher']['provider'])
            if mode in ('signed','classic'):
                assert 'full_rustc' in rows['restored-repeat']['compiler_kinds'],(mode,placement,rows['restored-repeat'])
            reports[label]={'rows':rows,'terminal':sha(folder/'completed.json')}
    selector.close()
    save(rt.LOG/'versioned-native-terminal.json',{'mode':mode,'compiler':PARENT if is_legacy else CHILD,'sources':selector.versions,'rosters':reports})
if __name__=='__main__':main(sys.argv[1],Path(sys.argv[2]))
