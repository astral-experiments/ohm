"""Original scoped Cargo event, artifact, quiet-source registry and inventory helpers."""
from collections import Counter
from pathlib import Path
from urllib.parse import unquote
import collections,gzip,hashlib,json,re,shlex,shutil,subprocess,tomllib
PREFIX='/tmp/uv-workflow-search/'
def commands(raw, rustc):
    # Cargo -vv embeds literal newlines and backticks in quoted package descriptions on a cold build.
    command=None;found=[]
    for line in raw.splitlines():
        if command is None:
            start=re.match(r"^\s*Running `(.*)$",line)
            if not start:continue
            command=start[1]
        else:
            assert not re.match(r"^\s*Running `",line),"unterminated prior Running entry"
            command+="\n"+line
        assert len(command)<1<<20
        if not command.endswith("`"):continue
        try:words=shlex.split(command[:-1])
        except ValueError as err:
            if str(err)=="No closing quotation":continue
            raise
        command=None
        if str(rustc) in words:
            argv=words[words.index(str(rustc)):]
            if "--crate-name" in argv and "--out-dir" in argv and not any(w=="--print" or w.startswith("--print=") for w in argv):
                found.append(argv)
    assert command is None and found
    return found

def events(raw):
    parsed=[]; owners=collections.Counter()
    for line in raw.decode().splitlines():
        if line.startswith("{"):
            row=json.loads(line)
            assert row["reason"] in {"build-started","compiler-artifact","build-script-executed","compiler-message","build-finished"}
            parsed.append(row)
        else:
            m=re.fullmatch(r"\[([^\s\]]+) ([^\s\]]+)\](?: .*)?",line)
            assert m,line[:160]
            owners[m.groups()]+=1
    assert parsed[0]["reason"]=="build-started" and parsed[-1]=={"reason":"build-finished","success":True}
    executed=set()
    for row in parsed:
        if row["reason"]=="build-script-executed":
            base,fragment=row["package_id"].rsplit("#",1)
            executed.add(tuple(fragment.rsplit("@",1)) if "@" in fragment else (unquote(base.rsplit("/",1)[1]),fragment))
    assert set(owners)<=executed,set(owners)-executed
    return parsed,sorted([*k,v] for k,v in owners.items())

def gzip_file(p):
    out=Path(str(p)+".gz")
    with p.open("rb") as src,gzip.open(out,"xb",compresslevel=2) as dest:shutil.copyfileobj(src,dest)
    p.unlink()

def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def identity(row):
    t=row['target'];pkg=row['package_id'];assert pkg.startswith('path+file://'+PREFIX+'uv/crates/')
    assert t['src_path'].startswith(PREFIX+'uv/crates/') and isinstance(row['features'],list)
    return [pkg.split('#',1)[0].rsplit('/',1)[1],t['name'],t['kind'],sorted(row['features'])]

def expected_products(art,gold):
    paths={}
    for row in art:
        if not row['target']['src_path'].startswith(PREFIX+'uv/crates/'):continue
        key=identity(row)
        if key not in gold['typed']:continue
        blob=json.dumps(key,sort_keys=True)
        assert blob not in paths and row['filenames']
        files=sorted(set(row['filenames']))
        assert all(s.startswith(PREFIX+'target/') for s in files)
        paths[blob]=files
    assert len(paths)==len(gold['typed'])
    return paths

def digests(paths):
    value={}
    for label,files in paths.items():
        records=[]
        for raw in files:
            f=Path(raw)
            assert not f.is_symlink() and f.is_file() and f.resolve().is_relative_to(Path(PREFIX+'target'))
            records.append([raw[len(PREFIX+'target/'):],f.stat().st_size,sha(f)])
        value[label]=records
    return value

def package_lines(raw):
    return sorted(s.decode() for s in re.findall(rb"^\s*(?:Checking|Compiling) ([\w-]+) v",raw,re.M))
