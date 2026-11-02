"""Qualify an extra synthetic layout only on the current held source, arguments and extern bytes."""
from pathlib import Path
import gzip,shutil
from basis import CASE,HERE,canon,digest,filehash,read,writez
import fixed_input,semantics

def missing(row,existing):
    """Reject changed typed values before considering any genuine physical repro."""
    if row['accepted']:return {}
    owners=row['unresolved'];allowed=fixed_input.RULE['known_prior_physical_kinds']
    assert owners and not row['changed_sidecars']and not row['ctfe_terminal_only']and row['all_workspace']==39 and row['all_public']==423
    result={}
    for n in owners:
        v=row['changes'][n];w=v['typed'];want=row['needs_fixed_input'][n]
        assert all(w['checks'].values()) and not w['exact_complete_bytes'] and not v['all_semantic_guards_passed']and len(set(v['root_sha256']))==1
        assert v['warm']==w['warm']and v['cold']==w['cold']and set(want)==set(w['physical_moved'])and want and set(want)<=set(allowed[n]) and set(want)-set(existing.get(n,[]))
        result[n]=want
    # A CTFE-only public-root mismatch can be reported alongside an unresolved
    # layout. It must never become eligible when that second owner is replayed.
    for n,v in row['changes'].items():
        assert n in owners or v['all_semantic_guards_passed']
    return result

def reproduce(e,role,state,d,paths,forms,source_forms,prod,oracle,want):
    from session import targetsha,stamps
    assert e.source(state)==CASE['states'][state]['source']and d.parent.is_dir()and not d.exists()
    for owner in want:
        assert len(forms[owner])==1 and forms[owner]==source_forms[owner]and prod['workspace'][owner][0]==paths[owner]
    # Keep all originals at their exact inodes. Only diagnostic clones run
    # through RUSTC_WRAPPER and the four registered thread settings.
    old=e.target.stat();hash_before=targetsha(e.target);mtimes=stamps(e)
    result=fixed_input.certify(e,role,state,d,paths,forms,prod,oracle,want,preserve_original=True)
    after=e.target.stat();assert (old.st_dev,old.st_ino)==(after.st_dev,after.st_ino)and hash_before==targetsha(e.target)and stamps(e)==mtimes and set(result['covered'])==set(want)
    keep={}
    for owner,classes in want.items():
        orig,=forms[owner];baseline=prod['workspace'][owner][1:];cert=result['covered'][owner];assert cert['checked_argv']==orig and cert['held_inputs']==fixed_input.inputs(orig)and cert['rows'] and set(classes)<=set(cert['coverage'])
        assert [r['threads']for r in cert['rows']]==fixed_input.RULE['sequence'] and len({tuple(r['result'])for r in cert['rows']})>=2
        assert all(r['argv']==digest(canon(orig+['-Zthreads='+str(r['threads'])])) and r['inputs']==digest(canon(cert['held_inputs']))for r in cert['rows'])
        assert cert['original_native_header']==digest(fixed_input.native_header(e,e.target/paths[owner]))
        keep[owner]={'source':CASE['states'][state]['source'],'real_baseline':baseline,'forms':digest(canon(orig)),'externs':cert['held_inputs'],'wanted':classes,'proof':cert['coverage']}
    writez(d/'live-input-bounds.json.gz',{'role':role,'state':state,'source':e.source(state),'target_before_and_after':hash_before,'source_mtimes_before_and_after':digest(canon(mtimes)),'restored_original_inode':[old.st_dev,old.st_ino],'owners':keep})
    return result

def qualify(e,role,state,d,paths,forms,source_forms,warm,cold,oracle,cover):
    pre=d/'initial-native-guard';pre.mkdir()
    row=semantics.typed_compare(e,warm,cold,pre,cover)
    if row['accepted']:
        shutil.copyfile(pre/'typed-warm-cold.json.gz',d/'typed-warm-cold.json.gz')
        return row
    owners=row['unresolved']or [n for n,x in row['changes'].items()if not x['all_semantic_guards_passed']]
    request={}
    for owner in owners:
        externs=fixed_input.inputs(forms[owner][0])if len(forms.get(owner,[]))==1 else {}
        request[owner]={'held':warm['workspace'][owner][1:],'cold':cold['workspace'][owner][1:],'externs':externs}
    writez(d/'live-raw-request.json.gz',request)
    for row_inputs in request.values():
        for name,meta in row_inputs['externs'].items():assert semantics.stash(e,Path(name))==meta
    want=missing(row,cover);assert want and set(want)==set(request)
    fd=d/'new-history-fixed';cert=reproduce(e,role,state,fd,paths,forms,source_forms,warm,oracle,want)
    assert read(fd/'forms.json')==forms
    (fd/'forms.json').unlink()  # The preceding real cold-A and edited argv reconstruct these bytes.
    for name in fd.glob('*/argv/*.json'):
        with name.open('rb')as src,name.with_suffix('.json.gz').open('xb')as dst,gzip.GzipFile(fileobj=dst,mode='wb',filename='',mtime=0)as packed:
            shutil.copyfileobj(src,packed)
        name.unlink()
    augmented={**cover,**{n:v['coverage']for n,v in cert['covered'].items()}}
    reread=semantics.typed_compare(e,warm,cold,d,augmented);assert reread['accepted']
    return reread
