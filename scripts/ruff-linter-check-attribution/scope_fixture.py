"""Exercise visibility, reexports, consts and generic bodies with an actual Cargo and rustdoc."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


def need(ok, why):
    if not ok:
        raise ValueError(why)


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()


def producer(module='outer', access='pub(in crate::outer)', value=11, ty='Small', generic=3, primitive=None, private_scope=False):
    attr='' if primitive is None else f'#[rustc_doc_primitive = "{primitive}"]'
    return f'''#![allow(internal_features, dead_code)]
#![feature(rustc_attrs)]
{"" if private_scope else "pub "}mod {module} {{
    {attr}
    pub const DOCUMENT: () = ();
    pub mod leaf {{
        pub struct Small {{ {access} value: u8 }}
        pub struct Wide(pub u16);
        pub enum Empty {{}}
        pub struct Hidden {{ {access} hidden: Empty }}
        pub fn small() -> Small {{ Small {{ value: 9 }} }}
    }}
    pub fn read(x: &leaf::Small) -> u8 {{ x.value }}
}}
pub use {module}::leaf::{{{ty} as Token, Hidden}};
pub use {module}::{{read, leaf::small}};
pub const CHANGED: u8 = {value};
pub fn generic<T>() -> u8 {{ core::mem::size_of::<T>() as u8 + {generic} }}
'''


RELAY='''#![feature(exhaustive_patterns)]
#[doc(inline)] pub use scope_origin::Token;
#[doc(inline)] pub use scope_origin::Hidden;
pub fn observed<T>() -> u8 { scope_origin::generic::<T>() }
pub fn ordinary() -> u8 { scope_origin::read(&scope_origin::small()) }
'''
MAIN='''fn main() { println!("{} {} {} {}", core::any::type_name::<scope_relay::Token>(), core::mem::size_of::<scope_relay::Token>(), scope_relay::observed::<u8>(), scope_relay::ordinary()); }\n'''


def fixture(sdk, root, output, expected_driver, *, inline_adt=False):
    need(not root.exists() and not output.exists(),'fresh fixture root and receipt')
    root.mkdir(parents=True); sdk=sdk.resolve(strict=True)
    driver,=list((sdk/'lib').glob('librustc_driver-*.so'))
    need(sha(driver)==expected_driver,'different native compiler')
    for sub in ('proxies','rustup/toolchains','home','cargo','temp','work'):
        (root/sub).mkdir(parents=True,exist_ok=True)
    rustup=Path(shutil.which('rustup')).resolve(strict=True)
    for n in ('rustup','cargo','rustc','rustdoc'): (root/'proxies'/n).symlink_to(rustup)
    (root/'rustup/toolchains/ohm').symlink_to(sdk);(root/'rustup/settings.toml').write_text('version = "12"\nprofile = "minimal"\n')
    ws=root/'work';state=root/'state';env=dict(HOME=str(root/'home'),RUSTUP_HOME=str(root/'rustup'),RUSTUP_AUTO_INSTALL='0',PATH=str(root/'proxies')+':/usr/bin:/bin',CARGO_HOME=str(root/'cargo'),CARGO_TARGET_DIR=str(state/'target'),CARGO_BUILD_BUILD_DIR=str(state/'build'),CARGO_BUILD_JOBS='2',CARGO_NET_OFFLINE='true',TMPDIR=str(root/'temp'),LC_ALL='C')
    def cmd(args,code=0):
        available=int(re.search(r'MemAvailable:\s+(\d+) kB',Path('/proc/meminfo').read_text())[1])*1024
        need(available>8*2**30+150*2**20 and shutil.disk_usage(root).free>15*2**30+150*2**20,'fixture reserve')
        p=subprocess.run(args,cwd=ws,env=env,stdin=subprocess.DEVNULL,capture_output=True,timeout=180)
        need(p.returncode==code,(args,p.returncode,code,p.stderr.decode(errors='replace')[-1300:],p.stdout.decode(errors='replace')[-900:]))
        need(b'internal compiler error' not in (p.stdout+p.stderr).lower(),'compiler panic')
        return p
    def cargo(args,code=0):
        p=cmd(['cargo','+ohm',*args,'--offline','--locked','--message-format=json'],code)
        rows=[json.loads(r)for r in p.stdout.splitlines()];need([r['success'] for r in rows if r['reason']=='build-finished']==[code==0],'Cargo terminal verdict')
        return rows
    def write_crate(name,body,file,deps=''):
        folder=ws/name; (folder/'src').mkdir(parents=True)
        (folder/'Cargo.toml').write_text(f'[package]\nname="{name}"\nversion="0.0.0"\nedition="2024"\n'+deps)
        (folder/'src'/file).write_text(body)
    (ws/'Cargo.toml').write_text('[workspace]\nmembers=["scope_origin","scope_relay","scope_view","scope_direct"]\nresolver="3"\n')
    write_crate('scope_origin',producer(),'lib.rs')
    write_crate('scope_relay',RELAY,'lib.rs','[dependencies]\nscope_origin={path="../scope_origin"}\n')
    write_crate('scope_view',MAIN,'main.rs','[dependencies]\nscope_relay={path="../scope_relay"}\n')
    write_crate('scope_direct','fn main(){println!("{}",scope_origin::CHANGED);}\n','main.rs','[dependencies]\nscope_origin={path="../scope_origin"}\n')
    proper=cmd(['rustc','+ohm','--print','sysroot']).stdout.decode().strip()
    need(Path(proper).resolve()==sdk,'rustup selected a different SDK')
    compiler=cmd(['rustc','+ohm','-vV']).stdout.decode(); cmd(['cargo','+ohm','generate-lockfile','--offline'])
    origin=ws/'scope_origin/src/lib.rs';relay=ws/'scope_relay/src/lib.rs'
    def state_output(label, cfg):
        checked=cargo(['check','-p','scope_view']); art=[(r['target']['name'],r['fresh']) for r in checked if r['reason']=='compiler-artifact']
        need(sorted(x[0] for x in art)==['scope_origin','scope_relay','scope_view'],'unexpected dependency path')
        built=cargo(['build','-p','scope_view','-p','scope_direct'])
        bins={r['target']['name']:Path(r['executable'])for r in built if r['reason']=='compiler-artifact' and r.get('executable')};need(set(bins)=={'scope_view','scope_direct'},'wrong binary roster')
        actual={k:cmd([str(v)]).stdout.decode().strip()for k,v in bins.items()}
        module=cfg.get('module','outer');ty=cfg.get('ty','Small');size=1 if ty=='Small' else 2
        want={'scope_view':f'scope_origin::{module}::leaf::{ty} {size} {cfg.get("generic",3)+1} 9','scope_direct':str(cfg.get('value',11))}
        need(actual==want,('wrong real execution',label,actual,want))
        documents={}
        for package in ('scope_origin','scope_relay'):
            cmd(['cargo','+ohm','rustdoc','--locked','--offline','-p',package,'--lib','--','-Zunstable-options','--output-format','json','--document-private-items'])
            candidates=list((state/'target').rglob(package+'.json'));need(len(candidates)==1,('rustdoc output',candidates));doc=json.loads(candidates[0].read_bytes());need(doc.get('index') and doc.get('paths'), 'empty actual rustdoc json')
            fields=[dict(name=q['name'],visibility=q['visibility'])for q in doc['index'].values()if 'struct_field' in q['inner'] and q.get('name') in ('value','hidden')]
            if package=='scope_origin' and cfg.get('primitive') is None:
                need({q['name']for q in fields}=={'hidden','value'},('documented actual fields',fields))
                values=[q['visibility']for q in fields]
                if cfg.get('access')=='pub(crate)':need(values==['crate','crate'],('actual crate visibility',values))
                else:need(all(isinstance(v,dict) and 'restricted' in v and v['restricted']['path'].split('::')[-1]==module for v in values),('actual named scope rendering',values,module))
            documents[package]=dict(sha256=hashlib.sha256(json.dumps(doc,sort_keys=True,separators=(',',':')).encode()).hexdigest(),items=len(doc['index']),fields=fields)
        return dict(checked=art,executables={k:sha(v)for k,v in bins.items()},output=actual,rustdoc_json=documents)
    configs=[('original',{}),('unrelated-export',{'value':29}),('crate-visibility',{'value':29,'access':'pub(crate)'}),('crate-unrelated',{'value':35,'access':'pub(crate)'}),('reexport',{'ty':'Wide'}),('generic',{'ty':'Wide','generic':17}),('scope-parent',{'module':'moved','access':'pub(in crate::moved)'}),('private-scope',{'private_scope':True}),('primitive-u8',{'private_scope':True,'primitive':'u8'}),('primitive-u16',{'private_scope':True,'primitive':'u16'})]
    out={}
    partial=output.parent/(output.stem+'-partial');partial.mkdir()
    for name,cfg in configs:
        origin.write_text(producer(**cfg));warm=state_output(name,cfg)
        (partial/(name+'-warm.json')).write_text(json.dumps(warm,sort_keys=True)+'\n')
        saved=root/'previous-state';need(not saved.exists() and state.is_dir() and not state.is_symlink(),'private state');state.rename(saved)
        empty=state_output(name,cfg)
        (partial/(name+'-empty.json')).write_text(json.dumps(empty,sort_keys=True)+'\n')
        need(all(warm[k]==empty[k]for k in ('output','rustdoc_json','executables')),('independent native or rustdoc result',name,warm,empty))
        shutil.rmtree(state);saved.rename(state);out[name]=dict(warm=warm,fresh=empty)
    origin.write_text(producer());relay.write_text(RELAY+'pub fn read_private() -> u8 { scope_origin::small().value }\n')
    errors=cargo(['check','-p','scope_view'],101);codes=lambda rs:[(r['message'].get('code')or{}).get('code')for r in rs if r['reason']=='compiler-message' and r['message']['level']=='error']
    need('E0616' in codes(errors),'missing private-field diagnostic')
    origin.write_text(producer(access='pub'));cargo(['check','-p','scope_view'])
    origin.write_text(producer(private_scope=True));relay.write_text(RELAY+'pub fn exhaust(x: scope_origin::Hidden) -> u8 { match x {} }\n')
    opaque=cargo(['check','-p','scope_view'],101);need('E0004' in codes(opaque),'downstream must respect private uninhabited field')
    origin.write_text(producer(access='pub',private_scope=True));cargo(['check','-p','scope_view'])
    relay.write_text(RELAY+'pub const BAD: u8="bad";\n');errors2=cargo(['check','-p','scope_view'],101);need('E0308' in codes(errors2),'missing type-mismatch diagnostic')
    relay.write_text(RELAY)
    origin.write_text(producer().replace('pub mod outer', '#[rustc_doc_primitive = "u8"]\npub mod outer'))
    primitive_bad=cargo(['check','-p','scope_view'],101)
    attr_errors=[r['message']['message']for r in primitive_bad if r['reason']=='compiler-message'and r['message']['level']=='error']
    need(any('cannot be used on modules' in e for e in attr_errors),'invalid module primitive accepted')
    origin.write_text(producer());relay.write_text(RELAY);repaired=state_output('repair',{});need(all(repaired[k]==out['original']['fresh'][k]for k in ('output','executables','rustdoc_json')),'stale repair')
    result=dict(driver=expected_driver,compiler=compiler,states=out,private=codes(errors),opaque=codes(opaque),invalid_module_attribute=attr_errors,type_error=codes(errors2),repair=repaired)
    if inline_adt:
        from scope_adt_traits import verify
        result['exact_size_iterator'] = verify(root, ws, state, origin, relay, producer, cargo, cmd, codes)
    output.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n');print('Verified actual visibility/value/generic/reexport/rustdoc states, private+type errors and repair',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('sdk',type=Path);p.add_argument('root',type=Path);p.add_argument('output',type=Path);p.add_argument('driver');a=p.parse_args();fixture(a.sdk,a.root,a.output,a.driver)
