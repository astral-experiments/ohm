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
SIGNED = "c79998a5cd143c445a4b2528f20953b176a65c5d"
BASE = "4e7c5b1f765b24ccd585d8ddb7eeae99a02b514e"
FORWARD = "96e6c29c1ed9bf7229ef3b89843712139529cd10"
COMBINED = "b79ec99c44772853c313161bee2bbfaecc80e0de"
HISTORICAL_F = "e420faa7fc34004b5e56b2c9f1456ae2ee5eab50"
HISTORICAL_C = "19d9b2a1d88e470ea2bea2e29b3b65a74ab08850"
SIGNED_TREE = "77ad1e80afc956a830491544d43695ec699fac2e"
COMPILER = "b429aa02503b16993d9b8f94a6ab17f4f3bfaa01"
LIBRARY = "4f7a8f755164dc68fff80790db8a844ae030fd03"
BOOT = "1dcf3e6b142ba5c132f7a2370dffa6ba090b15e1"
LIVE_PACK = "12277c6b2c405ea921acf59f7a1ed94eee5f4a069b8dc777c6408d49e998759f"
TWO_DOT = "fb920ee153c81895b3265fe729a693968dd68e3258ef24568b6b51c8d10e9971"
LIVE_TREES = {
    "P": (BASE, "d0647532bd782f92e3155bb0158de5a3c9b339bb", COMPILER),
    "F": (
        FORWARD,
        "611c96dce4a45e85551e12418bbdf262181aa4d8",
        "d6974700d89c4081ce287a1f798ce516d17e2950",
    ),
    "C": (
        COMBINED,
        "b0b1a3f38c1cf85dc79f87e2be7fd4429d9c5c37",
        "186b90f52fbc633bcd7caa0b16bced5e91553a33",
    ),
}
FORWARD_TEST = "ohm-derived-forwarder-cgus"
CALLABLE_TEST = "ohm-caller-drop-family"
PRODUCT = "compiler/rustc_monomorphize/src/partitioning.rs"
FTEST = {"tests/run-make/" + FORWARD_TEST + "/" + n for n in ("lib.rs", "main.rs", "rmake.rs")}
KTEST = {"tests/run-make/" + CALLABLE_TEST + "/" + n for n in ("fixture.rs", "rmake.rs")}
FIELDS = {
    "tree": "^{tree}",
    "compiler": ":compiler",
    "library": ":library",
    "tests": ":tests",
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


def two_dot(repo, left, right):
    return git(repo, "diff", "--binary", "--full-index", "--no-renames", left, right)


def live_base(repo, packet):
    raw = (packet / "live-over-signed.pack").read_bytes()
    need(len(raw) == 112293 and digest(raw) == LIVE_PACK, "corrupt live-base pack")
    git(repo, "index-pack", "--stdin", data=raw)
    need(
        obj(repo, SIGNED + "^{tree}") == SIGNED_TREE
        and obj(repo, BASE + "^{tree}") == LIVE_TREES["P"][1],
        "wrong signed or live checkout",
    )
    need(
        git(repo, "rev-list", "--count", BASE, "^" + SIGNED).strip() == b"263", "incomplete live history"
    )
    git(repo, "merge-base", "--is-ancestor", "f0750c162dc7f095b1c8c0caa9ca3894359404a1", BASE)
    need(digest(two_dot(repo, SIGNED, BASE)) == TWO_DOT, "actual signed/live two-dot difference changed")


def validate(repo, reg, require_combined):
    actual = {role: identity(repo, row["commit"]) for role, row in reg["roles"].items()}
    need(actual == reg["roles"], "source Git object or tree differs")
    need("C" in actual or not require_combined, "combined source is intentionally unenrolled")
    for k, a in actual.items():
        need((a["commit"], a["tree"], a["compiler"]) == LIVE_TREES[k], "wrong reviewed " + k + " source")
        need(a["library"] == LIBRARY and a["bootstrap"] == BOOT, "library or bootstrap diff")
    need(
        obj(repo, FORWARD + "^") == BASE
        and obj(repo, BASE + ":compiler") == obj(repo, SIGNED + ":compiler"),
        "wrong live compiler parent",
    )
    need(
        reg["historical"] == {"signed": SIGNED, "forwarder": HISTORICAL_F, "combined": HISTORICAL_C},
        "historical controls differ",
    )
    need(
        obj(repo, HISTORICAL_F + ":compiler") == "cee5a54f537678194263fed0e5f4167b31cee3a3"
        and obj(repo, HISTORICAL_C + ":compiler") == LIVE_TREES["C"][2],
        "signed-source control differs",
    )
    need(files(repo, FORWARD) == FTEST | {PRODUCT}, "wrong isolated forwarder paths")
    if "C" in actual:
        need(
            obj(repo, COMBINED + "^") == FORWARD and files(repo, COMBINED) == FTEST | KTEST | {PRODUCT},
            "wrong combined parent or paths",
        )
        for k in ("compiler", "library", "tests"):
            need(
                obj(repo, HISTORICAL_C + ":" + k) == actual["C"][k],
                "final live and historical " + k + " differ",
            )
        need(
            digest(two_dot(repo, HISTORICAL_C, COMBINED)) == TWO_DOT,
            "live C and signed C differ beyond the two original files",
        )
        for head in (FORWARD, COMBINED):
            need(
                obj(repo, head + ":tests/run-make/" + FORWARD_TEST)
                == "5f831d1d8a97cc0736f57fe3e955952ecbfe79ab",
                "missing exact forwarder coverage case",
            )
        need(
            obj(repo, COMBINED + ":tests/run-make/" + CALLABLE_TEST)
            == "f0c04d3a6302bbe1ec430d512303e8c4761764b3",
            "missing exact sole/mixed HRTB fixtures",
        )
    return actual


def enroll(repo, packet, combined):
    packet.mkdir(exist_ok=True)
    roles = {"P": BASE, "F": FORWARD}
    if combined:
        need(len(combined) == 40 and obj(repo, combined) == combined, "full combined commit required")
        roles["C"] = combined
    reg = {
        "historical": {"signed": SIGNED, "forwarder": HISTORICAL_F, "combined": HISTORICAL_C},
        "roles": {k: identity(repo, v) for k, v in roles.items()},
        "steps": [],
    }
    validate(repo, reg, False)
    commits = (
        git(
            repo,
            "rev-list",
            "--reverse",
            "--topo-order",
            HISTORICAL_C,
            *list(roles.values())[1:],
            "^" + SIGNED,
            "^" + BASE
        )
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
        need(parents and parents[0] in {SIGNED, BASE, *commits}, "foreign parent")
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
    live_base(repo, packet)
    known = {SIGNED, BASE}
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
