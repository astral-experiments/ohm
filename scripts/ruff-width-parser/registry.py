"""Compare every physically extracted package to the exact locked crates.io transport."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess as sp
import tarfile
import tomllib
import urllib.request

from records import digest, file_hash

def body_hash(stream):
    return hashlib.file_digest(stream, "sha256").hexdigest()

def materialized(home, archives, required=()):
    registry = home / "registry"
    cache, = (registry / "cache").iterdir()
    assert {p.name: file_hash(p) for p in cache.glob("*.crate")} == archives
    inventory = {}
    if not (registry / "src").exists():
        assert not required
        return inventory
    source, = (registry / "src").iterdir()
    assert cache.name == source.name
    for root in sorted(source.iterdir()):
        assert root.is_dir() and not root.is_symlink()
        name = root.name
        archive = cache / (name + ".crate")
        declared = {}
        with tarfile.open(archive, "r:gz") as bundle:
            for member in bundle:
                parts = Path(member.name).parts
                assert parts[0] == name and ".." not in parts
                if member.isdir():
                    continue
                path = Path(*parts[1:])
                assert path.parts and str(path) not in declared
                assert member.isfile(), (name, path, member.type)
                extracted = root / path
                assert extracted.is_file() and not extracted.is_symlink(), extracted
                with bundle.extractfile(member) as incoming:
                    expected = body_hash(incoming)
                assert expected == file_hash(extracted) and extracted.stat().st_size == member.size, extracted
                declared[str(path)] = [expected, member.size]
        physical = {str(f.relative_to(root)) for f in root.rglob("*") if not f.is_dir() or f.is_symlink()}
        assert physical == set(declared) | {".cargo-ok"}, (root, physical ^ set(declared))
        assert json.loads((root / ".cargo-ok").read_bytes()) == {"v": 1}
        body = json.dumps(declared, sort_keys=True, separators=(",", ":")).encode()
        inventory[name] = {"tree": digest(body), "files": len(declared),
                           "bytes": sum(r[1] for r in declared.values()), "archive": archives[archive.name]}
        if name.startswith("unicode-width-"):
            inventory[name]["members"] = declared
    assert set(required) <= set(inventory)
    return inventory

def git_roots(home, pins):
    roots = sorted((home / "git/db").iterdir())
    assert len(roots) == len(pins)
    admitted = {}
    for url, tree in pins.items():
        commit = url.rsplit("#", 1)[1]
        matches = []
        for root in roots:
            found = sp.run(["git", "--git-dir", root, "rev-parse", "--verify", commit + "^{tree}"],
                           capture_output=True, text=True)
            if found.returncode == 0:
                matches.append((root, found.stdout.strip()))
        assert len(matches) == 1 and matches[0][1] == tree, (url, matches)
        admitted[url] = {"commit":commit, "tree":tree, "bare":matches[0][0].name}
    assert len({v["bare"] for v in admitted.values()}) == len(pins)
    return admitted

def seed(src, home, locked, env, switch):
    env = env.copy()
    del env["CARGO_NET_OFFLINE"]
    for rev in (locked["old"], locked["new"]):
        switch(rev)
        assert file_hash(src / "Cargo.lock") == locked["locks"][rev]
        sp.run(["cargo", "+ohm", "fetch", "--locked"], cwd=src, env=env, check=True)
        cache, = (home / "registry/cache").iterdir()
        packages = [p for p in tomllib.loads((src / "Cargo.lock").read_text())["package"] if "source" in p]
        git_sources = {p["source"] for p in packages if p["source"].startswith("git+")}
        assert git_sources == set(locked["git"])
        git_roots(home, locked["git"])
        packages = [p for p in packages if p["source"] not in git_sources]
        assert len(packages) == 466
        for pkg in packages:
            assert pkg["source"] == "registry+https://github.com/rust-lang/crates.io-index"
            archive = cache / (pkg["name"] + "-" + pkg["version"] + ".crate")
            assert locked["archives"][archive.name] == pkg["checksum"]
            if not archive.exists():
                url = "https://static.crates.io/crates/" + pkg["name"] + "/" + archive.name
                with urllib.request.urlopen(url, timeout=80) as response, archive.open("xb") as output:
                    shutil.copyfileobj(response, output)
    assert len(locked["archives"]) == 467
    cache, = (home / "registry/cache").iterdir()
    assert {p.name: file_hash(p) for p in cache.glob("*.crate")} == locked["archives"]
