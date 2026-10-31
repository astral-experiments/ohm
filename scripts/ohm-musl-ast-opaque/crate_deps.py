"""Read the 45 genuine dependency identities from this enrolled native Ruff AST. Decode no other Rust metadata shape."""
import hashlib,re,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from opaque_metadata import Cursor

def require(cond,msg):
    if not cond:raise RuntimeError(str(msg))
def sha(data):return hashlib.sha256(data).hexdigest()
def file_sha(path):
    with Path(path).open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()
def definitions(raw):
    require(raw[:8]==b"rust\0\0\0\n","Rust metadata version")
    root=int.from_bytes(raw[8:16],"little");c=Cursor(raw,root)
    require(c.uint()==0 and c.string()=="x86_64-unknown-linux-musl","AST target")
    hashes=c.take(32).hex()
    require(c.symbol()=="ruff_python_ast" and c.take(2)==b"\0\0","AST owner")
    extra=c.string();stable=c.take(8).hex();c.take(7);last=None
    def array():
        nonlocal last
        n=c.uint()
        if not n:return n,None
        delta=c.uint();last=root-delta if last is None else last+delta
        require(0<last<root,"lazy offset");return n,Cursor(raw,last)
    array();num,d=array();require(20<num<100,"expected target dependencies")
    out=[]
    for _ in range(num):
        n=d.symbol();h=d.take(16).hex();has=d.uint();require(has in (0,1),"optional host hash")
        hh=d.take(16).hex() if has else None;kind=d.uint();suffix=d.string();private=d.uint()
        require(kind<4 and private<2 and re.fullmatch(r"-[0-9a-f]{16}",suffix),"CrateDep wire layout")
        out.append([n,h,hh,kind,suffix,private])
    require(len({(x[0],x[4]) for x in out})==num,"ambiguous crate entry")
    return {"stable":stable,"extra":extra,"declared_hashes":hashes,"items":out}
