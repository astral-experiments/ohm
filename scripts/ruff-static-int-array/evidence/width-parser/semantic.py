from pathlib import Path
import hashlib,json,os,subprocess as sp,sys
base=Path(__file__).resolve().parent
src=base/'fixtures';src.mkdir(exist_ok=True)
def put(name,text):
    p=src/name
    if p.exists():assert p.read_text()==text,name
    else:p.write_text(text)
def sha(b):return hashlib.sha256(b).hexdigest()
def digest(p):return sha(p.read_bytes())
put('lens.rs',r'''#![feature(proc_macro_span)]
extern crate proc_macro;
use proc_macro::{Delimiter, Group, TokenStream, TokenTree};
fn field(h: &mut u64, b: &[u8]) {
    for x in b { *h = (*h ^ u64::from(*x)).wrapping_mul(1099511628211); }
    *h = (*h ^ 255).wrapping_mul(1099511628211);
}
fn visit(stream: TokenStream, h:&mut u64, n:&mut usize) {
    for t in stream {
        *n += 1;
        let s=t.span();
        field(h,format!("{}:{}:{}:{}",s.start().line(),s.start().column(),s.end().line(),s.end().column()).as_bytes());
        field(h,s.source_text().unwrap_or_default().as_bytes());
        match t {
            TokenTree::Group(g)=>{field(h, format!("{:?}", g.delimiter()).as_bytes());field(h,g.span_open().source_text().unwrap_or_default().as_bytes());field(h,g.span_close().source_text().unwrap_or_default().as_bytes());visit(g.stream(),h,n);field(h,b"end")},
            TokenTree::Ident(i)=>field(h,i.to_string().as_bytes()),
            TokenTree::Punct(p)=>field(h,format!("{}:{:?}",p.as_char(),p.spacing()).as_bytes()),
            TokenTree::Literal(l)=>field(h,l.to_string().as_bytes()),
        }
    }
}
#[proc_macro]
pub fn lens(input: TokenStream)->TokenStream {
    let (mut h,mut n)=(14695981039346656037u64,0usize);visit(input.clone(),&mut h,&mut n);
    let mut edges:TokenStream=format!("{h}u64,{n}usize,").parse().unwrap();edges.extend(input);
    TokenTree::Group(Group::new(Delimiter::Parenthesis,edges)).into()
}
#[proc_macro_attribute]
pub fn roundtrip(_:TokenStream,input:TokenStream)->TokenStream {input}
#[proc_macro]
pub fn invisible(input:TokenStream)->TokenStream {TokenTree::Group(Group::new(Delimiter::None,input)).into()}
''')
tuples=',\n'.join('(r#"Ḍ̇"#,"D\\u{307}",\'λ\',0xff,0b01)'for _ in range(20))
ints=','.join(str(i)for i in range(32))
singles=','.join('('+str(i)+',)'for i in range(32))
parens=','.join('('+str(i)+')'for i in range(32))
strs=','.join('r##"x # y"##'for _ in range(32))
atoms=','.join(["'a'",r"'\x42'",r"'\u{75}'","'𝓢'"]*8)
positive=r'''#![feature(stmt_expr_attributes)]
#![allow(unused_parens)]
#[allow(unused_macros)] macro_rules! relay { ($e:expr)=>{lens::lens!($e)} }
macro_rules! substitute { ($x:expr)=>{[INTS,$x,]} }
macro_rules! literal_token { ($n:literal)=>{[INTS,$n,]} }
#[cfg(any())]
mod hidden { const UNUSED: [(&str,&str,char,u8,u8);20]=[TUPS,]; const IGNORED: [u8;33]=[INTS,256,]; }
#[lens::roundtrip]
fn main() {
    let (t,n,rows)=relay!([TUPS,]);println!("{t} {n} {:?}",rows[11]);
    let (t,n,array)=relay!([INTS,]);println!("{t} {n} {array:?}");
    let (t,n,array)=relay!([STRS]);println!("{t} {n} {:?}",array[19]);
    let (t,n,array)=relay!([CHARS,]);println!("{t} {n} {array:?}");
    let (t,n,singles)=relay!([SINGLES]);println!("{t} {n} {}",singles[9].0);
    let (t,n,parens)=relay!([PARENS,]);println!("{t} {n} {}",parens[9]);
    let (t,n,array)=relay!([INTS,1+32,33u8,2 << 4,lens::invisible!(4+5),]);println!("{t} {n} {array:?}");
    let (t,n,array)=relay!([INTS, #[cfg(any())] 101,]);println!("{t} {n} {array:?}");
    let (t,n,array)=relay!([INTS].map(|a| a + 1));println!("{t} {n} {}",array[31]);
    let branches=(substitute!(41+1)[32], literal_token!(10u32)[32], [INTS][31]);
    println!("{branches:?}");
}
'''.replace('INTS',ints).replace('TUPS',tuples).replace('STRS',strs).replace('CHARS',atoms).replace('SINGLES',singles).replace('PARENS',parens)
put('positive.rs',positive)
bad={'missing-sep':'8 9','extra-sep':'3,,4','bad-op':'4 +','suffix':'4bad','bad-tuples':'(1 3,4)','postfix':'1.method::','bad-repeat':'4;2','sized-overflow':'256','bad-field':'(1,.3)','attr':'#[cfg( ? )] 4','unclosed':'(3,4]','wrong-brace':'{3,4}'}
for name,tail in bad.items():
    x=f'#![allow(dead_code)]\npub fn value() {{ let _: [u8; 33] = [{ints},{tail}]; }}\n'
    put(name+'.rs',x)
for name,tail in {'disabled-missing':'(r#"x"# r#"y"#,r#"x"#)','disabled-op':'(1, 7 +, 3)','disabled-bad-raw':'r#"no end','disabled-repeat':'; 3','disabled-attr':'#[wrong(] 7'}.items():
    put(name+'.rs',f'#[cfg(any())]\nmod hidden {{ pub fn f() {{ let _ = [{tuples},{tail}]; }} }}\npub fn okay() {{}}\n')
# Restricted runtime checks for unary, repeated array, ranges, interpolation, attrs and postfix.
put('outside.rs',r'''#![allow(unused_parens)]
macro_rules! relay { ($e:expr)=>{lens::lens!($e)} }
fn main() {
    let (a,b,rs)=relay!([RANGES].map(|r| r.end-r.start));println!("{a} {b} {rs:?}");
    let p=([INTS],).0[30] as u64 + 4; let q=[[INTS];2][1][31];println!("{p} {q}");
    let (_a,_b,tr)=relay!([INTS, -2, 3i32.cast_unsigned() as i32]); println!("{}",tr[32]);
}
'''.replace('INTS',ints).replace('RANGES',','.join(f'{i}..{i+1}'for i in range(32))))
def run(role,sdk):
    arm=base/'semantic'/role;arm.mkdir(parents=True,exist_ok=False)
    put('native-input.marker','verbatim source comparison\n')
    env={k:os.environ[k]for k in ('PATH','HOME','LANG','TZ')if k in os.environ};env['RUSTUP_HOME']=str(sdk)
    outputs={}
    def cmd(label,args,expected=0,native=False):
        x=sp.run(args,env=env,cwd=src,capture_output=True);out=arm/(label+'.out');err=arm/(label+'.err')
        out.write_bytes(x.stdout);err.write_bytes(x.stderr)
        assert (x.returncode==0)==(expected==0),(label,x.returncode,x.stderr[-2400:])
        result={'stdout':digest(out),'stderr':digest(err),'exit':x.returncode}
        if expected:
            events=[json.loads(l)for l in x.stderr.splitlines()if l.startswith(b'{')];spans=[(e['message'],[(s['file_name'],s['byte_start'],s['byte_end'])for s in e.get('spans',[])if s['is_primary']])for e in events if e.get('level')=='error' and e.get('spans')]
            assert spans,(label,x.stderr[-1300:]);result['spans']=spans
        outputs[label]=result
    def rust(label,args,expected=0):cmd(label,['rustc','+ohm',*args],expected)
    rust('lens',['--edition=2024','--crate-name','lens','--crate-type','proc-macro','lens.rs','-o',str(arm/'liblens.so')])
    for name in ('positive','outside'):
        args=['--edition=2024','--crate-name',name,name+'.rs','--extern','lens='+str(arm/'liblens.so')]
        for kind in ('ast-tree','expanded','hir,typed'):
            rust(name+'-'+kind,args+['-Zunpretty='+kind])
        rust(name+'-native',args+['-o',str(arm/name)]);cmd(name+'-verdict',[str(arm/name)])
        if name=='positive':assert b'(42, 10, 31)' in (arm/(name+'-verdict.out')).read_bytes()
    for name in sorted(bad|{p.stem:None for p in src.glob('disabled-*.rs')}):
        rust(name,['--edition=2024','--crate-name','syntax',name+'.rs','--crate-type','lib','--emit=metadata','--error-format=json','-o',str(arm/'bad.rmeta')],1)
        assert not (arm/'bad.rmeta').exists()
    record={'role':role,'rustc':sp.check_output(['rustc','+ohm','-vV'],env=env,text=True),'files':{p.name:digest(p)for p in sorted(src.iterdir()) if p.is_file()},'verdicts':outputs,'native':{k:digest(arm/k)for k in ('positive','outside')}}
    (arm/'verified.json').write_text(json.dumps(record,sort_keys=True,indent=2)+'\n');print('guard',role,len(outputs),sha((arm/'verified.json').read_bytes()))
if __name__=='__main__':run(sys.argv[1],Path(sys.argv[2]).resolve())
