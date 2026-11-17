"""Prepare the Codex inputs used to benchmark stock Rust and Ohm 1.100 on Linux."""

import argparse
import hashlib
import json
import os
import subprocess
import tarfile
import tempfile
from pathlib import Path

CODEX_BASE = "5157493c23713ac12034cf250ffb0a8ce0670277"
CRATE = "allocative-0.3.6"
CRATE_DIGEST = "d8cf9afc79c83d514444b55df3935d317da54b1ce3b17a133c646889cc260de8"
UPSTREAM_FIX = "9711293c6de502d50583cafb12e4a7b764094d3a"
FIXED_FILES = {
    "src/lib.rs": "51ce256338801dad0d50e664ff1ce182715cd208dfe6a99133147ea1f4dd2c16",
    "src/impls/std/unsorted.rs": "0a8323b891c54017b3827b59b7722e588268a5c6b1f28aede7976779bfe05983",
}
HERE = Path(__file__).resolve().parent
PATCHES = HERE.parents[1] / "patches"
ALLOCATIVE_PATCH = PATCHES / "rust-1.100-allocative-0.3.6.patch"


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def git(directory, *args, env=None):
    return subprocess.check_output(["git", *args], cwd=directory, env=env, text=True).strip()


def check_sources(directory, expected):
    paths = directory.rglob("*")
    actual = {str(path.relative_to(directory)): sha256(path) for path in paths if path.is_file()}
    if actual != expected:
        raise ValueError(f"Prepared sources differ from the published crate plus {UPSTREAM_FIX}")


def prepare_crate(archive, inputs):
    if sha256(archive) != CRATE_DIGEST:
        raise ValueError(f"Incorrect published {CRATE} checksum in {archive}")
    crate = inputs / CRATE
    with tarfile.open(archive) as package:
        expected = {}
        for entry in package.getmembers():
            member = Path(entry.name)
            if member.parts[0] != CRATE or ".." in member.parts or not (entry.isfile() or entry.isdir()):
                raise ValueError(f"Unexpected crate member {entry.name}")
            if entry.isfile():
                name = str(member.relative_to(CRATE))
                with package.extractfile(entry) as stream:
                    expected[name] = hashlib.file_digest(stream, "sha256").hexdigest()
        if not FIXED_FILES.keys() <= expected.keys():
            raise ValueError("The release archive lacks the expected allocative sources")
        expected.update(FIXED_FILES)
        if not crate.exists():
            with tempfile.TemporaryDirectory(dir=inputs) as temporary:
                package.extractall(temporary, filter="data")
                unpacked = Path(temporary) / CRATE
                subprocess.run(["git", "apply", "--no-index", str(ALLOCATIVE_PATCH)], cwd=unpacked, check=True)
                check_sources(unpacked, expected)
                unpacked.rename(crate)
        else:
            check_sources(crate, expected)
    return crate


def prepare_command_source(original, inputs, patch):
    # The benchmark clone owns this synthetic commit. The original checkout only supplies objects.
    source = inputs / "codex-commands"
    if not source.exists():
        with tempfile.TemporaryDirectory(dir=inputs) as temporary:
            clone = Path(temporary) / "clone"
            subprocess.run(["git", "init", "--quiet", str(clone)], check=True)
            git(clone, "fetch", "--quiet", "--no-tags", "--depth=1", str(original), CODEX_BASE)
            git(clone, "checkout", "--quiet", "--detach", CODEX_BASE)
            clone.rename(source)
    if Path(git(source, "rev-parse", "--show-toplevel")) != source or git(source, "status", "--porcelain"):
        raise ValueError(f"Expected a clean benchmark checkout at {source}")
    with tempfile.TemporaryDirectory(dir=inputs) as temporary:
        stamp = git(source, "show", "-s", "--format=%ct", CODEX_BASE) + " +0000"
        env = os.environ | {
            "GIT_INDEX_FILE": str(Path(temporary) / "index"),
            "GIT_AUTHOR_NAME": "Ohm benchmark fixture",
            "GIT_COMMITTER_NAME": "Ohm benchmark fixture",
            "GIT_AUTHOR_EMAIL": "benchmark@users.noreply.github.com",
            "GIT_COMMITTER_EMAIL": "benchmark@users.noreply.github.com",
            "GIT_AUTHOR_DATE": stamp,
            "GIT_COMMITTER_DATE": stamp,
        }
        git(source, "read-tree", CODEX_BASE, env=env)
        git(source, "apply", "--cached", str(patch), env=env)
        tree = git(source, "write-tree", env=env)
        commit = git(source, "-c", "commit.gpgSign=false", "commit-tree", tree, "-p", CODEX_BASE, "-m",
                     "Apply the frozen Codex lint policy for Rust 1.100 benchmarks", env=env)
    if git(source, "diff", "--name-only", CODEX_BASE, commit) != "codex-rs/Cargo.toml":
        raise ValueError("Unexpected change to the Codex command fixture")
    previous = git(source, "rev-parse", "HEAD")
    if previous not in (CODEX_BASE, commit):
        raise ValueError(f"Unexpected benchmark checkout revision {previous}")
    if previous != commit:
        git(source, "checkout", "--quiet", "--detach", commit)
    return source, commit, tree


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark-root", type=Path, required=True, help="Dedicated directory containing the Codex benchmark outputs")
    parser.add_argument("--codex-source", type=Path, required=True, help="Local source containing the recorded Codex command revision")
    parser.add_argument("--archive", type=Path, help=f"Previously fetched {CRATE}.crate")
    args = parser.parse_args()
    root, original = args.benchmark_root.resolve(), args.codex_source.resolve()
    if root.is_relative_to(original) or original.is_relative_to(root / "compatibility"):
        raise ValueError("Choose a benchmark output directory separate from the source checkout")
    inputs = root / "compatibility"
    inputs.mkdir(exist_ok=True, parents=True)
    if args.archive:
        archive = args.archive
    else:
        cargo_home = Path(os.environ.get("CARGO_HOME", Path.home() / ".cargo"))
        archives = sorted((cargo_home / "registry/cache").glob(f"*/{CRATE}.crate"))
        archive = next((p for p in archives if sha256(p) == CRATE_DIGEST), None)
        if archive is None:
            parser.error(f"Fetch the recorded Codex dependencies or pass --archive for {CRATE}")
    crate = prepare_crate(archive, inputs)
    patch = PATCHES / "rust-1.100-codex-clippy.patch"
    source, commit, tree = prepare_command_source(original, inputs, patch)
    config = root / ".cargo/config.toml"
    config.parent.mkdir(exist_ok=True)
    contents = "paths = " + json.dumps([str(crate)]) + "\n"
    if config.with_suffix("").exists() or (config.exists() and config.read_text() != contents):
        raise ValueError(f"Conflicting Cargo configuration in {config.parent}")
    if not config.exists():
        config.write_text(contents)
    receipt = {
        "codex_revision": CODEX_BASE,
        "codex_base_tree": git(source, "rev-parse", CODEX_BASE + "^{tree}"),
        "codex_command_source": str(source),
        "codex_command_commit": commit,
        "codex_command_tree": tree,
        "codex_lock_sha256": sha256(source / "codex-rs/Cargo.lock"),
        "codex_patch_sha256": sha256(patch),
        "allocative_fix": "https://github.com/meta/buck2/commit/" + UPSTREAM_FIX,
        "allocative_crate_sha256": CRATE_DIGEST,
        "allocative_patch_sha256": sha256(ALLOCATIVE_PATCH),
        "allocative_updated_files": FIXED_FILES,
        "allocative_path": str(crate),
        "cargo_config_sha256": sha256(config),
    }
    body = json.dumps(receipt, sort_keys=True, indent=2) + "\n"
    (inputs / "codex-1.100.json").write_text(body)
    print(body, end="")


if __name__ == "__main__":
    main()
