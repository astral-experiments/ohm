"""Offline custody controls. Synthetic bytes exercise format gates, never source enrollment."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
import uuid
import warnings
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kit
import media
import task_dir

HASH = "1" * 64
HEAD = "2" * 40


def official_rows():
    repo = {"id": 1319437234, "full_name": kit.REPO, "private": True}
    run = {"id": 52, "path": ".github/workflows/ci.yml", "run_attempt": 1, "head_branch": media.BRANCH,
           "head_sha": HEAD, "workflow_id": 325165136, "event": "workflow_dispatch", "repository": repo, "head_repository": repo}
    steps = [{"name": n, "number": i, "status": "completed", "conclusion": "success"} for i, n in enumerate(media.STEPS, 1)]
    jobs = {"total_count": 1, "jobs": [{"id": 53, "name": "Native SDK (" + kit.TRIPLE + ")", "head_sha": HEAD,
            "run_id": 52, "run_attempt": 1, "conclusion": "success", "status": "completed", "steps": steps}]}
    artifact = {"id": 54, "name": media.ARTIFACT, "expired": False, "size_in_bytes": 100, "digest": "sha256:" + HASH,
                "workflow_run": {"id": 52, "head_sha": HEAD, "repository_id": repo["id"],
                                 "head_repository_id": repo["id"], "head_branch": media.BRANCH}}
    return [repo, run, jobs, {"total_count": 1, "artifacts": [artifact]}]


def fixture_reg():
    def version(commit):
        return "commit-hash: " + commit + "\nhost: " + kit.TRIPLE + "\nrelease: 1.99.0-dev"
    rust = {"commit": kit.RUST[0], "tree": kit.RUST[1], "host": kit.TRIPLE, "rustc_path": "sdk/bin/rustc",
            "driver_path": "sdk/lib/librustc_driver-aabb.so", "driver_sha256": HASH, "rustc_sha256": HASH,
            "version_verbose": version(kit.RUST[0]), "rustdoc_verbose": version(kit.RUST[0]), "rustdoc_sha256": HASH,
            "bootstrap": ["/usr/bin/python3", *kit.BOOTSTRAP], "subtrees": kit.RUST_TREES.copy()}
    qa = {"GITHUB_REPOSITORY": kit.REPO, "GITHUB_SHA": HEAD, "GITHUB_RUN_ID": "52", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_JOB": "sdk"}
    cargos = {}
    for i, (role, (commit, tree)) in enumerate(kit.CARGO.items()):
        cargos[role] = {"commit": commit, "tree": tree, "path": f"roles/{role}/cargo", "sha256": str(i+1)*64,
                        "release_channel": "dev", "version_verbose": version(commit), "features": ["all-static", "ohm-defaults"],
                        "command": ["cargo","+ohm","-Zohm-defaults=no","build","--release","--offline","--locked","-p",
                                    "cargo","--bin","cargo","--features","all-static,ohm-defaults","-j8","--message-format=json"]}
    receipt = {"schema": 1, "qa": qa, "rust": rust, "cargos": cargos,
               "source_qualification": "source-built native stage1; Cargo release profile with no distribution PGO",
               "native_linkers": [{"kind": "bundled-wild", "path": kit.LD, "sha256": kit.WILD, "source_archive": kit.DISTRIBUTED_21, "version": "Wild 0.11.0"}]}
    index = {}
    for n in ("sdk/bin/rustc","sdk/bin/rustdoc","sdk/bin/cargo",rust["driver_path"],"sdk/"+kit.LD,
              "roles/pinned/cargo","roles/fourfix/cargo"):
        index[n] = {"bytes": 30, "mode": 0o755, "sha256": HASH}
    index["roles/fourfix/cargo"]["sha256"] = cargos["fourfix"]["sha256"]
    index["sdk/"+kit.LD]["sha256"] = kit.WILD
    for n in ("core", "std", "alloc", "proc_macro", "test"):
        index[f"sdk/lib/rustlib/{kit.TRIPLE}/lib/lib{n}-abcd.rlib"] = {"bytes": 1, "mode": 0o644, "sha256": HASH}
    return receipt, index


class Carrier(unittest.TestCase):
    def test_source_custody(self):
        a = official_rows()
        result = media.catalog(*a, HEAD, 52)
        self.assertEqual((result["job"], result["artifact"]["id"]), (53, 54))
        bad = [
            (0, ("private",), False), (1, ("event",), "pull_request"), (1, ("run_attempt",), 2),
            (1, ("head_sha",), "3"*40), (1, ("workflow_id",), 17), (1, ("head_branch",), "main"),
            (2, ("jobs",0,"name"), "Native SDK (aarch64-apple-darwin)"), (2, ("jobs",0,"run_id"), 51),
            (2, ("jobs",0,"conclusion"), "failure"), (2, ("jobs",0,"steps",0,"conclusion"), "skipped"),
            (2, ("jobs",0,"steps",2,"number"), 1), (3, ("total_count",), 2),
            (3, ("artifacts",0,"expired"), True), (3, ("artifacts",0,"digest"), "sha256:"),
            (3, ("artifacts",0,"workflow_run","head_repository_id"), 11)]
        for section, keys, value in bad:
            with self.subTest(keys=keys):
                b = copy.deepcopy(a)
                node = b[section]
                for key in keys[:-1]:
                    node = node[key]
                node[keys[-1]] = value
                with self.assertRaises(ValueError):
                    media.catalog(*b, HEAD, 52)

    def test_runtime_registration(self):
        raw, index = fixture_reg()
        a = {"source_head": HEAD, "run": 52}
        reg, hashes = kit.registration(raw, index, a)
        self.assertEqual(reg["fixed"]["source"], kit.CARGO["fourfix"][0])
        self.assertEqual(len(hashes), 7)
        for field, keys, value in [
                ("r", ("qa", "GITHUB_RUN_ATTEMPT"), "2"), ("r", ("qa","GITHUB_JOB"), "marker"),
                ("r", ("rust","host"), "aarch64-apple-darwin"), ("r", ("cargos","pinned","features"), ["ohm-defaults"]),
                ("r", ("cargos","fourfix","tree"), kit.CARGO["pinned"][1]), ("r", ("rust","tree"), HEAD), ("r", ("rust","bootstrap"), []),
                ("r", ("rust","subtrees","compiler"), HEAD), ("r", ("native_linkers",0,"source_archive"),HASH),
                ("r", ("native_linkers",0,"sha256"), "f"*64), ("r", ("cargos","pinned","command"), ["cargo","build"]),
                ("i", ("sdk/bin/cargo","sha256"), "f"*64), ("i", ("sdk/bin/rustc","mode"), 0o4755)]:
            with self.subTest(keys=keys):
                b = copy.deepcopy((raw,index))
                node = b[0 if field == "r" else 1]
                for key in keys[:-1]:
                    node = node[key]
                node[keys[-1]] = value
                with self.assertRaises(ValueError):
                    kit.registration(*b, a)
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/"anchor.json";p.write_text("null\n")
            with self.assertRaisesRegex(ValueError, "no source-complete"):
                media.checked_anchor(p)
        with self.assertRaises(ValueError):
            kit.strict_json('{"mode":1,"mode":2}')

    def test_tar_boundary(self):
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp)
            name="sdk/bin/cargo"
            index={name: {"sha256":hashlib.sha256(b"q").hexdigest(),"bytes":1,"mode":0o755}}
            def zip_tar(entries, tail=b""):
                buf=io.BytesIO()
                with tarfile.open(fileobj=buf,mode="w:") as ar:
                    for path,kind,mode in entries:
                        i=tarfile.TarInfo(path); i.type=kind; i.mode=mode
                        if kind==tarfile.REGTYPE:
                            i.size=1; ar.addfile(i,io.BytesIO(b"q"))
                        else:
                            i.linkname="../outside";ar.addfile(i)
                pack=d/"object.tar.zst"
                pack.write_bytes(subprocess.check_output(["zstd","-q","-c"],input=buf.getvalue()+tail))
                return pack
            def verify(pack):
                with pack.open("rb") as f:
                    kit.validate_tar(f,index)
            good=(name,tarfile.REGTYPE,0o755)
            verify(zip_tar([good]))
            for description, rows, tail in [
                    ("missing",[],b""), ("duplicate",[good,good],b""), ("traversal",[("../bin/cargo",tarfile.REGTYPE,0o755)],b""),
                    ("symlink",[(name,tarfile.SYMTYPE,0o755)],b""), ("hardlink",[(name,tarfile.LNKTYPE,0o755)],b""),
                    ("mode",[(name,tarfile.REGTYPE,0o4755)],b""), ("post-tar",[good],b"x"*512),
                    ("decompression-envelope",[good],b"\0"*(2<<20))]:
                with self.subTest(description=description), self.assertRaises(ValueError):
                    verify(zip_tar(rows,tail))
            for bad in ("roles/concealed", "sdk/../bin/cargo", "/sdk/x", "sdk//x", "sdk/./x"):
                with self.subTest(name=bad), self.assertRaises(ValueError):
                    kit.inventory({bad: index[name]})

    def test_zip_and_physical_elf(self):
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp); raw=d/"src.zip"
            values={n:b"input" for n in kit.ZIP_LIMITS}
            def archive(names, count):
                with zipfile.ZipFile(raw, "w") as z, warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    for n in names:
                        z.writestr(n,b"input")
                return {"size":raw.stat().st_size,"sha256":kit.checksum(raw)}, d/f"out{count}"
            a,dest=archive(values,0);kit.unzip(raw,dest,a)
            self.assertEqual({p.name:p.read_bytes() for p in dest.iterdir()},values)
            a["sha256"]="0"*64
            with self.assertRaises(ValueError):
                kit.unzip(raw,d/"replaced",a)
            for i,entries in enumerate((["receipt.json"], [*values,"../outside"],[*values,"kit.tar.zst"])):
                a,dest=archive(entries,i+1)
                with self.assertRaises(ValueError):
                    kit.unzip(raw,dest,a)
            elf=Path("/bin/true").resolve();kit.native_elf(elf)
            data=elf.read_bytes()
            for i,mut in enumerate((b"\xcf\xfa\xed\xfe"+data[4:],data[:18]+b"\xb7\0"+data[20:])):
                p=d/f"foreign{i}";p.write_bytes(mut)
                with self.assertRaises(ValueError):
                    kit.native_elf(p)

    def test_owned_ext4_directory_boundary(self):
        with tempfile.TemporaryDirectory() as temp:
            top = Path(temp).resolve()
            name = top / "ohm-rc22-recovery-52-1-aBCDEf23"
            name.mkdir(mode=0o700)
            nonce = str(uuid.uuid4())
            claim = task_dir.handle("claim",name,"",nonce,top,52,1)
            with self.assertRaises(ValueError):
                task_dir.handle("claim",name,"",nonce,top,52,1)
            case = name/"rc22-regression"; case.mkdir()
            sentinel = top/"unrelated"; sentinel.write_bytes(b"owned elsewhere")
            (case/"outside-link").symlink_to(sentinel)
            (name/"unknown").write_text("must survive")
            with self.assertRaises(ValueError):
                task_dir.handle("drop",name,claim,nonce,top,52,1)
            (name/"unknown").unlink()
            for identity,token in (("wrong",nonce),(claim,str(uuid.uuid4()))):
                with self.assertRaises(ValueError):
                    task_dir.handle("drop",name,identity,token,top,52,1)
            working = top/"preserved-case"
            case.rename(working)
            case.symlink_to(top, target_is_directory=True)
            with self.assertRaises(ValueError):
                task_dir.handle("drop",name,claim,nonce,top,52,1)
            case.unlink()
            working.rename(case)
            self.assertEqual(task_dir.handle("drop",name,claim,nonce,top,52,1),claim)
            self.assertEqual(list(name.iterdir()),[])
            self.assertEqual(sentinel.read_bytes(),b"owned elsewhere")

    @unittest.skipUnless(os.environ.get("RC22_TEST_SOURCE"), "optional source checkout for actual decoder calibration")
    def test_source_authors_actual_reader(self):
        source = Path(os.environ["RC22_TEST_SOURCE"]).resolve(strict=True)
        self.assertEqual(subprocess.check_output(["git","-C",source,"rev-parse","HEAD"],text=True).strip(), media.SOURCE)
        rd = source/"scripts/rc22-native"
        self.assertEqual({n:kit.checksum(rd/n) for n in media.READERS},media.READERS)
        receipt,index = fixture_reg()
        # Genuine GNU files exercise the source reader without impersonating a
        # source-built official compiler. The real enrollment must reject this kit.
        payloads = {n: (Path("/bin/false").read_bytes() if n == "roles/fourfix/cargo" else Path("/bin/true").read_bytes())
                    for n in index}
        with tempfile.TemporaryDirectory() as temp:
            top=Path(temp);bundle=top/"bundle";bundle.mkdir()
            for n,data in payloads.items():
                index[n].update(sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
            rust=receipt["rust"]
            rust.update(driver_sha256=index[rust["driver_path"]]["sha256"], rustc_sha256=index["sdk/bin/rustc"]["sha256"],
                        rustdoc_sha256=index["sdk/bin/rustdoc"]["sha256"])
            for role in kit.CARGO:
                receipt["cargos"][role]["sha256"]=index[f"roles/{role}/cargo"]["sha256"]
            kit.save(bundle/"members.json",index)
            def pack(corrupt=False):
                buf=io.BytesIO()
                with tarfile.open(fileobj=buf,mode="w:") as tar:
                    for n,data in payloads.items():
                        i=tarfile.TarInfo(n);i.size=len(data);i.mode=index[n]["mode"]
                        if corrupt and n=="sdk/bin/rustc":
                            data=b"X"+data[1:]
                        tar.addfile(i,io.BytesIO(data))
                compressed=subprocess.check_output(["zstd","-q","-c"],input=buf.getvalue())
                (bundle/"kit.tar.zst").write_bytes(compressed)
                receipt.update(kit_sha256=hashlib.sha256(compressed).hexdigest(),kit_bytes=len(compressed),
                               members_sha256=kit.checksum(bundle/"members.json"))
                (bundle/"receipt.json").write_text(json.dumps(receipt))
            pack()
            with (bundle/"kit.tar.zst").open("rb") as f:
                kit.validate_tar(f,index)
            command=[sys.executable,"-IB",rd/"sdk.py","reopen",bundle]
            subprocess.run([*command,top/"good"],check=True)
            for n,data in payloads.items():
                self.assertEqual((top/"good"/n).read_bytes(),data)
            with self.assertRaises(ValueError):
                kit.registration(receipt,index,{"source_head":HEAD,"run":52})
            pack(corrupt=True)
            with (bundle/"kit.tar.zst").open("rb") as f, self.assertRaises(ValueError):
                kit.validate_tar(f,index)
            run=subprocess.run([*command,top/"bad"],capture_output=True)
            self.assertNotEqual(run.returncode,0)
            self.assertIn(b"sdk/bin/rustc",run.stderr)

    def test_worker_sources_and_entrypoints(self):
        for name, sha in kit.WORKERS.items():
            self.assertEqual(kit.checksum(HERE / name),sha)
        for name in ("native_mounts.py","ruff_recovery.py","media.py","kit.py"):
            subprocess.run([sys.executable,"-IB",HERE/name,"--help"],check=True,stdout=subprocess.DEVNULL)
        subprocess.run(["bash","-n",HERE/"run-worker.sh"],check=True)


if __name__=="__main__":
    unittest.main(verbosity=2)
