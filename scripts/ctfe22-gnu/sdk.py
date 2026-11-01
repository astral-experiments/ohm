"""Extract and verify complete native compiler, std and Cargo manifests. All writes stay inside a new SDK."""
import collections,hashlib,json,os,posixpath,shutil,tarfile,tempfile
from pathlib import Path,PurePosixPath
TARGET="x86_64-unknown-linux-gnu";TARBASE="rust-1.99.0-dev-"+TARGET
COMPONENTS={"rustc","cargo","rust-std-"+TARGET}
def read(p):return json.loads(Path(p).read_bytes())
def sha(p):
 with Path(p).open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()
def save(p,data):
 with Path(p).open("x") as f:json.dump(data,f,sort_keys=True,indent=2);f.write("\n")
def checked(name):
    assert name and "\0" not in name and "\\" not in name and len(name)<4096
    raw=name.rstrip("/").split("/");assert raw and all(v not in {"",".",".."} for v in raw) and not name.startswith("/")
    return PurePosixPath(*raw)
def extract(archive,out):
    sdk=out/"sdk";inv=out/"sdk-inventory.json";record=out/"component-inventory.json"
    if inv.exists():
        assert record.is_file()
        for name,v in read(inv).items():
            p=sdk/checked(name);assert not p.is_symlink() and p.stat().st_size==v["bytes"] and sha(p)==v["sha256"]
        return sdk,inv
    tmp=Path(tempfile.mkdtemp(prefix="native-components.incoming-",dir=out))
    mats={};manifests={};actual=collections.defaultdict(set);meta={};size=count=0
    with tarfile.open(archive,"r|gz") as tar:
        for item in tar:
            path=checked(item.name);parts=path.parts;assert parts[0]==TARBASE
            assert item.isdir() or item.isfile() or item.issym() or item.islnk()
            count+=1;size+=item.size;assert count<180000 and size<8*(1<<30)
            if item.issym() or item.islnk():
                name=item.linkname;assert name and "\0" not in name and "\\" not in name and not name.startswith("/")
                target=PurePosixPath(posixpath.normpath(str(path.parent/name) if item.issym() else name));assert target.parts and target.parts[0]==TARBASE
            if len(parts)==2 and parts[1] in {"version","git-commit-hash","components","rust-installer-version"}:
                assert item.isfile() and item.size<65536
                meta[parts[1]]=tar.extractfile(item).read().decode()
            if len(parts)<3 or parts[1] not in COMPONENTS or item.isdir():continue
            assert item.isfile() and item.size<512*(1<<20);label=parts[1];rel="/".join(parts[2:])
            if rel=="manifest.in":
                assert item.size<1<<20 and label not in manifests
                manifests[label]=tar.extractfile(item).read().decode().splitlines();continue
            dest=tmp/checked(rel);dest.parent.mkdir(parents=True,exist_ok=True);assert rel not in mats
            d=hashlib.sha256();total=0
            with tar.extractfile(item) as src,dest.open("xb") as f:
                while block:=src.read(1<<20):f.write(block);d.update(block);total+=len(block)
            assert total==item.size;mode=0o755 if item.mode&0o111 else 0o644;dest.chmod(mode)
            mats[rel]={"sha256":d.hexdigest(),"bytes":total,"mode":mode,"component":label};actual[label].add(rel)
    assert set(manifests)==COMPONENTS and COMPONENTS<=set(meta["components"].splitlines())
    for comp,lines in manifests.items():assert all(v.startswith("file:") for v in lines) and set(v[5:] for v in lines)==actual[comp]
    assert {"bin/cargo","bin/rustc","bin/rustdoc","lib/rustlib/"+TARGET+"/bin/wild-ld/ld.bfd"}<=set(mats)
    assert any(p.startswith("lib/rustlib/"+TARGET+"/lib/libstd-") for p in mats)
    tmp.rename(sdk);save(record,{"source_component_manifests":manifests,"distribution_metadata":meta,"tar_members_validated":count,"tar_member_bytes":size})
    save(inv,mats);return sdk,inv
