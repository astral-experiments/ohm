"""Install and independently check Ruff's public packed refs in the private study checkout."""

import io
import json
import os
import stat
import subprocess
import zipfile
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
ARCHIVE = "83677e87bc9b24a51b449a82efb60efacb42f775e2874b9d8e2f2a6b34ac18d2"
CARRIER = "a2ec33d5ce196d1a17cbb78ded57d3895480aabdef91fbd2ffc16a0dbb4e38a3"
TABLE = "c20afd3bc4bf7bf0e40f3ffef1ad46c86c37c15ce88a31cbcd52415641f928e9"
TABLE_BYTES = 117800
Y_RANGE = (46, 117)
A = "b5dba861cc38e3f7fb4524c9ceba3e01a474ea13"
B = "7b13f01ba1569887a25670820764b24c206da8e5"
X = "historical-parent"
Y = "historical-feature"
TREES = {
    A: "2b61306d708a211b3725c8d920e7590be6da41ad",
    B: "97ca36909f1ae8fa028b2c1f48f452fbdcdbbd4c",
}
LOCK = "839edc8250480bb523619b8d24bd57176a6e1f57c152cca85c5adc61ea5f94eb"
PUBLIC = "https://github.com/astral-sh/ruff.git"


def need(value, reason):
    if not value:
        raise ValueError(reason)


def digest(data):
    return sha256(data).hexdigest()


def git(repo, *args, stdin=None):
    # This helper runs after the source and registry acquisitions. Missing objects must fail.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        GIT_NO_LAZY_FETCH="1",
        GIT_OPTIONAL_LOCKS="0",
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL="/dev/null",
    )
    return subprocess.check_output(
        ["git", "-c", "protocol.allow=never", "-C", repo, *args],
        input=stdin,
        env=env,
        timeout=90,
    )


def inputs():
    raw = (HERE / "inputs/public-ruff-refs.zip").read_bytes()
    need(len(raw) == 521332 and digest(raw) == ARCHIVE, "different public ref archive")
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names = z.namelist()
        need(len(names) == len(set(names)) == 8, "different archive inventory")
        cert = z.read("receipt.json")
        need(digest(cert) == CARRIER, "different public Git acquisition")
        receipt = json.loads(cert)
        members = receipt["members"]
        need(
            set(names) == set(members) | {"receipt.json", "public-refs.tsv"},
            "extra archive member",
        )
        contents = {}
        for name, (length, expected) in members.items():
            need(
                z.getinfo(name).file_size == length <= 320_000,
                "wrong carrier member length",
            )
            contents[name] = z.read(name)
            need(digest(contents[name]) == expected, "wrong carrier member bytes")
        advert = z.read("public-refs.tsv")
    need(digest(advert) == receipt["advertisement"], "different public advertisement")
    public = {k: v for v, k in (line.split(b"\t") for line in advert.splitlines())}
    refs = [
        line
        for line in contents["packed-refs"].splitlines()
        if not line.startswith(b"#")
    ]
    need(
        digest(b"\n".join(refs) + b"\n") == receipt["subset"],
        "different public ref subset",
    )
    pairs = [tuple(line.split(b" ", 1)) for line in refs]
    need(
        len(public) == 1935
        and len(pairs) == 1291
        and len({v for v, _ in pairs}) == 1286
        and all(
            k.startswith(b"refs/remotes/origin/")
            and public.get(k.replace(b"refs/remotes/origin/", b"refs/heads/", 1)) == v
            for v, k in pairs
        ),
        "non-public ref or missing real object",
    )
    return contents, pairs


def add_refs(repo, contents, pairs):
    private = repo / ".git"
    old = (private / "shallow").read_bytes()
    need(old.splitlines() == [A.encode()], "unexpected existing shallow boundary")
    need(
        not git(repo, "remote") and not (private / "objects/info/alternates").exists(),
        "unexpected source or alternate object store",
    )
    git(repo, "remote", "add", "packed-source", PUBLIC)
    git(repo, "config", "remote.packed-source.promisor", "true")
    git(repo, "config", "remote.packed-source.partialCloneFilter", "tree:0")
    for name, data in contents.items():
        if name.startswith("objects/pack/"):
            dest = private / name
            with dest.open("xb") as f:
                f.write(data)
            need(dest.read_bytes() == data, "different installed Git object pack")
    union = sorted(set(old.splitlines()) | set(contents["shallow"].splitlines()))
    lock = private / "shallow.lock"
    with lock.open("xb") as f:
        f.write(b"\n".join(union) + b"\n")
    need((private / "shallow").read_bytes() == old, "historical shallow boundary moved")
    lock.replace(private / "shallow")
    git(
        repo,
        "update-ref",
        "--stdin",
        stdin=b"start\n"
        + b"".join(b"create " + k + b" " + v + b"\n" for v, k in pairs)
        + b"prepare\ncommit\n",
    )
    actual = git(
        repo, "for-each-ref", "--format=%(objectname) %(refname)", "refs/remotes/origin"
    ).splitlines()
    need(actual == [v + b" " + k for v, k in pairs], "installed public refs differ")
    oids = sorted({v for v, _ in pairs})
    actual = git(
        repo,
        "cat-file",
        "--batch-check=%(objectname) %(objecttype)",
        stdin=b"\n".join(oids) + b"\n",
    ).splitlines()
    need(actual == [v + b" commit" for v in oids], "missing public commit body")
    git(
        repo,
        "fsck",
        "--no-progress",
        "--connectivity-only",
        "--no-reflogs",
        "--no-dangling",
    )


def install(repo):
    repo = Path(repo)
    root = Path(os.environ["RUNNER_TEMP"]).resolve() / "ohm-branch-object-qa"
    need(
        repo == repo.resolve() == root / "ruff"
        and (root / "work/.owned-by-packed-study").read_text() == str(root),
        "outside registered private Ruff checkout",
    )
    need(
        stat.S_ISDIR((repo / ".git").lstat().st_mode)
        and not git(repo, "status", "--porcelain"),
        "dirty or linked input checkout",
    )
    for ref, rev in ((X, A), (Y, B)):
        need(
            git(repo, "rev-parse", "refs/heads/" + ref).strip().decode() == rev,
            "different historical branch",
        )
        need(
            git(repo, "rev-parse", rev + "^{tree}").strip().decode() == TREES[rev],
            "different historical source tree",
        )
    need(
        digest((repo / "Cargo.lock").read_bytes()) == LOCK,
        "different complete Cargo input",
    )
    contents, pairs = inputs()
    add_refs(repo, contents, pairs)
    git(repo, "switch", "-q", Y)
    git(repo, "pack-refs", "--all", "--prune")
    # Keep Y packed. Recreate X through Git, even when it was already at A before packing.
    git(repo, "update-ref", "refs/heads/" + X, B, A)
    git(repo, "update-ref", "refs/heads/" + X, A, B)
    result = snapshot(repo, Y, B)
    return {
        "archive": ARCHIVE,
        "carrier": CARRIER,
        "refs": 1291,
        "commits": 1286,
        "initial": result,
    }


def watched_names(ref):
    need(ref in (X, Y), "unknown historical branch")
    return (
        ("HEAD", "packed-refs", "refs/heads")
        if ref == Y
        else ("HEAD", "refs/heads/" + X)
    )


def file_record(path, directory=False):
    s = path.lstat()
    need(
        (stat.S_ISDIR if directory else stat.S_ISREG)(s.st_mode),
        "different watched path kind",
    )
    record = {
        "type": "dir" if directory else "file",
        "dev": s.st_dev,
        "ino": s.st_ino,
        "mtime_ns": s.st_mtime_ns,
        "ctime_ns": s.st_ctime_ns,
    }
    if not directory:
        record["sha256"] = digest(path.read_bytes())
    after = path.lstat()
    need(
        (s.st_dev, s.st_ino, s.st_mtime_ns, s.st_ctime_ns, s.st_size)
        == (
            after.st_dev,
            after.st_ino,
            after.st_mtime_ns,
            after.st_ctime_ns,
            after.st_size,
        ),
        "watched path changed while reading",
    )
    return record


def snapshot(repo, short_ref, revision):
    repo = Path(repo)
    private = repo / ".git"
    need(
        git(repo, "symbolic-ref", "--short", "HEAD").decode().strip() == short_ref
        and git(repo, "rev-parse", "HEAD").decode().strip() == revision,
        "different checked-out ref",
    )
    y = private / "refs/heads" / Y
    need(not y.exists() and not y.is_symlink(), "Y unexpectedly loose")
    table = (private / "packed-refs").read_bytes()
    row = (B + " refs/heads/" + Y + "\n").encode()
    need(
        table.count(row) == 1
        and table.find(row) == Y_RANGE[0]
        and len(row) == Y_RANGE[1] - Y_RANGE[0],
        "different packed Y row",
    )
    watched = {
        n: file_record(private / n, n == "refs/heads") for n in watched_names(short_ref)
    }
    result = {
        "ref": short_ref,
        "revision": revision,
        "y_loose": False,
        "table_sha256": digest(table),
        "table_bytes": len(table),
        "y_range": list(Y_RANGE),
        "watched": watched,
    }
    verify_snapshot(result, short_ref, revision)
    return result


def verify_snapshot(record, short_ref, revision):
    names = watched_names(short_ref)
    need(
        revision in TREES and (short_ref == X or revision == B),
        "impossible ref/revision",
    )
    need(
        set(record)
        == {
            "ref",
            "revision",
            "y_loose",
            "table_sha256",
            "table_bytes",
            "y_range",
            "watched",
        },
        "wrong Git witness fields",
    )
    need(
        (
            record["ref"],
            record["revision"],
            record["table_sha256"],
            record["table_bytes"],
            record["y_range"],
        )
        == (short_ref, revision, TABLE, TABLE_BYTES, list(Y_RANGE))
        and record["y_loose"] is False,
        "wrong table or loose-ref record",
    )
    watched = record["watched"]
    need(set(watched) == set(names), "wrong set of historical Ruff Git inputs")
    full = "refs/heads/" + short_ref
    hashes = {
        "HEAD": digest(("ref: " + full + "\n").encode()),
        "packed-refs": TABLE,
        full: digest((revision + "\n").encode()),
    }
    for name, item in watched.items():
        directory = name == "refs/heads"
        need(
            set(item)
            == {"type", "dev", "ino", "mtime_ns", "ctime_ns"}
            | (set() if directory else {"sha256"}),
            "wrong file observation",
        )
        need(
            item["type"] == ("dir" if directory else "file")
            and all(
                type(item[k]) is int and item[k] > 0
                for k in ("dev", "ino", "mtime_ns", "ctime_ns")
            ),
            "incorrect file type or identity",
        )
        if not directory:
            need(item["sha256"] == hashes[name], "different actual watched bytes")


def build_output(raw, repo, short_ref, revision):
    names = watched_names(short_ref)
    need(
        revision in TREES and (short_ref == X or revision == B),
        "impossible build-script revision",
    )
    prefix = "cargo:rerun-if-changed="
    root = Path(repo) / "crates/ruff/../../.git"
    lines = raw.splitlines()
    watched = [os.fsencode(prefix + str(root / n)) for n in names]
    need(
        [l for l in lines if l.startswith(prefix.encode())] == watched,
        "actual build-script watches differ",
    )
    marker = b"cargo::rustc-env=RUFF_COMMIT_HASH="
    need(
        [l for l in lines if l.startswith(marker)] == [marker + revision.encode()],
        "actual build-script commit differs",
    )
    return {"stdout_sha256": digest(raw), "watched": list(names), "revision": revision}
