"""Verify every tracked input of the release's composite Rust/tool checkout."""

import hashlib
import os
from pathlib import Path
import stat
import subprocess


TOOLS = {
    "src/tools/clippy": (
        "0d76dc1f4fe7ffb86ee5e1a8a9cc4d6bef1d1bf6",
        "597138f8e9a24972dd23acd15a8eee063c3a39f9",
    ),
    "src/tools/rustfmt": (
        "3c9620c92b01e6c393324729c4861823cc3676e2",
        "48c3ccd52f999a69778e9af7930b1d0408c7213c",
    ),
}
REQUIRED = {"library/backtrace", "src/tools/cargo"}


def need(value, why):
    if not value:
        raise ValueError(str(why))


def git(repo, *args):
    return subprocess.check_output(["git", "-C", repo, *args])


def tree(repo, rev):
    rows = {}
    for row in git(repo, "ls-tree", "-rz", "--full-tree", rev).split(b"\0")[:-1]:
        fields, name = row.split(b"\t", 1)
        mode, _, oid = fields.decode().split()
        name = os.fsdecode(name)
        need(name not in rows, name)
        rows[name] = mode, oid
    return rows


def blob(path, entry):
    mode, expected = entry
    info = path.lstat()
    actual = "120000" if stat.S_ISLNK(info.st_mode) else ("100755" if info.st_mode & 0o100 else "100644")
    need(
        (stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)) and actual == mode,
        f"wrong kind/mode: {path}",
    )
    h = hashlib.sha1(f"blob {info.st_size}\0".encode())
    if actual == "120000":
        h.update(os.fsencode(os.readlink(path)))
    else:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1 << 17), b""):
                h.update(chunk)
    need(h.hexdigest() == expected, f"wrong physical Git blob: {path}")


def checked(repo, revision, expected_tree, substitutions=None):
    substitutions = substitutions or {}
    need(
        not repo.is_symlink()
        and Path(os.fsdecode(git(repo, "rev-parse", "--show-toplevel").rstrip())).samefile(repo),
        f"wrong checkout root {repo}",
    )
    actual = git(repo, "rev-parse", "HEAD", "HEAD^{tree}").decode().splitlines()
    need(actual == [revision, expected_tree], (repo, "wrong revision/tree", actual))
    need(
        not git(repo, "diff", "--cached", "--no-ext-diff", "--raw", revision, "--"),
        f"modified Git index: {repo}",
    )
    paths = [".", *(f":(exclude){n}" for n in substitutions)]
    need(
        not git(
            repo,
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--ignore-submodules=none",
            "--",
            *paths,
        ),
        f"dirty source outside verified overlays: {repo}",
    )
    # ls-files without --exclude-standard includes even files matched by .gitignore.
    need(not git(repo, "ls-files", "--others", "-z", "--", *paths), f"unexpected untracked input: {repo}")
    entries = tree(repo, revision)
    links, nested, differences = {}, {}, {}
    for name, (head, tree_oid) in substitutions.items():
        original = {p[len(name) + 1 :]: mode for p, mode in entries.items() if p.startswith(name + "/")}
        need(original, f"expected a real tracked Rust subtree: {name}")
        for p in original:
            del entries[name + "/" + p]
        child = repo / name
        nested[name] = checked(child, head, tree_oid)
        want = tree(child, head)
        for p in sorted(original.keys() | want.keys()):
            if original.get(p) != want.get(p):
                differences[name + "/" + p] = [original.get(p), want.get(p)]
                if p not in want:
                    need(
                        not os.path.lexists(child / p), f"deleted release input remains present: {child / p}"
                    )
    for path, (mode, oid) in entries.items():
        target = repo / path
        if mode != "160000":
            blob(target, (mode, oid))
            continue
        if os.path.lexists(target):
            need(target.is_dir() and not target.is_symlink(), f"wrong gitlink type: {target}")
        if (target / ".git").exists():
            settings = git(target, "rev-parse", oid + "^{tree}").decode().strip()
            links[path] = checked(target, oid, settings)
        else:
            need(
                not target.exists() or not any(target.iterdir()), f"nonempty uninitialized gitlink: {target}"
            )
            links[path] = {"commit": oid, "populated": False}
    if substitutions:
        need(REQUIRED <= {p for p, v in links.items() if v["populated"]}, "missing required native sources")
    return {
        "commit": revision,
        "tree": expected_tree,
        "populated": True,
        "files": len(entries) - len(links),
        "gitlinks": links,
        "substitutions": nested,
        "authorized_differences": differences,
    }
