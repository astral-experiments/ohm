"""Authenticate the release-parent Cargo and switch just that executable in a real SDK."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
SVC = HERE.parent
VERSIONED = SVC.parent / "ohm-aarch64-versioned"
sys.path[:0] = [str(SVC), str(VERSIONED)]
from version_kit import rt

SOURCES = json.loads((HERE / "source.json").read_bytes())
SIGNED = "abf43741c6c75f7fd4a3bcbf1db0cfc29824a07727bde4a3974b3ea44b379c1a"
ORIGINAL = "9fb29f6abecad05acb6015990615c5fbb435a5907543f0bd33cf88cada4f5826"


def registered():
    p = json.loads((HERE / "product.json").read_bytes())
    assert p["source"] == SOURCES["integrated"]["commit"] and p["tree"] == SOURCES["integrated"]["tree"]
    return p


def acquire():
    p = registered()
    api = "repos/astral-experiments/ohm/actions/"
    def get(name):
        return json.loads(subprocess.check_output(["gh", "api", api + name]))
    run = get("runs/" + str(p["run"]))
    assert run["head_sha"] == p["workflow"] and run["head_branch"] == "charlie/qa-gnu-ruff-syscall"
    assert run["event"] == "workflow_dispatch"
    a = get("artifacts/" + str(p["artifact"]))
    assert a["workflow_run"]["id"] == p["run"] and a["name"] == "signed-base-integrated-cargo" and not a["expired"]
    assert (a["size_in_bytes"], a["digest"]) == (p["bytes"], "sha256:" + p["zip_sha256"])
    dest = rt.ROOT / "reader-inputs"
    dest.mkdir()
    with tempfile.TemporaryDirectory(dir=dest) as tmp:
        archive = Path(tmp) / "cargo.zip"
        with archive.open("xb") as stream:
            subprocess.run(["gh", "api", api + "artifacts/" + str(p["artifact"]) + "/zip"], stdout=stream, check=True)
        assert rt.sha(archive) == p["zip_sha256"] and archive.stat().st_size == p["bytes"]
        with zipfile.ZipFile(archive) as zip:
            assert sorted(zip.namelist()) == ["cargo.zst", "product.json"]
            manifest = zip.read("product.json")
            assert hashlib.sha256(manifest).hexdigest() == p["manifest"]
            product = json.loads(manifest)
            assert (product["git"], product["tree"], product["parents"]) == (
                p["source"], p["tree"], SOURCES["integrated"]["parents"])
            assert product["builder"] == SIGNED and product["workflow"] == p["workflow"]
            assert product["sha256"] == p["elf_sha256"] and product["typed_units"] >= 380 and product["construction_rustcs"] >= 380
            wire = Path(tmp) / "cargo.zst"
            with zip.open("cargo.zst") as z, wire.open("xb") as f:
                shutil.copyfileobj(z, f)
        image = dest / "integrated"
        subprocess.run(["zstd", "-qd", wire, "-o", image], check=True)
        assert rt.sha(image) == p["elf_sha256"]
        with image.open("rb") as f:
            elf = f.read(20)
        assert elf[:6] == b"\x7fELF\x02\x01" and elf[18:20] == b"\x3e\x00"
        image.chmod(0o755)
    base = Path(os.environ["CENSUS_PARENT"]).parent / "inputs/versioned/sdk.tar.zst"
    record = json.loads((VERSIONED / "qualified-builds.json").read_bytes())
    assert rt.sha(base) == record["capsule"]
    signed = dest / "signed"
    with signed.open("xb") as out:
        subprocess.run(["tar", "--zstd", "-xOf", base, "objects/" + SIGNED], stdout=out, check=True)
    signed.chmod(0o755)
    assert rt.sha(signed) == SIGNED
    rt.save(rt.LOG / "release-reader-identity.json", {"registration": p, "original_manifest": product, "signed": SIGNED})


def select_cargo(sdk, role):
    source = rt.ROOT / "reader-inputs" / role
    key = SIGNED if role == "signed" else registered()["elf_sha256"]
    assert role in ("signed", "integrated") and rt.sha(source) == key
    exe = sdk / "bin/cargo"
    original = rt.sha(exe)
    assert original == ORIGINAL
    new = exe.with_suffix(".integrated-qa")
    assert not new.exists()
    shutil.copy2(source, new)
    new.replace(exe)
    assert rt.sha(exe) == key
    return key


if __name__ == "__main__":
    acquire()
