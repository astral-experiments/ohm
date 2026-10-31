"""Transport and reconstruct the literal post-release commits without a mutable fork ref."""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
BASE = "c79998a5cd143c445a4b2528f20953b176a65c5d"
COMBINED = "caf6ddd8b4a7a19acb140f2a030cc5d2035aa424"
FORWARD = "e420faa7fc34004b5e56b2c9f1456ae2ee5eab50"
CALLABLE = "f8f32cace6a079c4e9c6a08166a86e572fd1f4fb"
TREE = "77ad1e80afc956a830491544d43695ec699fac2e"
COMPILER = "b429aa02503b16993d9b8f94a6ab17f4f3bfaa01"
LIBRARY = "4f7a8f755164dc68fff80790db8a844ae030fd03"
BOOT = "1dcf3e6b142ba5c132f7a2370dffa6ba090b15e1"
FORWARD_TEST = "ohm-derived-forwarder-cgus"
CALLABLE_TEST = "ohm-caller-drop-family"
PRODUCT = "compiler/rustc_monomorphize/src/partitioning.rs"
FTEST = {"tests/run-make/" + FORWARD_TEST + "/" + n for n in ("lib.rs", "main.rs", "rmake.rs")}
KTEST = {"tests/run-make/" + CALLABLE_TEST + "/" + n for n in ("fixture.rs", "rmake.rs")}
FIELDS = {
    "tree": "^{tree}",
    "compiler": ":compiler",
    "library": ":library",
    "bootstrap": ":src/bootstrap",
}


def need(ok, msg):
    if not ok:
        raise ValueError(msg)


def git(repo, *args, data=None, env=None):
    return subprocess.check_output(
        ["git", "-C", str(repo), *args],
        input=data,
        env=dict(os.environ if env is None else env, GIT_NO_LAZY_FETCH="1"),
    )


def obj(repo, ref):
    return git(repo, "rev-parse", "--verify", ref).decode().strip()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def files(repo, head):
    return set(git(repo, "diff", "--name-only", BASE, head).decode().splitlines())


def identity(repo, head):
    return {"commit": head, **{k: obj(repo, head + suffix) for k, suffix in FIELDS.items()}}


def validate(repo, reg, require_combined):
    actual = {role: identity(repo, item["commit"]) for role, item in reg["roles"].items()}
    need(actual == reg["roles"], "source Git object or tree differs")
    need(
        actual["P"]
        == {"commit": BASE, "tree": TREE, "compiler": COMPILER, "library": LIBRARY, "bootstrap": BOOT},
        "wrong signed source",
    )
    need(
        actual["F"]["commit"] == FORWARD
        and actual["F"]["tree"] == "adfbc281b424f8421de30fa9a178e9e441feb9ab",
        "wrong forwarder commit",
    )
    need(
        actual["K"]["commit"] == CALLABLE
        and actual["K"]["tree"] == "876055ca2a21aff0ce49ab1349820ca7e178b76b",
        "wrong standalone callable",
    )
    need(
        all(a["library"] == LIBRARY and a["bootstrap"] == BOOT for a in actual.values()),
        "library or bootstrap diff",
    )
    need(
        files(repo, FORWARD) == FTEST | {PRODUCT} and files(repo, CALLABLE) == KTEST | {PRODUCT},
        "unexpected standalone source path",
    )
    need("C" in actual or not require_combined, "combined source is intentionally unenrolled")
    if "C" in actual:
        child = actual["C"]["commit"]
        need(
            child == COMBINED
            and actual["C"]["tree"] == "0a87f43a4b3c92f9648d54d0d7fff7a292e3bd10"
            and actual["C"]["compiler"] == "1be646d90d0024e0ab0334f1de4c3578f83535ec",
            "wrong combined candidate",
        )
        need(files(repo, child) == FTEST | KTEST | {PRODUCT}, "combined source changed another path")
        coverage = "tests/run-make/" + FORWARD_TEST + "/rmake.rs"
        need(
            obj(repo, child + ":" + coverage) == "e4ba16b96b6dfade1d087414211d524d56c53510",
            "combined coverage fixture differs",
        )
        for role, paths in ((FORWARD, FTEST - {coverage}), (CALLABLE, KTEST)):
            for path in paths:
                need(
                    obj(repo, role + ":" + path) == obj(repo, child + ":" + path),
                    "source fixture differs: " + path,
                )
        need(
            len({actual[r]["compiler"] for r in ("P", "F", "K", "C")}) == 4,
            "combined compiler does not differ from its parts",
        )
    return actual


def enroll(repo, packet, combined):
    packet.mkdir(exist_ok=True)
    roles = {"P": BASE, "F": FORWARD, "K": CALLABLE}
    if combined:
        need(len(combined) == 40 and obj(repo, combined) == combined, "full combined commit required")
        roles["C"] = combined
    reg = {"roles": {k: identity(repo, v) for k, v in roles.items()}, "steps": []}
    validate(repo, reg, False)
    commits = (
        git(repo, "rev-list", "--reverse", "--topo-order", *list(roles.values())[1:], "^" + BASE)
        .decode()
        .splitlines()
    )
    need(2 <= len(commits) <= 16, "unexpected ancestry size")
    for commit in commits:
        whole = git(repo, "cat-file", "commit", commit)
        parents = [
            row.split()[1].decode()
            for row in whole.split(b"\n\n", 1)[0].splitlines()
            if row.startswith(b"parent ")
        ]
        need(parents and parents[0] in {BASE, *commits}, "foreign parent")
        diff = git(
            repo, "diff", "--no-ext-diff", "--binary", "--full-index", "--no-renames", parents[0], commit
        )
        rec = {"head": commit, "tree": obj(repo, commit + "^{tree}"), "parents": parents}
        for name, raw in [("commit", whole), ("patch", diff)]:
            payload = gzip.compress(raw, mtime=0)
            (packet / (commit + "." + name + ".gz")).write_bytes(payload)
            rec[name] = digest(payload)
        reg["steps"].append(rec)
    (packet / "registration.json").write_text(json.dumps(reg, sort_keys=True, indent=2) + "\n")


def reconstruct(repo, packet, required):
    reg = json.loads((packet / "registration.json").read_text())
    known = {BASE}
    with tempfile.TemporaryDirectory() as temp:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(temp) / "index"))
        for rec in reg["steps"]:
            need(set(rec["parents"]) <= known, "missing source parent")
            blobs = {}
            for key in ("commit", "patch"):
                data = (packet / (rec["head"] + "." + key + ".gz")).read_bytes()
                need(digest(data) == rec[key], "corrupt packed " + key)
                blobs[key] = gzip.decompress(data)
            lines = blobs["commit"].split(b"\n\n", 1)[0].splitlines()
            need(
                lines[0] == b"tree " + rec["tree"].encode()
                and [l[7:].decode() for l in lines if l.startswith(b"parent ")] == rec["parents"],
                "incorrect raw commit header",
            )
            git(repo, "read-tree", rec["parents"][0], env=env)
            if blobs["patch"]:
                cmd = ["apply", "--cached", "--binary", "--whitespace=error"]
                git(repo, *cmd, "--check", "-", data=blobs["patch"], env=env)
                git(repo, *cmd, "-", data=blobs["patch"], env=env)
            need(
                git(repo, "write-tree", env=env).decode().strip() == rec["tree"],
                "reconstructed source tree differs",
            )
            need(
                git(repo, "hash-object", "-t", "commit", "-w", "--stdin", data=blobs["commit"])
                .decode()
                .strip()
                == rec["head"],
                "reconstructed commit differs",
            )
            known.add(rec["head"])
    need({v["commit"] for v in reg["roles"].values()} <= known, "role not reconstructed")
    return validate(repo, reg, required)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["enroll", "verify", "verify-plan"])
    parser.add_argument("repo", type=Path)
    parser.add_argument("--packet", type=Path, default=HERE / "packet")
    parser.add_argument("--combined")
    arg = parser.parse_args()
    if arg.mode == "enroll":
        enroll(arg.repo, arg.packet, arg.combined)
    else:
        print(
            json.dumps(reconstruct(arg.repo, arg.packet, arg.mode == "verify"), indent=2, sort_keys=True)
        )
