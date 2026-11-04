"""Test deferred registry freshness with the two real same-remap Cargo revisions."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess as sp
import sys
import traceback
import zipfile

here = Path(__file__).resolve().parent
sys.path.insert(0, str(here))
import run as helper

pair = json.loads((here / "first-parent.json").read_bytes())


def git(src, *args):
    return sp.check_output(["git", *args], cwd=src, text=True).strip()


def exact_parent(src):
    helper.source_at(src)
    before, after = pair["before"], pair["after"]
    assert after == helper.reg["head"] and helper.reg["parents"][0] == before
    pack = here / "first-parent.pack"
    assert pack.stat().st_size == pair["pack_bytes"] and helper.sha(pack) == pair["pack_sha256"]
    (src / ".git/shallow").write_text(before + "\n" + after + "\n")
    with pack.open("rb") as f:
        label = sp.check_output(["git","index-pack","--strict","--stdin"], cwd=src, stdin=f, text=True).strip().split()
    assert len(label) == 2 and label[0] == "pack"
    idx = src / (".git/objects/pack/pack-" + label[1] + ".idx")
    ids = [v.split()[0] for v in git(src, "verify-pack", "-v", str(idx)).splitlines() if v.split()[1:2] in (["tree"],["blob"],["commit"])]
    assert len(ids) == pair["delta_count"] and hashlib.sha256(("\n".join(sorted(ids))+"\n").encode()).hexdigest() == pair["delta_roster"]
    assert git(src, "rev-parse", before+"^{tree}") == pair["tree"]
    assert git(src, "rev-parse", after+"^{tree}") == pair["merge_tree"]
    for expected, count, roster in [(before, pair["parent_count"], pair["parent_roster"]),(after, pair["head_count"], pair["head_roster"])]:
        ids = sorted(set(git(src,"rev-list","--objects","--no-object-names",expected).splitlines()))
        assert len(ids) == count and hashlib.sha256(("\n".join(ids)+"\n").encode()).hexdigest() == roster
        sp.run(["git","fsck","--strict","--full","--no-reflogs",expected], cwd=src, check=True)
    assert len(git(src, "diff", "--name-only", before, after).splitlines()) == 6


def runner(reference, old, new):
    assert helper.sha(reference) == helper.reg["prior_files"]["evidence/nonempty-registry-history/replay.py"]
    text = reference.read_text()
    for orig, replacement in [
        ("b05c0f1a01f8cae3ccb7446647fcb7d9b5a36c3dfabc340a78a8b189561036b6", old),
        ("32df98560d4ac57c4c959c762095a3afe6a3bbe62b44d8fc6e6bf8071f53a53e", new),
        ("or a.published_parent\n        and not", "or not a.published_parent\n        and not"),
    ]:
        assert text.count(orig) == 1
        text = text.replace(orig, replacement)
    return text


def verified_parent(archive, destination, current_sdk, rustc, dependencies):
    """Read the authenticated first parent from the prior worker's original upload."""
    assert helper.sha(archive) == "e8522941fb2b486f7a209b58dfec401e08e599468efc1532c25c6744f2000db3"
    with zipfile.ZipFile(archive) as original:
        assert original.testzip() is None
        data = json.loads(original.read("compiler.json"))
        assert data["qa"] == "e3e3ad915d588498a7ca458c124e66218e8d453d"
        assert int(data["run"]) == 41867097954 and data["dependencies"] == dependencies and data["rustc"] == rustc
        assert json.loads(original.read("sdk.json")) == current_sdk
        record = data["roles"]["before"]
        assert record["source"] == pair["before"] and record["tree"] == pair["tree"]
        with original.open("physical/cargo-before") as src, destination.open("xb") as dst:
            shutil.copyfileobj(src, dst)
    assert helper.sha(destination) == record["sha256"] == "70e27c0843f7bce42232024532f78b62fa365e17785e66122bd64b1a1de121ac"
    destination.chmod(0o755)
    return record


def main():
    root = Path(os.environ["RUNNER_TEMP"]) / "cargo25-registry"
    root.mkdir()
    proof = root / "proof"
    proof.mkdir()
    src = root / "cargo-src"
    exact_parent(src)
    assert all(helper.sha(helper.prior / name) == digest for name,digest in helper.reg["prior_files"].items())
    sdk = helper.signed_sdk(root, proof)
    alias = root / "rustup/toolchains/ohm"
    alias.parent.mkdir(parents=True)
    alias.symlink_to(sdk)
    env = {k: os.environ[k] for k in ("PATH","HOME","USER","LANG","TMPDIR") if k in os.environ}
    env.update(CARGO_HOME=str(root/"compiler-home"), RUSTUP_HOME=str(root/"rustup"), RUSTUP_TOOLCHAIN="ohm",
               CARGO_TARGET_DIR=str(root/"compiler-target"), CARGO_BUILD_BUILD_DIR=str(root/"compiler-build"),
               CARGO_PROFILE_RELEASE_DEBUG="0", CARGO_INCREMENTAL="false")
    rustc = helper.out(["rustc","+ohm","-vV"],src,env)
    signed_cargo = helper.out(["cargo","+ohm","-vV"],src,env)
    assert helper.reg["signed_rust"] in rustc and helper.reg["root"] in signed_cargo
    deps = helper.locked_inputs(src, env)
    assert len(deps) == 524
    physical = proof / "physical"
    physical.mkdir()
    argv = ["cargo","+ohm","-Zohm-defaults=no","build","--release","--locked","--offline","-p","cargo","--bin","cargo",
            "--features","all-static,ohm-defaults",f"-j{min(8,os.cpu_count())}"]
    records = {}
    for role in ["before","after"]:
        revision = pair[role]
        sp.run(["git","checkout","--quiet","--detach",revision],cwd=src,check=True)
        assert git(src,"rev-parse","HEAD") == revision and not git(src,"status","--porcelain")
        assert helper.sha(src/"Cargo.lock") == helper.reg["rust_package"]
        path = physical / ("cargo-"+role)
        if role == "before":
            verified_parent(root.parent / "first-parent-original.zip", path, json.loads((proof/"sdk.json").read_bytes()), rustc, deps)
        else:
            # Cargo's Git build stamp does not declare .git/HEAD as an input.
            # The candidate must have empty compiler outputs throughout this checkout.
            assert not (root/"compiler-target/release").exists() and not (root/"compiler-build/release").exists()
            sp.run(argv,cwd=src,env=env,check=True)
            assert not git(src,"status","--porcelain")
            shutil.copy2(root/"compiler-target/release/cargo", path)
        vv = helper.out([path,"-vV"],src,env)
        assert "commit-hash: "+revision in vv
        records[role] = {"source":revision,"tree":git(src,"rev-parse","HEAD^{tree}"),"cargo":vv,"sha256":helper.sha(path)}
        helper.dump(proof/"compiler.json",{"roles":records,"signed_cargo":signed_cargo,"rustc":rustc,"dependencies":deps,"build":argv,
            "qa":os.environ["GITHUB_SHA"],"run":os.environ["GITHUB_RUN_ID"],"boot":Path("/proc/sys/kernel/random/boot_id").read_text().strip()})
    assert records["before"]["sha256"] != records["after"]["sha256"]
    ref = helper.prior / "evidence/nonempty-registry-history/replay.py"
    replay = proof / "same-remap-replay.py"
    replay.write_text(runner(ref,records["before"]["sha256"],records["after"]["sha256"]))
    refusals = {}
    for label,control in [("first-v5","--first-clean"),("inherited","--legacy-control")]:
        case = root / label
        try:
            sp.run(["strace","-f","-qq","-s","768","-e","trace=execve","-o",proof/(label+".exec"),sys.executable,"-IB",replay,case,control,
                    "--signed",sdk,"--parent",physical/"cargo-before","--candidate",physical/"cargo-after"],check=True)
        except Exception:
            refusals[label] = traceback.format_exc()
            helper.dump(proof/"refusals.json",refusals)
        finally:
            if (case/"evidence").is_dir():
                (case/"evidence").rename(proof/label)
                for inp,out in [("objects/v5consumer/0.1.0/download","v5consumer.crate"),("index/v5/co/v5consumer","registry/v5/co/v5consumer"),
                                ("application/Cargo.lock","application/Cargo.lock")]:
                    if (case/inp).is_file():
                        dst = proof/label/out
                        dst.parent.mkdir(parents=True,exist_ok=True)
                        shutil.copyfile(case/inp,dst)
    assert not refusals, refusals
    helper.dump(proof/"complete.json",{"roles":records,"cases":["first-v5","inherited"],"reference":helper.sha(ref),"runner":helper.sha(replay)})


if __name__ == "__main__":
    if len(sys.argv)==3 and sys.argv[1]=="--check-source":
        exact_parent(Path(sys.argv[2]))
    else:
        assert len(sys.argv)==1
        main()
