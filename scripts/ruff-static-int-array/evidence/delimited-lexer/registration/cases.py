"""Generate deterministic near misses over the actual eligibility and fallback, before C9 observations."""
from pathlib import Path
import hashlib,itertools,json,random
D=Path(__file__).resolve().parent
SEED=0xC809_21231_29261
def build():
 r=random.Random(SEED);items={}
 def put(name,code,edition='2024',kind='classify'):
  s=code.encode('utf-8')
  assert name not in items;items[name]=dict(edition=edition,kind=kind,source=s.hex(),sha256=hashlib.sha256(s).hexdigest())
 def src(payload):
  return '#![allow(text_direction_codepoint_in_literal)]\nextern crate tokenlens;\nmacro_rules! relay { ($e:expr) => { tokenlens::capture!($e) } }\npub const VALUE: () = tokenlens::capture!{ '+payload+' };\npub const INTERPOLATED: () = relay!((1,2,3,4 + 5));\n'
 seeds=['0','1','00','00001','42','9'*31,'8'*32,'7'*33,'15f32','3.0f32','0xF','0b1','0o7','1_024','1u16','1..3','1..=3',
        'r#""#','r#"x"#','r#"x"#field','r#"λ"#','r#"\u202e"#','r#"\u2069"#','r#"—"#','r#"a\x00z"#',
        'r#"x"y"#','r#"a\\"#','r##"x"##','r###"x#\"z"###','r#"ὰ́"#','r"no_hash"','r#ident','r#é','r#async','r#"x"#é','r#"x"#_π',
        'r#"'+'x'*62+'"#','r#"'+'x'*63+'"#','r#"'+'x'*64+'"#','r#"'+'x'*65+'"#','r'+'#'*253+'"x"'+'#'*253,'r'+'#'*255+'"x"'+'#'*255]
 # Grouped arbitrary Rust tokens are lexically valid under a real procedural macro.
 ws=['',' ','\t','\n','\r\n',' '*23,' '*24,' '*25,'\u200e','/*one /*two*/ three*/','// one\r\n','\x0b']
 endings=['',',',', 0', '=> x', '::path', '..=9', ' + -7', '..= (-1)', '[2]', '.field', ' >> 2',' && true']
 pairs=[('(',')'),('[',']'),('{','}')]
 for edition in ('2015','2018','2021','2024'):
  pieces=[]
  for i in range(500):
   v=seeds[i%len(seeds)];w=ws[i%len(ws)];a,b=r.choice(pairs);e=r.choice(endings)
   # A subset of suffix/raw/guarded forms have edition-dependent errors and are isolated below.
   valid=v not in ('r#"x"#field','r#"x"#é','r#"x"#_π') and w not in ('\x0b','\u200e')
   if valid: pieces.append(a+'1,2,'+w+v+e+b)
  put('balanced-'+edition,src(' '.join(pieces)),edition,'required-success')
 dangerous=['r','r#','r##','r#"','r#""','r#"x"', 'r##"x"#','r#"x"##','r#"#"##','r#"bad\rraw"#','r#"a\r\nb"#','r#"'+'x'*65+'"#',
  'r'+'#'*256+'"x"'+'#'*256,'r#1','r#_', 'r#self','r#"x"#suffix','r#"x"#é','r#"x"#\u200d','r##"x"##suf','r#""#_',
  '17e','0b2','0x','0o8','1u8','1_','1f128','00_1','1.foo','1..=2','1\u0301','2π','1e-','1.2u8','1.0.1',
  '1#','##','##""##','###','=>','!==','::','-1','\u00a0','\u202e','\x00','"unterminated','"\\q"','c"\\0"','(1,2]','<','λ','r#await','b"x"','cr#"a"#','r#"\u202a"#']
 for i,(v,edition) in enumerate(itertools.product(dangerous,('2015','2024'))):
  a,b=r.choice(pairs);w=r.choice(ws);e=r.choice(endings)
  put(f'isolated-{i:03}',src(a+'1,2,3,'+w+v+e+b),edition)
 for i in range(160):
  a,b=r.choice(pairs);start=r.choice(seeds);prefix=r.choice(['1,2,3','r#"e"#,r#"e"#','1, r#"λ"#','0x20,12','((-1))'])
  w=r.choice(ws);sep=r.choice([',',',',',',',,','/*m*/ ,','+','=>','.',' :: ','\n,','/','?',';'])
  tail=r.choice([',4',',r#"q"#',']','}','#','//\n','..','/*', 'é', ',(2,3)'])
  put(f'mutation-{i:03}',src(a+prefix+sep+w+start+tail+b),r.choice(['2015','2018','2021','2024']))
 # These choices are actual Rust expressions, requiring the normal parser and type checker.
 for name,literal,kind in [
  ('bidi-denied','r#"abc\u202edef"#','required-error'),('bidi-permitted','r#"abc\u202edef"#','required-success'),
  ('bare-cr','r#"abc\rdef"#','required-error'),('normalized-crlf','r#"a\r\nb"#','required-success'),
  ('invalid-escape','"\\q"','required-error'),('numeric-overflow','260u8','required-error'),('raw-big','#'*256,'required-error'),
  ('powers','(0u32).wrapping_pow(3)','required-success'),('bad-separator','?','required-error')]:
   if name=='raw-big':literal='r'+literal+'"aa"'+literal
   attr='deny' if name=='bidi-denied'else'allow'
   put('typed-'+name,f'#![{attr}(text_direction_codepoint_in_literal)]\nfn main() {{ let _ = (1,2,3,{literal},4); }}\n',kind=kind)
 return items
if __name__=='__main__':
 x=build();(D/'cases.json').write_text(json.dumps(x,indent=2,sort_keys=True)+'\n');print(len(x),hashlib.sha256((D/'cases.json').read_bytes()).hexdigest())
