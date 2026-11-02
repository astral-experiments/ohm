"""Apply the exact foreign incoherent-impl domain patch to the authenticated f534 source."""
from pathlib import Path
import hashlib,json,os,re,runpy,subprocess,sys,tempfile
HERE=Path(__file__).resolve().parent
ROLE='callables_ctfe318_incoherent_domain'
BASE_ROLE='callables_ctfe318'
EPOCH='compiler/rustc_incremental/src/persist/file_format.rs'
stable=('role','source','component_git','recipe','training_objects','signed_manifest_sha256','released_coordinator','source_pack_sha256','overlay_description_sha256')
def digest(b):return hashlib.sha256(b).hexdigest()
def canon(x):return json.dumps(x,sort_keys=True,separators=(',',':')).encode()
def text(repo,*args):return subprocess.check_output(['git','-C',repo,*args],text=True).strip()
def install(repo,qa,cfg,pack):
    arm=cfg['source'];parent=cfg['parent']
    assert qa['role']==BASE_ROLE and digest(canon({k:qa[k]for k in stable}))==cfg['published_parent_projection_sha256']
    assert [text(repo,'rev-parse',r)for r in ('HEAD','HEAD^{tree}')]==[parent['commit'],parent['tree']]==[arm['parent'],arm['parent_tree']]
    assert qa['source']['epoch']==parent['epoch']==43309 and arm['epoch']==43317
    b=pack.read_bytes();assert len(b)==cfg['pack_bytes'] and digest(b)==cfg['pack_sha256']
    receipt=subprocess.check_output(['git','-C',repo,'index-pack','--strict','--stdin'],input=b).decode().split()[-1];assert receipt==cfg['pack_git_id']
    idx=Path(text(repo,'rev-parse','--absolute-git-dir'))/'objects/pack'/('pack-'+receipt+'.idx')
    packed=sorted(l.split()[0]for l in subprocess.check_output(['git','verify-pack','-v',idx],text=True).splitlines()if re.fullmatch('[0-9a-f]{40}',l.split()[0]))
    rev=arm['commit'];a=parent['commit'];assert text(repo,'rev-list','--parents','-1',rev)==rev+' '+a and text(repo,'rev-parse',rev+'^{tree}')==arm['tree']
    missing=sorted(text(repo,'rev-list','--objects','--no-object-names',rev,'^'+a).splitlines())
    assert missing==packed and len(packed)==len(set(packed))==cfg['pack_objects']==35 and digest(('\n'.join(packed)+'\n').encode())==cfg['objects_sha256']
    delta={r.split('\t')[1]:r.split('\t')[0]for r in text(repo,'diff-tree','--no-commit-id','-r','--name-status','--no-renames',a,rev).splitlines()}
    assert delta==cfg['changes'] and len(delta)==14
    for p,oid in cfg['parent_files'].items():assert text(repo,'rev-parse',a+':'+p)==oid
    for p,oid in {**qa['training_objects'],**arm['ctfe_blob_ids'],**cfg['files']}.items():assert text(repo,'rev-parse',rev+':'+p)==oid
    assert arm['ctfe_blob_ids']==qa['source']['ctfe_blob_ids']|{EPOCH:cfg['files'][EPOCH]}
    text(repo,'checkout','--quiet','--detach','--no-recurse-submodules',rev)
    assert all(text(repo,'hash-object',p)==oid for p,oid in cfg['files'].items())
    assert 'const HEADER_FORMAT_VERSION: u16 = 43317;'in (repo/EPOCH).read_text()
def main(role):
    assert role==ROLE;cfg=json.loads((HERE/'domain-source.json').read_bytes())
    previous=runpy.run_path(str(HERE/'materialize-callable.py'));previous['main'](BASE_ROLE)
    base=runpy.run_path(str(HERE/'materialize.py'));qa,rust,ref=(base[k]for k in('QA','R','REF'));before=json.loads((qa/'source.json').read_bytes())
    install(rust,before,cfg,HERE/'domain-production.pack')
    arm=cfg['source'];rev=arm['commit'];manifest=json.loads((ref/'toolchains/1.99.0/22.json').read_bytes());manifest['sources']['rust']['revision']=rev
    with tempfile.TemporaryDirectory()as tmp:
        root=Path(tmp);(root/'1.99.0').mkdir();(root/'manifest.schema.json').write_bytes((ref/'toolchains/manifest.schema.json').read_bytes())
        m=root/'1.99.0/22.json';base['write'](m,manifest);assert base['assert_sources'](m,rev)==before['component_git']
    (qa/'source.json').rename(qa/'previous-callable-source.json');assert (qa/'previous-production-source.json').is_file()
    after=before|{'role':ROLE,'source':arm,'source_pack_sha256':cfg['pack_sha256'],'overlay_description_sha256':digest((HERE/'domain-source.json').read_bytes()),
                  'previous_callable_source_sha256':digest((qa/'previous-callable-source.json').read_bytes()),'published_parent_source_sha256':cfg['published_parent_source_sha256'],
                  'published_parent_projection_sha256':cfg['published_parent_projection_sha256']}
    base['write'](qa/'source.json',after)
    assert text(rust,'rev-parse','HEAD')==rev and os.environ['REVIEWED_HEAD']==after['reviewed_head']
if __name__=='__main__':main(*sys.argv[1:])
