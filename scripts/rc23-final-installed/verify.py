"""Authenticate the seven ordinary release files delivered to one native host."""

import hashlib
import json
from pathlib import Path
import re
import stat
import subprocess

HERE = Path(__file__).resolve().parent
COORDINATOR = "e408863e7ba61fac3e054a580e149dbf4c89f582"
MANIFEST = "toolchains/1.99.0/23.json"
MANIFEST_SHA = "ef76f8eb83ea78d7ab3bf272bb3aea0ba2729bd3f626af0faf4842f0c2b51c65"
TOOLCHAIN = "ohm-1.99.0-23"
TARGETS = ("x86_64-unknown-linux-gnu", "aarch64-apple-darwin")
BUILDERS = dict.fromkeys(TARGETS, COORDINATOR)
SOURCES = {
    "rust": "a3fc6da13921586bc374586dee00883e9210aecd",
    "cargo": "159be68484a7f8cb05debf82bee89e594b7f19b6",
    "clippy": "5b5d9fb377e21872c83ed1598f9ffee1420c7b39",
    "rustfmt": "59e87b3b3eb731560e1c3a1da4319af04bda5483",
}
GLOBAL = {"ohm-installer.sh", TOOLCHAIN + ".json", "SHA256SUMS"}


def require(ok, why):
    if not ok:
        raise ValueError(str(why))


def digest(path):
    require(stat.S_ISREG(path.lstat().st_mode), ("nonregular file", path))
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def save(path, value):
    with path.open("x") as f:
        print(json.dumps(value, sort_keys=True, indent=2), file=f)


def head(root):
    return subprocess.check_output(["git", "-C", root, "rev-parse", "HEAD"], text=True).strip()


def frozen(root, path, commit):
    p = root / path
    require(p.resolve(strict=True) == p and stat.S_ISREG(p.lstat().st_mode), ("nonregular reviewed input", p))
    body = p.read_bytes()
    oid = subprocess.check_output(["git", "-C", root, "rev-parse", commit + ":" + path], text=True).strip()
    require(
        hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest() == oid,
        ("altered Git input", path),
    )
    return body


def coordinator(root):
    require(head(root) == COORDINATOR, "wrong package coordinator")
    b = frozen(root, MANIFEST, COORDINATOR)
    require(sha(b) == MANIFEST_SHA, "wrong release manifest")
    manifest = json.loads(b)
    require(
        {k: v["revision"] for k, v in manifest["sources"].items()} == SOURCES
        and manifest["release"]["toolchain_name"] == TOOLCHAIN
        and manifest["prepare_relocated_pgo_dependencies"] is True,
        "different product pins",
    )
    return manifest


def names(target):
    require(target in TARGETS, target)
    stem = TOOLCHAIN + "-" + target
    return {
        stem + suffix
        for suffix in (".tar.gz", ".tar.gz.sha256", "-provenance.json", "-provenance.json.sha256")
    }


def staged(root, directory, target):
    manifest = coordinator(root)
    stem = TOOLCHAIN + "-" + target
    archive, provenance = stem + ".tar.gz", stem + "-provenance.json"
    expected = names(target) | GLOBAL
    require({p.name for p in directory.iterdir()} == expected, "wrong seven release files")
    hashes = {n: digest(directory / n) for n in sorted(expected)}
    require(hashes[TOOLCHAIN + ".json"] == MANIFEST_SHA, "staged manifest differs")
    global_shas = {}
    for line in (directory / "SHA256SUMS").read_text().splitlines():
        m = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9_.-]+)", line)
        require(m and m[2] not in global_shas, "invalid global checksum entry")
        global_shas[m[2]] = m[1]
    global_names = (names(TARGETS[0]) | names(TARGETS[1]) | GLOBAL) - {"SHA256SUMS"}
    global_names = {n for n in global_names if not n.endswith("-provenance.json.sha256")}
    require(set(global_shas) == global_names, "incorrect global checksums inventory")
    for n in global_names & expected:
        require(global_shas[n] == hashes[n], ("different release body", n))
    for n in (archive, provenance):
        require(
            (directory / (n + ".sha256")).read_bytes() == (hashes[n] + "  " + n + "\n").encode(),
            ("bad individual checksum", n),
        )
    tools = manifest["bundled_tools"] if target == TARGETS[0] else {}
    expected_provenance = {
        "schema_version": 1,
        "toolchain": TOOLCHAIN,
        "target": target,
        "bundled_tools": tools,
        "coordinator": {"repository": "astral-experiments/ohm", "revision": COORDINATOR},
        "manifest": {"path": MANIFEST, "sha256": MANIFEST_SHA},
        "sources": {k: {"revision": v} for k, v in SOURCES.items()},
    }
    require(
        json.loads((directory / provenance).read_bytes()) == expected_provenance,
        "wrong native build provenance",
    )
    installer = frozen(root, "scripts/install.sh", COORDINATOR)
    settings = {
        "embedded_version": TOOLCHAIN,
        "embedded_wild_version": manifest["bundled_tools"]["wild"]["version"],
    }
    settings.update(
        {
            "embedded_archive_sha256_" + t.replace("-", "_"): global_shas[TOOLCHAIN + "-" + t + ".tar.gz"]
            for t in TARGETS
        }
    )
    for key, value in settings.items():
        needle = ("\n" + key + "=\n").encode()
        require(installer.count(needle) == 1, ("unrecognized stock installer", key))
        installer = installer.replace(needle, needle[:-1] + value.encode() + b"\n")
    require(
        installer == (directory / "ohm-installer.sh").read_bytes(),
        "global installer differs from actual coordinator",
    )
    return {
        "target": target,
        "coordinator": COORDINATOR,
        "manifest_sha256": MANIFEST_SHA,
        "sources": SOURCES,
        "files": hashes,
    }
