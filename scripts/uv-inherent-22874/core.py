"""Private Actions scope and the exact preexisting hardware/read-only SDK authorities."""
import hashlib,json,os,re,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;BASE=HERE.parent/'handwritten-panel';sys.path.insert(0,str(BASE))
import material as m
import deep,scope
P=m.read(HERE/'study.json');ROLES=P['roles'];CHECK=[str(m.SDK/'bin/cargo'),*P['score_commands']]
def guard(v,why):return m.guard(v,why)
def filehash(p):return m.filesha(p)
def host():
    e=os.environ;guard(m.P['branch']in('charlie/codex-20988-handwritten-stage1-check',P['branch']),'upstream cohort scope')
    m.P['branch']=P['branch'];w,tmp=m.host();origin=w/'coordinator'
    raw=m.sha_git(origin,'cat-file','commit','HEAD').split(b'\n\n',1)[0].splitlines()
    guard([v[7:].decode()for v in raw if v.startswith(b'parent ')]==[P['parent']]and m.sha_git(origin,'rev-parse','HEAD').decode().strip()==e['REVIEWED_HEAD'],'direct reviewed child')
    guard(e['GITHUB_REPOSITORY_ID']=='1319437234' and e['BUILD_RUN_ID']==str(P['producer_run'])and e['BUILD_HEAD']==P['producer_head']and e['SDK_LOCK_SHA256']==P['sdk_lock_sha256'],'enrollment')
    gate=m.read(HERE/'provider-gate.json');guard(filehash(HERE/'provider-gate.json')=='d29bf0c3fc8acef7d2652a0d0652194c08349ef1278c2cbb50c7a56bbcb7129c','native control evidence')
    guard([(gate['roles'][r]['actual_impl_shifts'],gate['roles'][r]['actual_public_method_shifts'])for r in ROLES]==[(5,15),(0,0)]and all(gate['roles'][r]['matched_definition_rows']==5509 and gate['roles'][r]['serde_A_and_B']for r in ROLES),'native mechanism')
    return w,tmp
def main():
    w,tmp=host();cmd=sys.argv[1:];guard(len(cmd)==1,'one command')
    if cmd==['calibrate']:
        old,_=m.pmu(w,tmp);old.calibrate()
    elif cmd==['admit']:
        import enroll
        sys.argv[1:]=['admit'];enroll.main()
    elif cmd==['migration']:
        import migration
        migration.run()
    else:raise ValueError(cmd)
if __name__=='__main__':main()
