"""Demand the existing source-native two-way incremental and metadata boundary for the actual selected pair."""
from pathlib import Path
import runpy,subprocess,sys,tempfile
sys.path.insert(0,str(Path(__file__).resolve().parent))
from basis import CASE,HERE,LOCK,Env,filehash,read,write
def qualify(e):
    return qualify_pair(e,read(e.results/'qualification/accepted.json')['control'])
def qualify_pair(e,chosen):
    original=read(HERE/'epoch-kit.json');kit=HERE/'kit/epoch';assert all(filehash(kit/n)==v for n,v in original['files'].items())
    original['roles']={r:{'source':a['source']['commit'],'incremental':a['source']['epoch'],'metadata':a['source']['metadata_epoch']}for r,a in LOCK['roles'].items()}
    roles=(chosen,'F');assert chosen in ('S','R')
    by={r:Path(e.inp['sdks'][r]).resolve()for r in roles};src={original['roles'][r]['source']:by[r]for r in roles};epochs={original['roles'][r]['source']:(original['roles'][r]['incremental'],original['roles'][r]['metadata'])for r in roles};out=e.results/'epoch-native';out.mkdir()
    runpy.run_path(str(kit/'epoch.py'))['run'](by[chosen],by['F'],out/'incremental','actual',expected=[(s,p[0])for s,p in epochs.items()])
    runpy.run_path(str(kit/'metadata_epoch.py'))['metadata'](src,out/'metadata',expected=epochs)
    inc=read(out/'incremental/passed.json');met=read(out/'metadata/passed.json');assert inc['signed_argv_refusal_both_directions']and inc['same_sdk_self_loaded_before_and_after']and inc['reader_compilations']==10 and inc['no_header_edit']and inc['no_compiler_version_override']
    assert met['cross_crate_E0514']==met['own_crate_reads']==met['own_native_typecheck_errors']==2 and not met['file_edits']and not met['compiler_version_overrides']
    res={'roles':list(roles),'runtime':{'P':LOCK['roles'][chosen]['hash'],'T':LOCK['roles']['F']['hash']},'incremental':filehash(out/'incremental/passed.json'),'metadata':filehash(out/'metadata/passed.json'),'registered_source_epochs':epochs,'eligible':True};write(e.results/'compatibility.json',res);return res
if __name__=='__main__':qualify(Env(read(sys.argv[1])))
