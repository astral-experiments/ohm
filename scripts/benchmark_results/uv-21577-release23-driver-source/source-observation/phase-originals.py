"""Reopen the unchanged rustc's original pre-ThinLTO selector and its final rust-lld read."""
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile
import hashlib,json,shutil,subprocess,sys
HERE=Path(__file__).resolve().parent
RUNTIME_FILES=("phase.py","read.py","origins.py","lld_open.py")
def read(path):return json.loads(path.read_bytes())
def sha(path):
    with path.open("rb")as f:return hashlib.file_digest(f,"sha256").hexdigest()
def physical(raw,reader,declared):
    sys.path.insert(0,str(reader))
    try:
        import phase,lld_open
        assert Path(phase.__file__).resolve().parent==reader.resolve() and Path(lld_open.__file__).resolve().parent==reader.resolve()
        early=phase.finish(raw/"pre-lto",raw/"capture.json")
        visit,=(raw/"pre-lto").glob("visit-*")
        opened=lld_open.probe(visit,early["lld_pid"])
    finally:sys.path.pop(0)
    assert declared["early"]==early and declared["kernel_lld_read"]==opened
    assert early["target_pid"]!=early["lld_pid"]==opened["pid"] and early["qualified_matches"] and early["protected_inputs"]
    assert any(x["provenance"]["name"]=="blake3"for x in early["proven_foreign"])
    assert declared["after_lto"]["object_count"]>0
    return {"producer_rustc":early["target_pid"],"final_lld":opened["pid"],"source_archives":early["source_rows"],"matches":len(early["qualified_matches"]),"protected":len(early["protected_inputs"]),"late_objects":declared["after_lto"]["object_count"],"closed_exceptions":early["closed_exception_sha256"]}
def from_archive(archive,reader):
    with TemporaryDirectory()as tmp,ZipFile(archive)as z:
        base=Path(tmp);files=[x for x in z.infolist()if not x.is_dir()]
        assert len({x.filename for x in files})==len(files)
        for info in files:
            name=info.filename
            if not name.startswith("driver-witness/")and name not in ("role.json","source-observation.json"):continue
            assert not Path(name).is_absolute() and ".."not in Path(name).parts
            dest=base/name;dest.parent.mkdir(parents=True,exist_ok=True)
            with z.open(info)as src,dest.open("xb")as dst:shutil.copyfileobj(src,dst)
        role=read(base/"role.json");record=base/"source-observation.json";assert role["qa"]["source-observation.json"]==sha(record)
        row=physical(base/"driver-witness",reader,read(record));return {**row,"service_record":sha(record),"qa":sha(archive)}
def retain(folder,admitted,pin):
    source=Path(admitted["qa"]["path"]);assert sha(source)==admitted["qa"]["sha256"] and source.stat().st_size==admitted["qa"]["bytes"]
    folder.mkdir();r=folder/"reader";r.mkdir();k=HERE.parents[4]/"work/ohm-21577-driver-link-production-prelto"
    assert pin==admitted["coordinator"] and subprocess.check_output(["git","-C",k,"rev-parse",pin+"^"],text=True).strip()=="e295118d5a8fd2fbe672d16c28d0df80ff1c2d20"
    for name in RUNTIME_FILES:
        (r/name).write_bytes(subprocess.check_output(["git","-C",k,"show",pin+":scripts/rc23-driver-link/prelto/"+name]))
    shutil.copyfile(source,folder/"original-QA.zip")
    shutil.copyfile(__file__,folder/"phase-originals.py")
    result=from_archive(folder/"original-QA.zip",r)
    certificate={"coordinator":pin,"source":admitted["source_commit"],"run":admitted["run"],"job":admitted["job"],"reader":{p.name:sha(p)for p in r.iterdir()},"actual":result}
    (folder/"observed.json").write_text(json.dumps(certificate,sort_keys=True,indent=1)+"\n");return certificate
def verify(folder):
    proof=read(folder/"observed.json");r=folder/"reader"
    assert proof["reader"]=={s:sha(r/s)for s in RUNTIME_FILES}
    assert from_archive(folder/"original-QA.zip",r)==proof["actual"]
    return proof
if __name__=="__main__":
    if sys.argv[1:]==["rehearse"]:
        m=HERE.parent/"production-source/product-amendment/phase-producer/native-05"
        r=HERE.parents[4]/"work/ohm-21577-driver-link-production-prelto/scripts/rc23-driver-link/prelto"
        print(json.dumps(physical(m/"raw",r,read(m/"accepted.json")["native"]["source_selection_before_lto"]),sort_keys=True))
    elif len(sys.argv)==1:print(json.dumps(verify(HERE),sort_keys=True))

