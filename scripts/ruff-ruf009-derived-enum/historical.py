"""Bind the exact original #19021 sources, locked Git inputs and the ordinary Cargo client."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import stat

HERE = Path(__file__).resolve().parent
PORT = json.loads((HERE / "historical-source.json").read_bytes())
REVISIONS = PORT["revisions"]
REG = json.loads((HERE / "registration.json").read_bytes())


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def git(path, *args):
    return subprocess.check_output(["git", "--no-optional-locks", "-C", path, *args], text=True).strip()


def enter(path):
    old, new = (REVISIONS[role]["commit"] for role in ("buggy", "fixed"))
    assert git(path, "rev-parse", "HEAD") == new and git(path, "rev-parse", new + "^") == old
    assert not git(path, "status", "--porcelain")
    changed = git(path, "diff", "--name-only", old, new, "--").splitlines()
    for record in REVISIONS.values():
        rev = record["commit"]
        assert git(path, "rev-parse", rev + "^{tree}") == record["tree"]
        assert sorted(changed) == sorted(record["files"]) and len(changed) == 3
        for rel, info in record["files"].items():
            raw = subprocess.check_output(["git", "-C", path, "show", rev + ":" + rel])
            assert git(path, "rev-parse", rev + ":" + rel) == info["blob"] and hashlib.sha256(raw).hexdigest() == info["sha256"]
    git(path, "switch", "--detach", old)
    assert state(path) == "buggy"


def state(path, desired=None):
    assert git(path, "rev-parse", "HEAD") == REVISIONS["buggy"]["commit"]
    assert sha(path / "Cargo.lock") == REG["lock"]["sha256"]
    assert not git(path, "ls-files", "--others", "--exclude-standard")
    current, = [key for key in REVISIONS if sha(path / PORT["path"]) == PORT[key]]
    record = REVISIONS[current]
    assert all(sha(path / rel) == info["sha256"] for rel, info in record["files"].items())
    for cmd in (["diff", "--quiet", record["commit"], "--"], ["diff", "--cached", "--quiet", record["commit"], "--"]):
        git(path, *cmd)
    if desired is not None and desired != current:
        target = REVISIONS[desired]
        git(path, "restore", "--source=" + target["commit"], "--staged", "--worktree", "--", *target["files"])
        assert git(path, "write-tree") == target["tree"]
        return state(path)
    return current


def git_sources(cargo, locked):
    suffixes = {source.split("#")[-1] for source in locked.values()}
    found = {}
    for root in sorted((cargo / "git/checkouts").glob("*/*")):
        if not (root / ".git").exists():
            continue
        head = git(root, "rev-parse", "HEAD")
        assert head in suffixes and head not in found
        assert not git(root, "diff", "--name-status", "HEAD", "--")
        inventory = hashlib.sha256()
        count = 0
        for entry in subprocess.check_output(["git", "-C", root, "ls-files", "-s", "-z"]).rstrip(b"\0").split(b"\0"):
            mode_oid, rel = entry.split(b"\t", 1); mode, blob, stage = mode_oid.split()
            assert stage == b"0"
            path = root / os.fsdecode(rel)
            if mode == b"120000":
                assert path.is_symlink()
                body = os.fsencode(os.readlink(path))
            else:
                assert mode in (b"100755", b"100644") and path.is_file() and not path.is_symlink()
                assert bool(path.stat().st_mode & 0o111) == (mode == b"100755")
                body = path.read_bytes()
            git_object = b"blob " + str(len(body)).encode() + b"\0" + body
            if hashlib.sha1(git_object).hexdigest().encode() != blob:
                canonical = subprocess.check_output(["git", "-C", root, "hash-object", "--path=" + os.fsdecode(rel), "--stdin"], input=body)
                assert canonical.strip() == blob
            inventory.update(mode + b" " + rel + b"\0" + hashlib.sha256(body).digest())
            count += 1
        found[head] = {"tree":git(root,"rev-parse","HEAD^{tree}"),"physical_files":count,"physical_sha256":inventory.hexdigest()}
    assert set(found) == suffixes
    return found


def cargo_client(root, receipt, artifacts):
    bind = json.loads((HERE / "client.json").read_bytes())
    run = artifacts.api("actions/runs/" + str(bind["run"]))
    assert run["head_sha"]==bind["head"] and run["conclusion"]=="success" and run["run_attempt"]==1 and run["head_branch"]==bind["branch"]
    folder = root / "cargo-client"; folder.mkdir()
    files, archive = artifacts.download(bind["run"], bind["artifact"]["name"], folder)
    assert archive["id"] == bind["artifact"]["id"] and archive["bytes"]==bind["artifact"]["bytes"] and archive["sha256"]==bind["artifact"]["sha256"]
    b = files / "candidate-cargo"
    ident = json.loads((files / "factory-identity.json").read_bytes())
    assert ident["source"] == bind["revision"] and ident["tree"] == bind["tree"] and ident["inventory"] == bind["physical_source"]
    assert sha(b) == ident["binary_sha256"] == bind["binary_sha256"] and b.stat().st_size == ident["bytes"]
    assert bind["revision"] in ident["version"] and ident["baseline_fix"] == bind["parent"]
    b.chmod(0o755)
    (receipt / "client-native.json").write_text(json.dumps({"binding":bind,"constructor":ident,"archive":archive},indent=1,sort_keys=True)+"\n")
    return b


def with_client(sdk, root, name, client, original_files):
    view = root / ("capability-sdk-" + name)
    subprocess.run(["cp", "-a", "--reflink=auto", sdk, view], check=True)
    assert sha(view / "bin/cargo") == original_files["bin/cargo"]
    installed = view / "bin/cargo"
    donor = sdk / "bin/cargo"
    assert not installed.is_symlink() and not installed.samefile(donor)
    mode = stat.S_IMODE(donor.stat().st_mode)
    assert stat.S_IMODE(installed.stat().st_mode) == mode and mode & stat.S_IXUSR
    installed.chmod(mode | stat.S_IWUSR)
    try:
        shutil.copyfile(client, installed)
    finally:
        installed.chmod(mode)
    assert stat.S_IMODE(installed.stat().st_mode) == stat.S_IMODE(donor.stat().st_mode) == mode
    actual = {rel:sha(view / rel) for rel in original_files}
    assert [k for k in actual if actual[k] != original_files[k]] == ["bin/cargo"]
    assert actual["bin/cargo"] == sha(client) and sha(sdk / "bin/cargo") == original_files["bin/cargo"]
    return view, actual
