"""Bind the selected installed host compiler to one genuine final-qualification ZIP."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import zipfile

RUST = "a3fc6da13921586bc374586dee00883e9210aecd"
CARGO = "159be68484a7f8cb05debf82bee89e594b7f19b6"
ROOT = "e408863e7ba61fac3e054a580e149dbf4c89f582"
MANIFEST = "ef76f8eb83ea78d7ab3bf272bb3aea0ba2729bd3f626af0faf4842f0c2b51c65"
QA = "ef93e73f36ff44577d10d9b412c78a3015896110"
RUN = 41351902967
REPO = 1319437234
HOST = "x86_64-unknown-linux-gnu"
STEM = "ohm-1.99.0-23-" + HOST


def need(test, message):
    if not test:
        raise ValueError(message)


def file_sha(path):
    with path.open("rb") as fd:
        return hashlib.file_digest(fd, "sha256").hexdigest()


def bind_catalog(row, official):
    wr = row["workflow_run"]
    need((wr["id"], wr["head_sha"], wr["repository_id"], row["name"]) ==
         (RUN, QA, REPO, STEM), "wrong original run, source or target")
    digest = row["digest"].removeprefix("sha256:")
    need(len(digest) == 64 and row["size_in_bytes"] == official.stat().st_size and
         file_sha(official) == digest, "official ZIP length or authenticated digest")
    return digest


def select_tar(name, dtype):
    parts = Path(name).parts
    return (len(parts) >= 3 and len(parts) == len(dtype) + 1 and parts[1:] == dtype)


def admit(catalog, official, sdk, rustup, env):
    row = json.loads(catalog.read_bytes())
    outer = bind_catalog(row, official)
    with zipfile.ZipFile(official) as z:
        archive = STEM + ".tar.gz"
        provenance = STEM + "-provenance.json"
        need(len(z.namelist()) == 4 and set(z.namelist()) ==
             {archive, archive + ".sha256", provenance, provenance + ".sha256"}, "ZIP member set")
        for name in (archive, provenance):
            with z.open(name) as f:
                actual = hashlib.file_digest(f, "sha256").hexdigest()
            need(z.read(name + ".sha256").decode().split() == [actual, name], "sidecar " + name)
        p = json.loads(z.read(provenance))
        need(p["target"] == HOST and p["coordinator"]["revision"] == ROOT and
             p["manifest"]["sha256"] == MANIFEST and p["sources"]["rust"]["revision"] == RUST and
             p["sources"]["cargo"]["revision"] == CARGO, "native archive source pins")
        driver = list((sdk / "lib").glob("librustc_driver-*.so"))
        need(len(driver) == 1, "one installed rustc driver")
        files = {"bin/rustc":"rustc", "bin/cargo":"cargo", "lib/"+driver[0].name:"rustc",
                 "lib/rustlib/"+HOST+"/bin/rust-lld":"rustc"}
        # LLVM's ELF and its small linker script are part of the assembler proof.
        # Verify the absolute installed paths and reject unexpected binary aliases.
        native_libs = list((sdk / "lib").glob("*.so*"))
        native_libs += list((sdk / "lib/rustlib" / HOST / "codegen-backends").glob("*.so*"))
        need(any(f.name.startswith("libLLVM") for f in native_libs), "missing installed LLVM")
        for f in native_libs:
            need(f.is_file() and not f.is_symlink(), "unsupported shared-library alias " + str(f))
            files[str(f.relative_to(sdk))] = "rustc"
        observed = {}
        with z.open(archive) as raw, tarfile.open(fileobj=raw, mode="r|gz") as tar:
            for entry in tar:
                for rel,component in files.items():
                    if not select_tar(entry.name, (component, *Path(rel).parts)):
                        continue
                    need(entry.isfile() and rel not in observed, "nonregular/duplicate " + rel)
                    with tar.extractfile(entry) as f:
                        h = hashlib.file_digest(f, "sha256").hexdigest()
                    installed = sdk / rel
                    need(installed.stat().st_size == entry.size and file_sha(installed) == h, "installed " + rel)
                    observed[rel] = [h, entry.size, installed.stat().st_dev, installed.stat().st_ino]
        need(observed.keys() == files.keys(), "missing authenticated SDK member")
    for tool,commit in (("rustc",RUST),("cargo",CARGO)):
        selected = Path(subprocess.check_output([rustup,"which","--toolchain","ohm",tool],env=env,text=True).strip())
        need(os.path.samefile(selected,sdk/"bin"/tool), "actual rustup alias " + tool)
        proxy = str(Path(rustup).parent / tool)
        version = subprocess.check_output([proxy,"+ohm","-vV"],env=env,text=True)
        need("commit-hash: "+commit in version.splitlines(), "executable commit from -vV: "+tool)
    return dict(official_artifact_id=row["id"], official_zip_sha256=outer, source=p, selected=observed)
