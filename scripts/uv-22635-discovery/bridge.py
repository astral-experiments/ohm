"""Pin the existing producer, original workload, and independent instruments to a new private dispatch."""
from pathlib import Path
import gzip,hashlib,json,os,subprocess,sys
H=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_bytes())
def guard(f,msg):
    if not f:raise ValueError(msg)
def sha(p):
    with p.open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
P=read(H/'case.json');R=gzip.decompress((H/'signed-reference.json.gz').read_bytes())
guard(sha(H/'signed-reference.json.gz')==P['input_registration_sha256'],'signed reference changed');R=json.loads(R)
def host():
    e=os.environ;w=Path(e['GITHUB_WORKSPACE']).resolve(strict=True);t=Path(e['RUNNER_TEMP']).resolve(strict=True)
    guard(__debug__ and e['GITHUB_REPOSITORY']==P['repo'] and e['GITHUB_EVENT_NAME']=='workflow_dispatch' and e['GITHUB_REF']=='refs/heads/'+P['branch'] and e['GITHUB_SHA']==e['REVIEWED_HEAD'] and e['GITHUB_RUN_ATTEMPT']=='1' and e['GITHUB_WORKFLOW_REF']==P['repo']+'/.github/workflows/ci.yml@'+e['GITHUB_REF'],'private reviewed scope')
    return w,t
def source(repo,rev):
    def git(*a):return subprocess.check_output(['git','-C',repo,*a]).strip()
    guard(git('rev-parse','HEAD').decode()==rev and not git('status','--porcelain','--untracked-files=no'),'source checkout differs: '+str(repo))
def load():
    w,tmp=host();prd=w/'production';source(prd,P['production_coordinator']);source(w/'coordinator',os.environ['REVIEWED_HEAD'])
    old=prd/'scripts/uv-20988-ctfe-hw';sys.path.insert(0,str(old));import material as m
    m.host=host;m.check_sources(w)
    guard(m.P['roles']==P['roles']and m.P['signed_cargo_sha256']==P['cargo_sha256'],'changed 2-role source/Cargo authority')
    src=w/'coordinator/scripts/uv-22635-opening'
    for f,q in P['opening_files'].items():guard(sha(src/f)==q,('changed signed opening',f))
    guard(R['original_signed_admission_line']in(src/'opening.py').read_text()and R['signed_strict_raw_veto']and P['previous_signed_raw_veto_preserved'],'historical raw veto missing')
    guard(os.environ['BUILD_HEAD']==P['production_head']and os.environ['BUILD_RUN_ID']==str(P['build_run'])and os.environ['SDK_LOCK_SHA256']==P['production_lock_sha256'],'wrong production inputs')
    return w,tmp,m,src
def admission():
    w,tmp,m,_=load();import enroll
    sys.argv=[sys.argv[0],'admit'];enroll.main()
def calibration():
    w,tmp,m,_=load();old,_=m.pmu(w,tmp);old.calibrate()
if __name__=='__main__':
    guard(sys.argv[1:]in (['admit'],['calibrate']),'admit | calibrate')
    admission()if sys.argv[1]=='admit'else calibration()
