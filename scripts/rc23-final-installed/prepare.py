"""Rebind the unchanged native release fixtures to the exact installed component sources."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from verify import COORDINATOR, SOURCES, TARGETS, coordinator, frozen, head, require, save, sha

SUITES = "4fe6d1c04b8226928fb0c57800a864269d7001e8"
LEGACY = "46258d8b9b6ae5f7b443fab3115799466a3b5ff4"
OLD = "f12924d918dbc66898325531940a20aa8cf4f5fc"
BASE = "scripts/rc23-expanded-inputs/"
CASE = "trait-impl-bucket-projection"
NATIVE = (
    "native.py",
    "epoch.py",
    "media.py",
    "materialize.py",
    "published-actors.json",
    "diamond-patch.json",
    "diamond.patch",
    "diamond_policy.py",
    "ohm_ready_tests.rs",
    *(CASE + "/" + n for n in ("rmake.rs", "reader.rs", "roster.rs")),
)
EPOCH_SOURCE = "f96e27d853eaf23289d72479b990780eda43eacc"
PUBLISHED = "scripts/dep-graph-slots/release-22/"
PUBLISHED_SHA = "67a62c80e9ae1dda7650819511f2329add5db7a9ccf35ef7b1b9b64a314b18a2"
PUBLISHED_PINS = {
    "rust": "008a21ac0d750dc9a1c18b7959d7e7984c03d887",
    "cargo": "ed0ae15d22da9a0af9afb3d0fdeb4ceb8a71b770",
}
PUBLISHED_ASSETS = {
    "x86_64-unknown-linux-gnu": (
        698533704, 359852703, "bcf21a3bcdfedd7174ef56ae17a5511fa5b2b6a0afff4b725bed6c5da50194d7"
    ),
    "aarch64-apple-darwin": (
        698533709, 295001987, "4106b90c07ae918a6960e13ef16eb9536ebf8ff39ff04abbdf0c320ebf86d684"
    ),
}


def gitblob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def candidate_installer_checks(source):
    old = f'    "candidate": ("{OLD}", "{SOURCES["cargo"]}"),'
    new = old.replace(OLD, SOURCES["rust"])
    require(
        source.splitlines().count(old.encode()) == 1 and source.count(OLD.encode()) == 1,
        "installer suite no longer has exactly one former candidate registration",
    )
    return source.replace(old.encode(), new.encode())


def published_predecessor(manifest, registry, actors):
    tag = "ohm-1.99.0-22"
    require(sha(manifest) == PUBLISHED_SHA, "different published -22 source manifest")
    sources = json.loads(manifest)["sources"]
    require({k: sources[k]["revision"] for k in PUBLISHED_PINS} == PUBLISHED_PINS, "different -22 components")
    require(
        registry["id"] == 430629054
        and registry["tag_name"] == tag
        and registry["target_commitish"] == "8c7d5b4500fdfa6e2234417340aa190e5787e513",
        "different public release",
    )
    archives = {}
    for target in TARGETS:
        aid, size, digest = PUBLISHED_ASSETS[target]
        expected = {"id": aid, "size": size, "name": f"{tag}-{target}.tar.gz", "digest": "sha256:" + digest}
        require(
            [a for a in registry["assets"] if a["name"] == expected["name"]] == [expected]
            and actors[target]["archive"] == expected,
            ("different published native archive", target),
        )
        archives[target] = expected
    return {
        "release_id": registry["id"],
        "tag": tag,
        "manifest_sha256": PUBLISHED_SHA,
        "sources": PUBLISHED_PINS,
        "archives": archives,
    }


def prepare(root, suites, legacy, out):
    coordinator(root)
    require(head(suites) == SUITES and head(legacy) == LEGACY, "different reviewed native suite")
    require(not out.exists(), "runtime must be newly created")
    predecessor = published_predecessor(
        frozen(legacy, PUBLISHED + "22.json", LEGACY),
        json.loads(frozen(legacy, PUBLISHED + "published-assets.json", LEGACY)),
        json.loads(frozen(suites, BASE + "published-actors.json", SUITES)),
    )
    registered = json.loads((HERE / "native-sources.json").read_bytes())
    require(
        {k: v["revision"] for k, v in registered.items()} == {k: SOURCES[k] for k in ("rust", "cargo")},
        "wrong source fixture registration",
    )
    rust = registered["rust"]["blobs"]
    cargo = registered["cargo"]["blobs"]
    require(
        rust["compiler/rustc_incremental/src/persist/file_format.rs"] == EPOCH_SOURCE
        and rust["compiler/rustc_middle/src/dep_graph/serialized.rs"]
        == "006bc1a676dc34e3ba5a32f4aaf3fa6c3a55a7ed",
        "different numeric header or graph reader",
    )
    require(
        rust["compiler/rustc_codegen_llvm/src/asm.rs"] == "033cf9df65b477ed566089157db7e315dabd6e61",
        "different changed asm implementation",
    )
    for n in ("minicore.rs", "gnu_aarch64.rs", "musl_x86_64.rs", "rmake.rs"):
        upstream = (
            "tests/auxiliary/" + n if n == "minicore.rs" else "tests/run-make/ohm-checked-dep-info/" + n
        )
        require(
            gitblob((HERE / "cross/fixtures" / n).read_bytes()) == rust[upstream],
            ("different in-tree target fixture", n),
        )
    out.mkdir(mode=0o700)
    files = {}
    for n in NATIVE:
        raw = frozen(suites, BASE + n, SUITES)
        if n.startswith(CASE + "/"):
            require(gitblob(raw) == rust["tests/run-make/" + n], ("different real Rust test", n))
        if n == "ohm_ready_tests.rs":
            require(gitblob(raw) == cargo["tests/testsuite/" + n], "different real Cargo terminal test")
        dst = out / n
        dst.parent.mkdir(exist_ok=True)
        dst.write_bytes(raw)
        files[n] = sha(raw)
    native_reg = {
        "coordinator": COORDINATOR,
        "legacy": LEGACY,
        "epoch": 26655,
        "rust_tail": {
            "commit": SOURCES["rust"],
            "paths": {k: v for k, v in rust.items() if k.startswith("tests/run-make/" + CASE + "/")},
        },
        "cargo_tail": {"commit": SOURCES["cargo"]},
    }
    save(out / "registration.json", native_reg)
    old = frozen(suites, "scripts/rc23-expanded-dist/install_checks.py", SUITES)
    new = candidate_installer_checks(old)
    (out / "install_checks.py").write_bytes(new)
    return {
        "suites": SUITES,
        "legacy": LEGACY,
        "inputs": files,
        "native": native_reg,
        "published_predecessor": predecessor,
        "installer_checks": {"original_sha256": sha(old), "runtime_sha256": sha(new)},
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for n in ("root", "suites", "legacy", "out", "receipt"):
        p.add_argument("--" + n, type=Path, required=True)
    a = p.parse_args()
    save(
        a.receipt,
        prepare(
            a.root.resolve(strict=True), a.suites.resolve(strict=True), a.legacy.resolve(strict=True), a.out
        ),
    )
