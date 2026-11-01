"""Authenticate the literal-identity child; the existing E source capsule is the sole parent."""

from pathlib import Path
import hashlib, json, os, subprocess, sys

HERE = Path(__file__).resolve().parent
OLD = "393b4b05a4bfa3f531a36023846f86236a6b71a9"
NEW = "df2c077a113a709ab379c8ec34e62c94c7513325"
CARRIER_PARENT = "7b904161df80bffb2c6b41782fc314b17afdc788"
SOURCE_QA = "762fc25095e317ac5632ec835df3c7f9cfc64a64"
REF = "refs/heads/charlie/qa-ctfe-literal-identity-20261101"
TREE = "59ec1b8a5d8f7c446534fa8725281fd215f02164"
TEST = "rdr-public-hash-ctfe-literal-identity"
EXPECTED = {
    "compiler/rustc_incremental/src/persist/file_format.rs",
    "compiler/rustc_middle/src/mir/interpret/mod.rs",
    "compiler/rustc_middle/src/mir/interpret/tests.rs",
} | {"tests/run-make/" + TEST + "/" + n + ".rs" for n in ("rmake", "right", "lib", "main")}
SCHEMA = {
    "symbols.rs": "compiler/rustc_span/src/symbol.rs",
    "rmeta.rs": "compiler/rustc_metadata/src/rmeta/mod.rs",
}


def need(value, why):
    if not value:
        raise ValueError(why)


def sha(p):
    with Path(p).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def digest(b):
    return hashlib.sha256(b).hexdigest()


def save(p, data):
    with Path(p).open("x") as f:
        json.dump(data, f, sort_keys=True, indent=2)
        f.write("\n")


def git(repo, *args, body=None):
    return subprocess.check_output(["git", "--no-lazy-fetch", "-C", repo, *args], input=body)


def rev(repo, spec):
    return git(repo, "rev-parse", spec).decode().strip()


def job():
    need(
        os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
        and os.environ.get("GITHUB_REPOSITORY") == "astral-experiments/ohm"
        and os.environ.get("GITHUB_REF") == REF
        and os.environ.get("GITHUB_RUN_ATTEMPT") == "1"
        and os.environ.get("GITHUB_JOB") == "qualify"
        and os.environ.get("REVIEWED_HEAD") == os.environ["GITHUB_SHA"] == rev(HERE, "HEAD")
        and rev(HERE, "HEAD^") == CARRIER_PARENT,
        "foreign QA invocation",
    )


def validate(repo, install=False):
    import gzip

    data = json.loads((HERE / "inputs/product.json").read_bytes())
    pack = HERE / "inputs/child.pack"
    need(
        sha(HERE / "inputs/product.json")
        == "da527efa602a2fe443261e86fcb129bff30071c89647e2af3bbfedebdba06651"
        and data["parent"] == OLD
        and data["child"] == NEW
        and data["root"] == TREE
        and data["pack"]["bytes"] == pack.stat().st_size
        and data["pack"]["sha256"] == sha(pack),
        "source enrollment",
    )
    if install:
        git(repo, "index-pack", "--stdin", body=pack.read_bytes())
    need(
        rev(repo, NEW + "^") == OLD
        and rev(repo, NEW + "^{tree}") == TREE
        and len(git(repo, "rev-list", "--objects", NEW, "^" + OLD).splitlines())
        == data["pack"]["count"]
        == 20,
        "unregistered child",
    )
    need(
        set(git(repo, "diff", "--name-only", OLD, NEW).decode().splitlines())
        == set(data["blobs"])
        == EXPECTED,
        "source scope",
    )
    for p, ids in data["blobs"].items():
        for key, ref in (("old", OLD), ("new", NEW)):
            spec = ref + ":" + p
            if ids[key] is None:
                need(
                    key == "old"
                    and p.startswith("tests/run-make/" + TEST + "/")
                    and not git(repo, "ls-tree", ref, "--", p),
                    "expected new source path",
                )
            else:
                need(
                    [rev(repo, spec), digest(git(repo, "show", spec))] == ids[key],
                    "wrong Git blob: " + spec,
                )
    for name, v in data["trees"].items():
        need(v == rev(repo, NEW + ":" + name), "wrong " + name)
        if name not in ("compiler", "tests"):
            need(v == rev(repo, OLD + ":" + name), "parent component changed " + name)
    for fixture, name in SCHEMA.items():
        need(
            gzip.decompress((HERE / "inputs" / (fixture + ".gz")).read_bytes())
            == git(repo, "show", NEW + ":" + name),
            "foreign metadata decoding schema",
        )
    patch = git(
        repo,
        "--attr-source=4b825dc642cb6eb9a060e54bf8d69288fbee4904",
        "diff",
        "--full-index",
        "--binary",
        OLD,
        NEW,
    )
    need(
        digest(patch)
        == data["patch"]
        == "44d41ecf8a45b127d04c55f948a17261d834889af3526a1af285041561e29434",
        "source diff",
    )
    return data


if __name__ == "__main__":
    print(json.dumps(validate(Path(sys.argv[1]))["pack"], sort_keys=True))
