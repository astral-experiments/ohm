"""Keep the full v0 byte grammar; translate only the crate-domain root and absolute backref offsets."""
from collections import defaultdict
from pathlib import Path
import hashlib
import json
import subprocess
import tarfile

HERE=Path(__file__).resolve().parent
CRATE="b74b56ffa8bb2830709a538c2cbcae9aa062db0d2a42563bfb09bdaae44020eb"
SOURCE="ed9fe5f8357a1142ebe74555c64dd67d57009b15d17814705322b9ed7b95575d"
def sha(p):
    with Path(p).open("rb") as f: return hashlib.file_digest(f,"sha256").hexdigest()
def build(rustc,crate,target):
    assert sha(crate)==CRATE
    with tarfile.open(crate) as t:
        member,=[x for x in t if x.name=="rustc-demangle-0.1.28/src/v0.rs"]
        assert member.isfile();src=t.extractfile(member).read()
    assert hashlib.sha256(src).hexdigest()==SOURCE
    src=src.decode();target.mkdir(parents=True,exist_ok=True)
    # Observe the two native grammar branches, including skipped impl paths and instantiating crate.
    old="""                let dis = parse!(self, disambiguator);
                let name = parse!(self, ident);

                self.print(name)?;"""
    new="""                let start = self.parser.as_ref().unwrap().next - 1;
                let dis = parse!(self, disambiguator);
                let end = self.parser.as_ref().unwrap().next;
                let name = parse!(self, ident);
                crate::crate_domain(start, end, dis, name.to_string());

                self.print(name)?;"""
    assert src.count(old)==1;src=src.replace(old,new)
    old="""        let mut new_parser = Parser {
            sym: self.sym,
            next: i as usize,"""
    new="""        crate::back_reference(s_start, self.next, i as usize);
        let mut new_parser = Parser {
            sym: self.sym,
            next: i as usize,"""
    assert src.count(old)==1;src=src.replace(old,new)
    for sig in ("fn print_path(&mut self, in_value: bool) -> fmt::Result {","fn print_type(&mut self) -> fmt::Result {","fn print_const(&mut self, in_value: bool) -> fmt::Result {"):
        assert src.count(sig)==1
        src=src.replace(sig,sig+"\n        if let Ok(ref p) = self.parser { crate::anchor(p.next); }")
    (target/"v0.rs").write_text(src)
    (target/"trace.rs").write_bytes((HERE/"trace.rs").read_bytes())
    prog=target/"trace"
    subprocess.run([str(rustc),"--edition=2021","-Awarnings","-O",str(target/"trace.rs"),"-o",str(prog)],check=True)
    return prog

def number(s):
    """Decode the canonical Rust-v0 base-62 number, including the implicit +1."""
    digits="0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    assert s.endswith("_")
    if s=="_":return 0
    n=0
    for c in s[:-1]:n=n*62+digits.index(c)
    return n+1

def parsed(name,event_line):
    if event_line=="!":return None
    assert name.startswith("_R") and name.isascii()
    src=name[2:];wire=[];offset={};origins=[];last=0
    # A tuple token is a complete grammar directive, disjoint from each ordinary byte.
    for raw in event_line.split(";"):
        what,a,b,*fields=raw.split(",");a,b=int(a),int(b)
        assert last<=a<b<=len(src)
        for i in range(last,a):offset[i]=len(wire);wire.append(src[i])
        offset[a]=len(wire)
        if what=="c":
            d,crate=fields;d=int(d)
            assert src[a]=="C" and ((b==a+1 and d==0) or (src[a+1]=="s" and number(src[a+2:b])+1==d))
            assert crate
            origins.append((crate,d));wire.append(("crate",))
        else:
            assert what=="b" and len(fields)==1 and src[a]=="B"
            pos=int(fields[0]);assert pos==number(src[a+1:b]) and pos in offset and pos<a
            wire.append(("backref",offset[pos]))
        last=b
    for i in range(last,len(src)):wire.append(src[i])
    assert origins
    return tuple(wire),tuple(origins)

def index(names,prog):
    v0=sorted({n for n in names if n.startswith("_R")})
    out=subprocess.run([prog],input="\n".join(v0)+"\n",text=True,stdout=subprocess.PIPE,check=True).stdout.splitlines()
    assert len(v0)==len(out)
    by_name={};domains=defaultdict(set)
    for n,e in zip(v0,out):
        result=parsed(n,e)
        if result is not None:
            wire,origins=result
            for crate,dis in origins:domains[crate].add(dis)
            by_name[n]=(wire,{k for k,_ in origins})
    by_wire=defaultdict(list)
    for n,(wire,_) in by_name.items():by_wire[wire].append(n)
    return by_name,by_wire,domains

def join(left,right):
    """Demand unique full structural names and unique observed crate instances on both inputs."""
    l,w,d=left;r,x,e=right
    dual={k for k in d.keys()&e.keys() if len(d[k])==len(e[k])==1}
    matches={}
    for a,(wire,crates) in l.items():
        if len(w[wire])==1 and len(x.get(wire,()))==1 and crates<=dual:
            b=x[wire][0]
            assert crates==r[b][1];matches[a]=b
    assert len(set(matches.values()))==len(matches)
    return matches
