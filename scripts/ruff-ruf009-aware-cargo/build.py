"""Reconstruct and build the single source-pinned Cargo client used by the mixed-SDK study."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
QA = SCRIPTS.parent
FIX = SCRIPTS / "ruff-join-proof/fix"
PLAN = json.loads((HERE / "registration.json").read_bytes())
PREVIOUS = json.loads((FIX / "plan.json").read_bytes())


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def materialize(root, evidence, pack):
    def git(*args, binary=False):
        value = subprocess.check_output(["git", "-C", root, *args])
        return value if binary else value.decode().strip()

    assert not root.exists()
    root.mkdir()
    git("init", "--quiet", "--template=")
    signed = PREVIOUS["parent"]
    prior = PREVIOUS["prior_qa_source"]
    assert sha(pack) == prior["pack_sha256"]
    delta = FIX / "signed-delta.pack"
    assert sha(delta) == PREVIOUS["delta_sha256"]
    for source in (pack, delta):
        with source.open("rb") as stream:
            subprocess.run(["git", "-C", root, "index-pack", "--stdin"], stdin=stream, check=True)
    (root / ".git/shallow").write_text(prior["source_sha"] + "\n" + signed + "\n")
    git("update-ref", "refs/heads/release-parent", signed)
    git("switch", "--detach", signed)
    assert git("write-tree") == PREVIOUS["signed_tree"]
    for name, digest, head in (
        (FIX / "candidate-v3.bundle", PREVIOUS["bundle_sha256"], PLAN["transport_base"]),
        (HERE / PLAN["aware_bundle"], PLAN["aware_bundle_sha256"], PLAN["source"]),
    ):
        assert sha(name) == digest
        git("bundle", "verify", str(name))
        git("fetch", "--no-tags", str(name), "HEAD")
        assert git("rev-parse", "FETCH_HEAD") == head
        git("switch", "--detach", head)
    git("fsck", "--full", "--strict", "--no-progress")
    assert git("rev-parse", "HEAD^") == PLAN["parent"]
    assert git("rev-list", "--first-parent", "--reverse", signed + "..HEAD").splitlines() == PLAN["source_chain"]
    assert PLAN["source_chain"][:3] == [PREVIOUS["first_candidate"], PREVIOUS["second_candidate"], PREVIOUS["candidate"]]
    assert git("rev-parse", "HEAD^{tree}") == git("write-tree") == PLAN["tree"]
    assert not git("status", "--porcelain")
    assert set(git("diff", "--name-only", "HEAD^", "HEAD").splitlines()) == set(PLAN["changed"])
    for path, ids in PLAN["changed"].items():
        assert git("rev-parse", "HEAD^:" + path) == ids["parent"]
        assert git("rev-parse", "HEAD:" + path) == ids["candidate"]

    rows = {}
    for entry in git("ls-files", "-s", "-z", binary=True).rstrip(b"\0").split(b"\0"):
        index, rel = entry.split(b"\t", 1)
        mode, blob, stage = index.decode().split()
        name = os.fsdecode(rel)
        path = root / name
        assert stage == "0" and mode in ("100644", "100755", "120000")
        assert path.is_symlink() == (mode == "120000")
        if path.is_symlink():
            body = os.fsencode(os.readlink(path))
        else:
            assert path.is_file() and bool(path.stat().st_mode & 0o111) == (mode == "100755")
            body = path.read_bytes()
        raw_git = hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()
        if raw_git != blob:
            assert body == git("cat-file", "--filters", "--path=" + name, "HEAD:" + name, binary=True)
        rows[name] = [mode, blob, len(body), hashlib.sha256(body).hexdigest()]
    assert len(rows) == 3119
    record = evidence / "physical-source.json.gz"
    record.write_bytes(gzip.compress(json.dumps(rows, sort_keys=True).encode(), mtime=0))
    return {"source": PLAN["source"], "tree": PLAN["tree"], "files": len(rows), "inventory": sha(record)}


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("--source-only", type=Path)
    cli.add_argument("--prior-source-pack", required=True, type=Path)
    args = cli.parse_args()
    for path, expected in PLAN["prior_receiver"].items():
        assert sha(QA / path) == expected
    if args.source_only:
        evidence = args.source_only
        evidence.mkdir(exist_ok=False)
        source = materialize(evidence / "checkout", evidence, args.prior_source_pack.resolve())
        (evidence / "source.json").write_text(json.dumps(source, sort_keys=True) + "\n")
        return

    sys.path[:0] = [str(SCRIPTS / "ruff-foreign-span-observer"), str(FIX)]
    import worker as sdk
    import build as constructor

    assert Path(constructor.__file__).resolve() == FIX / "build.py"
    env = sdk.install()
    root = Path(os.environ["GITHUB_WORKSPACE"]) / "cargo"
    bound = materialize(root, sdk.proof, args.prior_source_pack.resolve())
    sdk.put(sdk.proof / "source.json", bound)
    target = sdk.root / "factory-target"
    shared = sdk.root / "factory-shared"
    env.update(PLAN["profile"], RUSTUP_TOOLCHAIN="ohm", CARGO_TARGET_DIR=str(target), CARGO_BUILD_BUILD_DIR=str(shared))
    argv = ["cargo", "+ohm", "-Zohm-defaults=no", "build", "--locked", "--release", "-p", "cargo",
            "--bin", "cargo", "--features", PLAN["features"], "-j8", "--message-format=json-render-diagnostics"]
    stdout = constructor.run(sdk, env, "factory", argv, root)
    rows = [json.loads(line) for line in stdout.read_text().splitlines() if line.startswith("{")]
    assert rows[-1] == {"reason": "build-finished", "success": True}
    selected, = [r for r in rows if r.get("executable") and r["target"]["name"] == "cargo" and "bin" in r["target"]["kind"]]
    exe = Path(selected["executable"]).resolve()
    assert selected["profile"]["opt_level"] == "3" and not selected["fresh"] and exe.is_file()
    assert any(exe.is_relative_to(directory) for directory in (target, shared))
    version = subprocess.check_output([exe, "-Vv"], env=env, text=True)
    assert PLAN["source"] in version
    product = sdk.proof / "candidate-cargo"
    shutil.copy2(exe, product)
    assert sha(exe) == sha(product)
    sdk.put(sdk.proof / "factory-identity.json", {
        **bound, "baseline_fix": PLAN["parent"], "binary_sha256": sha(product), "bytes": product.stat().st_size,
        "mode": oct(product.stat().st_mode & 0o777), "version": version, "argv": argv, "profile": PLAN["profile"],
        "signed_sdk": sha(sdk.proof / "sdk-proof.json"), "rustc": subprocess.check_output(["rustc", "+ohm", "-vV"], env=env, text=True),
        "qualification": "GNU Linux release profile, thin LTO and one codegen unit; distribution PGO and BOLT are separate.",
    })


if __name__ == "__main__":
    main()
