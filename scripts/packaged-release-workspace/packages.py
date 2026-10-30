"""Install exactly the signed -20 or the actual published -21 release."""
from __future__ import annotations
import argparse,hashlib,json,os,platform,shutil,stat,subprocess,sys,tarfile,time,zipfile
from pathlib import Path

HERE=Path(__file__).resolve().parent
RUN=41088174292
HEAD='6920a42c1f5ab44ccd8b6a3638478acd1b5efaf1'
REPO='astral-experiments/ohm'
CARGO='2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c'
TRIPLES={'Darwin':'aarch64-apple-darwin','Linux':'x86_64-unknown-linux-gnu'}
ASSETS={'aarch64-apple-darwin':(691272613,294960329,'7cd292583785c25a315f67bf85c8f028a15ccb0be5461ac39ce6e46720807bb8',691272609,'406960a6082942c3440db8d61d1882379af52e46c1b3f2378f9b083dd5ace622',691272632,'1c69f4ffadeed83885a4f1b4c5878b912516223b9b061de3f884bd45dc87b060'),'x86_64-unknown-linux-gnu':(691272608,359585079,'edb64a2ee39b2f2951614f98d53ec4e4197f55149ff794c911bd81bc7f870b15',691272611,'31164b6c91d93ee4662b50ae347b1165983fc92521cf6faeb4cd322de2f10ec0',691272634,'1bac589fa5a90d9d9ddcbbc1e847ff2bf8cb500aa58df02b0dd8c2933ceeb15a')}

def need(x,msg):
    if not x:raise RuntimeError(msg)
def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def save(p,data):
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x') as f:json.dump(data,f,indent=2,sort_keys=True);f.write('\n')
def api(path):return json.loads(subprocess.check_output(['gh','api',f'repos/{REPO}/'+path]))
def fetch(path,dest):
    headers=['-H','Accept: application/octet-stream'] if path.startswith('releases/assets/') else []
    need(bool(headers) or path.startswith('actions/artifacts/') and path.endswith('/zip'),'foreign GitHub download route')
    with dest.open('xb') as f:subprocess.run(['gh','api',*headers,f'repos/{REPO}/'+path],stdout=f,check=True)
def platform_triple():
    host=platform.system();t=TRIPLES[host];need((host,platform.machine()) in [('Darwin','arm64'),('Linux','x86_64')],'wrong native host');return t

SIGNED_21 = {
    'aarch64-apple-darwin':(693058656,294965478,'b9514511839ca0dd54e3f473df508c2d43f0dfc27de90ed3926811ed063c7f73',693058650,'b1908108568889e76ebfac2a1c5ee6278ac9e05e7be36b70cf892de36ddb9859',693058683,'ab40362fb3e01c1fdce10ae334617ee5170a7a02dbfd8b0b94acfe5f615e24b0'),
    'x86_64-unknown-linux-gnu':(693058648,359657153,'6f550de85f95440a61b5bd1a9d2ab0528d4fcaf674fdc008f5e986d2138be6c4',693058655,'9986360590836a4b8b7ac76346ac997aa4320ec0183643c175b4b4895d79344d',693058695,'38056225d3f10745209ffc1c011697998f877b4c96ee8bb718b63938d9d00746'),
}
RELEASES={'20':(428741333,'df8ed6cd29c1387ec1e2ba68e00724e23ea60bf8',ASSETS),
          '21':(429373023,HEAD,SIGNED_21)}

def actual_release(role,target,inbox):
    ident,commit,bindings=RELEASES[role];a=bindings[target];tag='ohm-1.99.0-'+role
    base=tag+'-'+target;archive=base+'.tar.gz';prov=base+'-provenance.json'
    catalog=api('releases/tags/'+tag)
    need(catalog['id']==ident and not catalog['draft'] and catalog['tag_name']==tag and catalog['target_commitish']==commit,'foreign official release')
    retained=[]
    for name,id,digest in ((archive,a[0],a[2]),(archive+'.sha256',a[3],a[4]),(prov,a[5],a[6])):
        one,=[r for r in catalog['assets'] if r['id']==id and r['name']==name]
        need(one['digest']=='sha256:'+digest,'different official asset');fetch(f'releases/assets/{id}',inbox/name)
        need(sha(inbox/name)==digest and (inbox/name).stat().st_size==one['size'],'downloaded asset bytes differ')
        retained.append({'id':id,'name':name,'sha256':digest,'bytes':one['size']})
    need((inbox/archive).stat().st_size==a[1],'different original tar size')
    return {'release_id':ident,'tag':tag,'coordinator':commit,'assets':retained}

def prepare(root,role):
    root=root.resolve();root.mkdir(parents=True,exist_ok=True);t=platform_triple();out=root/'receipts'/role;out.mkdir(parents=True,exist_ok=True);inbox=root/('inbox-'+role);inbox.mkdir();need(shutil.disk_usage(root).free>5*2**30,'insufficient workspace storage')
    spec=json.loads((HERE/(role+'.json')).read_bytes());enroll=actual_release(role,t,inbox)
    base=f'ohm-1.99.0-{role}-{t}';archive=inbox/(base+'.tar.gz');provenance=inbox/(base+'-provenance.json');q=json.loads(provenance.read_bytes());need(q['toolchain']==f'ohm-1.99.0-{role}' and q['target']==t and q['manifest']=={'path':f'toolchains/1.99.0/{role}.json','sha256':sha(HERE/(role+'.json'))},'manifest or target mismatch');need(q['sources']=={k:{'revision':v['revision']} for k,v in spec['sources'].items()} and q['sources']['cargo']['revision']==CARGO,'wrong actual sources')
    coordinator='df8ed6cd29c1387ec1e2ba68e00724e23ea60bf8' if role=='20' else HEAD;need(q['coordinator']=={'repository':REPO,'revision':coordinator},'wrong source coordinator')
    need((inbox/(base+'.tar.gz.sha256')).read_text().split()==[sha(archive),archive.name],'distributed tar checksum');need(q['bundled_tools']==(spec['bundled_tools'] if t.startswith('x86') else {}),'wrong packaged native tools')
    save(out/'custody.json',{'source':enroll,'archive_sha256':sha(archive),'bytes':archive.stat().st_size,'provenance':q,'provenance_sha256':sha(provenance)})
    unpack=inbox/'unpack';unpack.mkdir();chosen={'rustc','rust-std-'+t,'cargo'};roots=set()
    with tarfile.open(archive,'r|gz') as a:
        for m in a:
            names=Path(m.name).parts;need(names and not Path(m.name).is_absolute() and '..' not in names,'foreign dist path');roots.add(names[0])
            if len(names)<=2 or names[1] in chosen:a.extract(m,unpack,filter='data')
    top,=roots;d=unpack/top;sdk=root/('sdk-'+role)
    args=[str(d/'install.sh'),'--prefix='+str(sdk),'--disable-ldconfig','--components=rustc,rust-std-'+t+',cargo'];subprocess.run(args,cwd=d,stdout=subprocess.DEVNULL,check=True,timeout=420)
    certified={}
    for relative in ['bin/cargo','bin/rustc']:
        component='cargo' if relative.endswith('cargo') else 'rustc';need(sha(d/component/relative)==sha(sdk/relative),'different installed product');certified[relative]=sha(sdk/relative)
    drivers=list((sdk/'lib').glob('librustc_driver*'));need(len(drivers)==1,'ambiguous driver');certified[str(drivers[0].relative_to(sdk))]=sha(drivers[0]);wild_path=Path('lib/rustlib')/t/'bin/wild-ld/ld.bfd';wild=sdk/wild_path
    need(wild.is_file()==(t=='x86_64-unknown-linux-gnu'),'wrong platform Wild membership')
    if wild.is_file():
        stock=d/'rustc'/wild_path;need(os.access(wild,os.X_OK) and sha(wild)==sha(stock),'Wild differs from original package')
        version=subprocess.check_output([str(wild),'--version'],text=True).strip();need(version=='Wild 0.11.0' or version.startswith('Wild 0.11.0 '),'unexpected bundled Wild');certified[str(wild_path)]=sha(wild);save(out/'wild.json',{'package_member':str(stock.relative_to(d)),'installed':str(wild_path),'sha256':sha(wild),'version':version})
    save(out/'installed.json',certified);shutil.rmtree(inbox)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('role',choices=['20','21']);parser.add_argument('root',type=Path);a=parser.parse_args();prepare(a.root,a.role)
