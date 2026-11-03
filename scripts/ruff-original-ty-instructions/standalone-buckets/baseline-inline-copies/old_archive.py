"""Read all original signed -22 Rust members by their complete stable names."""
import re
from census import need as require

def iter_archive(body, owner):
    # Browsable/piped library hash is checked by the caller. ELF data remain zero-copy here.
    v = memoryview(body); table = b""; seen = set(); at = 8
    require(v[:8] == b"!<arch>\n", "invalid archive")
    while at < len(v):
        header = bytes(v[at:at+60]); require(len(header)==60 and header[-2:]==b"\x60\n","ar header")
        length=int(header[48:58].strip()); name=header[:16].decode("ascii").rstrip()
        first=at+60; end=first+length
        require(length>=0 and end<=len(v),"ar extent"); at=end+length%2
        piece=v[first:end]
        if name=="//":
            require(not table,"duplicate strings"); table=bytes(piece); continue
        if name in ("/","/SYM64/"):
            continue
        if name.startswith("/") and name[1:].isdigit():
            begin=int(name[1:]); end_name=table.find(b"/\n",begin)
            require(0<=begin<end_name,"string table member"); name=table[begin:end_name].decode("ascii")
        elif name.startswith("#1/"):
            count=int(name[3:]); require(0<count<len(piece),"BSD name"); name=bytes(piece[:count]).rstrip(b"\0").decode("ascii");piece=piece[count:]
        else:
            name=name.removesuffix("/")
        require(name not in seen,"duplicate ar member");seen.add(name)
        if name in ("lib.rmeta","lib.rmeta-link"):
            continue
        match=re.fullmatch(re.escape(owner)+r"-([a-f0-9]{16})\.([a-z0-9]{25})(?:\.[a-z0-9]{7})?\.rcgu\.o",name)
        require(match,("unexpected native member",name))
        yield ".".join((owner,match[1],match[2])),piece
    require(at==len(v) and "lib.rmeta" in seen,"incomplete native archive")
