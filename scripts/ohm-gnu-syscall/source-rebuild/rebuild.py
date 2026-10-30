"""Rebuild the three measured sources and reopen the resulting native compiler installations."""
import argparse
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tarfile

HERE = Path(__file__).resolve().parent
SVC = HERE.parent
SCRIPTS = SVC.parent
sys.path[:0] = [str(HERE), str(SVC)]
from bootstrap import CHILD, PARENT, git, materialize, rt, stage
from elf import compare, describe

MEMBERS = rt.load(SCRIPTS / "ohm-aarch64-portable-review/source/sdk-members.json")
CARGO_SOURCE = "c18e91b514b2c4e4966c9ab03232c804af3e1b57"
CARGO_HASH = MEMBERS["common"]["bin/cargo"][0]
ROLES = {"builder": "N", "parent": "M", "patched": "C"}


def patched_record():
    """Read the enrolled candidate directly from the durable first pair, validating its hash."""
    evidence = SVC / "evidence/literal-svc-ruff-cli"
    archive = evidence / "pairs/01.tar.zst"
    registration = rt.load(evidence / "registration.json")
    assert rt.sha(archive) == registration["pairs"][0]["retained_sha256"]
    raw = subprocess.check_output(["zstd", "-qdc", archive])
    with tarfile.open(fileobj=io.BytesIO(raw)) as records:
        candidate = json.load(records.extractfile("candidate.json"))
    assert candidate["source"] == CHILD and candidate["parent"] == PARENT
    assert candidate["driver_path"] == MEMBERS["driver_path"] and candidate["unchanged_members"] == 118
    return candidate


def check_sdk(sdk, expected):
    """Check all files including both triples' libraries, their modes and the selected driver."""
    names = {p.relative_to(sdk).as_posix() for p in sdk.rglob("*") if p.is_file()}
    assert len(expected) == 119 and names == set(expected), sorted(names ^ set(expected))
    rows = {}
    for name in sorted(expected):
        path = sdk / name
        info = path.stat()
        rows[name] = [rt.sha(path), info.st_size, stat.S_IMODE(info.st_mode)]
    differences = {n: {"measured": expected[n], "rebuild": rows[n]} for n in rows if rows[n] != expected[n]}
    rt.save(rt.LOG / "physical-sdk.json", {"files": rows, "differences": differences})
    assert not differences, list(differences)


def rustc(role, cargo_transfer):
    sdk = rt.SDK
    rt.room(True)
    rt.release()
    src = rt.ROOT / "rust"
    materialize(src)
    registered = patched_record() if role == "patched" else MEMBERS["roles"][ROLES[role]]
    rev = registered["source"]
    git(src, "switch", "--detach", rev)
    assert git(src, "rev-parse", "HEAD^{tree}") == registered["tree"]
    assert not git(src, "status", "--porcelain", "--untracked-files=no")
    # Runtime.freeze writes P-sdk.json or C-sdk.json, including both selected library triples.
    label = "C" if role == "patched" else "P"
    rt.PARENT = rt.CHILD = rev
    for part, target, build in (("host", rt.HOST, ["compiler/rustc", "library"]),
                                ("target", rt.TARGET, ["library"])):
        stage(["build", "--stage", "1", "-j8", "--host", rt.HOST, "--target", target, *build], part)
        rt.freeze(label, part)
    manifest = rt.load(rt.LOG / (label + "-sdk.json"))
    assert (manifest["source"], manifest["tree"], manifest["bootstrap"]) == (
        rev, registered["tree"], registered["bootstrap"])
    for name, (digest, size, mode) in manifest["files"].items():
        src = rt.CAP / "objects" / digest
        assert src.stat().st_size == size and rt.sha(src) == digest
        dest = sdk / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        dest.chmod(mode)
    expected = MEMBERS["common"] | {MEMBERS["driver_path"]: registered["driver"]}
    if role == "builder":
        assert not cargo_transfer
        original = sdk / "bin/cargo"
        assert rt.sha(original) == rt.TOOLS["bin/cargo"]
        expected["bin/cargo"] = [rt.TOOLS["bin/cargo"], original.stat().st_size, stat.S_IMODE(original.stat().st_mode)]
    else:
        assert cargo_transfer is not None
        seal = rt.load(cargo_transfer / "product.json")
        assert (seal["git"], seal["cargo_sha256"], seal["builder"], seal["SDK_driver"]) == (
            CARGO_SOURCE, CARGO_HASH, rt.TOOLS["bin/cargo"], MEMBERS["roles"]["N"]["driver"][0])
        assert seal["source_workflow"] == os.environ["GITHUB_SHA"]
        new = sdk / "bin/cargo.rebuilt"
        with new.open("xb") as out:
            subprocess.run(["zstd", "-qdc", cargo_transfer / "cargo.zst"], stdout=out, check=True)
        assert rt.sha(new) == CARGO_HASH
        new.chmod(seal["mode"])
        new.replace(sdk / "bin/cargo")
    check_sdk(sdk, expected)
    rt.save(rt.LOG / "selected.json", {"role": role, "commit": rev, "tree": registered["tree"],
                                      "driver": registered["driver"], "cargo": expected["bin/cargo"],
                                      "member_count": len(expected), "bootstrap": manifest["bootstrap"]})
    if role == "patched":
        rt.save(rt.LOG / "candidate.json", registered)
    print(role, rev, "119 original native files match", flush=True)


def cargo(builder_root, unfixed_clock, control_product):
    """Build the enrolled Cargo source with the separate, freshly constructed builder SDK."""
    sys.path.insert(0, str(SCRIPTS / "ohm-aarch64-versioned"))
    import cargo_build
    source = cargo_build.meta
    assert source["source"] == CARGO_SOURCE
    builder = rt.load(builder_root / "receipts/selected.json")
    assert builder["role"] == "builder" and builder["commit"] == MEMBERS["roles"]["N"]["source"]
    shutil.copytree(builder_root / "rustup/toolchains/ohm", rt.SDK, copy_function=os.link)
    shutil.copyfile(builder_root / "receipts/P-sdk.json", rt.LOG / "P-sdk.json")
    cargo_build.original.kit.bind()
    cargo_build.original.CANDIDATE = source["source"]
    cargo_build.original.TREE = source["tree"]
    cargo_build.original.materialize = cargo_build.materialize
    historical = rt.load(HERE / "original-cargo-elf.json")
    assert historical["source"] == CARGO_SOURCE and historical["elf"]["sha256"] == CARGO_HASH
    stamp = historical["elf"]["openssl_build_time"]["bytes"]
    epoch = int(datetime.strptime(stamp, "built on: %a %b %d %H:%M:%S %Y UTC").replace(tzinfo=timezone.utc).timestamp())
    assert epoch == 1793374538
    cargo_build.original.build_with_selected_sdk(source_date_epoch=None if unfixed_clock else epoch)
    product = rt.load(rt.ROOT / "product/product.json")
    binary = rt.ROOT / "product/cargo"
    body = binary.read_bytes()
    elf = describe(body)
    result = elf["sha256"]
    rt.save(rt.LOG / "cargo-elf.json", elf)
    rt.save(rt.LOG / "physical-cargo.json", {"source": source, "measured": CARGO_HASH, "rebuilt": result,
                                            "source_date_epoch": None if unfixed_clock else epoch,
                                            "builder": builder, "product": product})
    assert product["git"] == CARGO_SOURCE and product["SDK_driver"] == builder["driver"][0]
    compressed = rt.ROOT / "product/cargo.zst"
    subprocess.run(["zstd", "-q", "-T2", "-3", binary, "-o", compressed], check=True)
    if unfixed_clock:
        assert control_product is None
        return
    if control_product is not None:
        control = rt.LOG / "clock-control"
        control.mkdir()
        shutil.copyfile(compressed, control / "pinned-cargo.zst")
        shutil.copyfile(control_product.with_suffix(".zst"), control / "unpinned-cargo.zst")
        differences = compare(body, control_product.read_bytes())
        rt.save(control / "comparison.json", differences)
    assert result == CARGO_HASH and elf == historical["elf"], f"rebuilt Cargo {result}, original {CARGO_HASH}"
    cargo_build.unit()


def verify_ruff(role, receipts):
    from hashlib import sha256
    expected = (19, 19) if role == "parent" else (4, 3)
    assert role in ("parent", "patched")
    terminal = rt.load(receipts / "terminal.json")
    assert terminal["untimed"] is True
    rows = terminal["phases"]
    assert rows["invalid"] == {"diagnostic": "E0425"}
    assert tuple(len(rows[p]["full"]) for p in ("edit", "repeat")) == expected
    assert all(rows[p]["root_links"] == 1 for p in ("edit", "repeat"))
    assert all(rows[p]["matches_empty"] == {"sha256": True, "text_sha": True} for p in ("edit", "repeat", "repair"))
    assert all(rows[p]["product"] == rows["empty-new"]["product"] for p in ("edit", "repeat", "repair"))
    assert rows["cold"]["product"]["sha256"] != rows["empty-new"]["product"]["sha256"]
    for phase in ("cold", "edit", "repeat", "repair", "empty-new"):
        assert rt.load(receipts / phase / "census.json")["typed"] == 372
    rt.save(rt.LOG / "ruff-readback.json", {"role": role, "counts": list(expected),
            "terminal_sha256": sha256((receipts / "terminal.json").read_bytes()).hexdigest(),
            "old": rows["cold"]["product"], "edited": rows["empty-new"]["product"]})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    bootstrap = actions.add_parser("rustc")
    bootstrap.add_argument("role", choices=ROLES)
    bootstrap.add_argument("--cargo-transfer", type=Path)
    build_cargo = actions.add_parser("cargo")
    build_cargo.add_argument("builder_root", type=Path)
    build_cargo.add_argument("--unfixed-clock", action="store_true", help="build a diagnostic current-time Cargo")
    build_cargo.add_argument("--control-product", type=Path, help="compare every ELF byte to the diagnostic build")
    ruff = actions.add_parser("verify-ruff")
    ruff.add_argument("role", choices=("parent", "patched"))
    ruff.add_argument("receipts", type=Path)
    args = parser.parse_args()
    if args.action == "rustc":
        rustc(args.role, args.cargo_transfer)
    elif args.action == "cargo":
        cargo(args.builder_root, args.unfixed_clock, args.control_product)
    else:
        verify_ruff(args.role, args.receipts)
