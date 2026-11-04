"""Replay the two actual #28392 file buffers, retaining the original index and HEAD."""
import hashlib
import os
from pathlib import Path
import stat
import subprocess

OLD = "f3280423f6c535690287e8169c25929f8d6433ce"
NEW = "d136bd8d002a648de5f344df602e492658306f1e"
FILES = ("crates/ruff/src/args.rs", "docs/configuration.md")


def check(condition, description):
    if not condition:
        raise ValueError(description)


def git(root, *args):
    return subprocess.check_output(["git", "--no-optional-locks", "-C", root, *args])


def head(root):
    path = Path(os.fsdecode(git(root, "rev-parse", "--absolute-git-dir").rstrip())) / "HEAD"
    value = path.read_bytes()
    st = path.lstat()
    check(stat.S_ISREG(st.st_mode) and value == (OLD + "\n").encode(), "expected detached original HEAD")
    return {"value": value.decode(), "device": st.st_dev, "inode": st.st_ino, "mtime_ns": st.st_mtime_ns}


def validate(root, state, full=False):
    check(state in (OLD, NEW) and git(root, "rev-parse", "HEAD").decode().strip() == OLD, "moved or unknown git HEAD")
    check(git(root, "diff", "--cached", "--no-ext-diff", OLD, "--") == b"", "modified real Git index")
    check(git(root, "diff", "--no-ext-diff", state, "--") == b"", "tracked working tree differs from registered state")
    check(git(root, "ls-files", "--others", "--exclude-standard", "-z") == b"", "unexpected untracked files")
    diff = git(root, "diff", "--name-only", "-z", OLD, "--").split(b"\0")[:-1]
    check(diff == ([s.encode() for s in FILES] if state == NEW else []), "unexpected changed paths")
    rows = {}
    for name in FILES:
        f = root / name
        data = f.read_bytes()
        check(stat.S_ISREG(f.lstat().st_mode) and data == git(root, "cat-file", "blob", state + ":" + name), "working bytes differ")
        rows[name] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "git_blob": git(root,"rev-parse",state+":"+name).decode().strip()}
    result = {"head": head(root), "content": state, "tree": git(root,"rev-parse",state+"^{tree}").decode().strip(),
              "real_index_matches": OLD, "changed_paths": list(map(os.fsdecode,diff)), "actual_source_files": rows}
    if full:
        # Verify the bytes and Git file mode in every tracked path, independently of Git's stat refresh.
        total = 0
        n = 0
        crlf_files = []
        commitment = hashlib.sha256()
        entries = git(root, "ls-tree", "-rz", state).split(b"\0")
        check(entries.pop() == b"", "truncated tree")
        for entry in entries:
            header, path = entry.split(b"\t", 1)
            mode, kind, oid = header.split()
            check(kind == b"blob" and mode in (b"100644", b"100755", b"120000"), ("unsupported tree entry", entry))
            f = root / os.fsdecode(path)
            st = f.lstat()
            if mode == b"120000":
                check(stat.S_ISLNK(st.st_mode), ("not a symlink", path))
                data = os.readlink(os.fsencode(f))
            else:
                check(stat.S_ISREG(st.st_mode) and bool(st.st_mode & stat.S_IXUSR) == (mode == b"100755"), ("changed file mode", path))
                data = f.read_bytes()
            actual = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest().encode()
            if actual != oid:
                name = os.fsdecode(path)
                attrs = git(root, "check-attr", "-z", "text", "eol", "filter", "working-tree-encoding", "--", name).split(b"\0")
                check(len(attrs)==13 and attrs[2] in (b"set",b"auto") and attrs == [path,b"text",attrs[2],path,b"eol",b"crlf",path,b"filter",b"unspecified",path,b"working-tree-encoding",b"unspecified",b""],
                      ("working bytes differ outside a registered CRLF checkout", path))
                stored = git(root,"cat-file","blob",state+":"+name)
                check(b"\r" not in stored and stored.replace(b"\n",b"\r\n")==data, ("incorrect physical CRLF file", path))
                crlf_files.append(name)
            total += len(data)
            n += 1
            commitment.update(mode + b"\0" + path + b"\0" + hashlib.sha256(data).digest())
        result["tracked"] = {"files":n, "bytes":total, "sha256_mode_path_content":commitment.hexdigest(),"crlf_checkout_files":crlf_files}
    return result


def apply(root):
    old = validate(root, OLD)
    changed = git(root, "diff-tree", "--no-commit-id", "--no-renames", "--name-only", "-r", "-z", OLD, NEW).split(b"\0")
    check(changed == [s.encode() for s in FILES] + [b""], "different recorded historical patch")
    for name in FILES:
        (root / name).write_bytes(git(root, "cat-file", "blob", NEW + ":" + name))
    new = validate(root, NEW, full=True)
    check(new["head"] == old["head"], "HEAD physically changed while applying source buffers")
    return new
