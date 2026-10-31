"""Materialize the exact rebased fix and authenticate its native predecessor and checked-in tests."""

from pathlib import Path
import json
import sys

HERE = Path(__file__).resolve().parent
ORIGINAL = HERE.parent / "branch-first-session-e-source"
sys.path.insert(0, str(ORIGINAL))
import subject as old

reg = old.reg
need = reg.need
SHA = "393b4b05a4bfa3f531a36023846f86236a6b71a9"
PARENT = "d14aab0ed513d847f30ba5073e0863b7419c9a70"
ANCHOR = "6dbcba66b0fe2c6c205f106a622129557796f86f"
PREVIOUS = "c9a6a212d38d778ed0e9d2c7057a9dedb179fff2"
REF = "refs/heads/charlie/qa-branch-checked-packed-source-20261031"
WITNESS = "73d75e928f2b8c0663b3412d1f8d222be4d30b90f68c6e5d3398f641ade3d0e9"
ORIGINAL_ARTIFACT = json.loads((HERE / "inputs/old-sdk.json").read_bytes())["source"]
EXPECTED_PATHS = {
    "compiler/rustc_incremental/src/persist/fs/packed/objects.rs",
    "compiler/rustc_incremental/src/persist/fs/packed/tests.rs",
    "tests/run-make/ohm-packed-branch-cache/rmake.rs",
}
K_ORIGIN = old.K_ORIGIN


def load():
    old_candidate = old.load()
    original_subject = json.loads((HERE / "inputs/old-native-subject.json").read_bytes())
    need(
        reg.sha(HERE / "inputs/old-sdk.json")
        == "231393000d6c1bc3ed241aa4409615eca0e2fa3ea44564c57fcdd13237db83b2"
        and reg.sha(HERE / "inputs/old-native-subject.json")
        == "fe253a9471abc33180dc058c5788d7005720cc34eb835a8948505413237aa801"
        and original_subject["source"] == old_candidate["role"]
        and original_subject["cargo"][0] == reg.ELF
        and original_subject["driver"] == ORIGINAL_ARTIFACT["qualified"]["driver"]
        and original_subject["manifest"] == ORIGINAL_ARTIFACT["qualified"]["manifest"],
        "incorrect historical native witness",
    )

    pack = HERE / "inputs/source.pack"
    path = HERE / "inputs/subject.json"
    need(
        reg.sha(path) == "56fce0a20daab2c01734ceca267928ab750856c79e936c880d3a48aee5496e9d",
        "incorrect corrected compiler enrollment",
    )
    data = json.loads(path.read_bytes())
    r = data["role"]
    need(
        (r["commit"], r["tree"], r["compiler"], r["library"], r["tests"], r["src/bootstrap"])
        == (
            SHA,
            "f0996ec0915571479ff22b774da977fa25ac690c",
            "89dcac9002ea6a0307d6fef82c0652b15c85dcca",
            "4f7a8f755164dc68fff80790db8a844ae030fd03",
            "c2f01372cdffaed5229731e74ae5a814622f7f7a",
            "1dcf3e6b142ba5c132f7a2370dffa6ba090b15e1",
        ),
        "different compiler or bootstrap",
    )
    need(
        data["parent"] == PARENT
        and data["anchor"]["commit"] == ANCHOR
        and data["previous"] == old_candidate["role"]
        and [r["path"] for r in data["rebase_delta"]["rows"]] == [".github/workflows/ci.yml"]
        and {r["path"] for r in data["delta"]["rows"]} == EXPECTED_PATHS
        and all(r["change"] == "M" for r in data["delta"]["rows"]),
        "unknown product changes",
    )
    need(
        not pack.is_symlink()
        and 0 < pack.stat().st_size == data["pack"]["bytes"] < 4 << 20
        and reg.sha(pack) == data["pack"]["sha256"],
        "incorrect source transport",
    )
    need(
        ORIGINAL_ARTIFACT["qualified"]["source"] == PREVIOUS
        and ORIGINAL_ARTIFACT["run"] == 41227867294
        and reg.sha(HERE / "inputs/old-run-make.json") == WITNESS
        and reg.sha(HERE / "inputs/old-natural-F.json")
        == "4cc9758bf843cd592e0feeafdce42fadc1ea1733e1bcd4519005c72b5b63ea9c"
        and reg.sha(HERE / "inputs/old-cargo-cases.json")
        == "99eafd72f393fba5ddee6684bf49d280e9b187d6c77e40fca8d59d5bc15a352d"
        and reg.sha(HERE / "inputs/complete.json")
        == "3db0100bef6f7683b1702fdbf39ffbf3a26118da271e696d4f380f5414413987",
        "original native failure unavailable",
    )
    return data


def verify(repo, candidate, install=False):
    need(candidate == load(), "unregistered candidate")
    old.verify(repo, old.load(), install)
    if install:
        reg.git(repo, "index-pack", "--stdin", data=(HERE / "inputs/source.pack").read_bytes())
    need(
        all(
            old.ident(repo, x["commit"]) == x
            for x in [
                candidate["role"],
                candidate["anchor"],
                candidate["rebase_parent"],
                candidate["previous"],
            ]
        ),
        "unmatched complete source or subtree",
    )
    need(
        reg.git(repo, "rev-list", "--parents", "-1", SHA).decode().split() == [SHA, PARENT]
        and reg.git(repo, "rev-list", "--parents", "-1", PARENT).decode().split() == [PARENT, ANCHOR],
        "different reviewed ancestry",
    )
    need(
        reg.identity_delta(repo, PREVIOUS, PARENT) == candidate["rebase_delta"]
        and reg.identity_delta(repo, PARENT, SHA) == candidate["delta"],
        "unverified rebased tree or fix",
    )
    f = old.ident(repo, reg.SOURCE()["roles"]["F"]["commit"])
    for path in ("compiler", "library", "tests", "src/bootstrap"):
        need(
            candidate["anchor"][path] == f[path]
            and candidate["previous"][path] == candidate["rebase_parent"][path],
            "original native F or E was not source-equivalent",
        )
    need(
        old.verify_pack(repo, PREVIOUS, SHA, (HERE / "inputs/source.pack").read_bytes()) == 656,
        "different independently accepted source objects",
    )
    for p in ("compiler/rustc_session/src/session.rs", "compiler/rustc_interface/src/queries.rs"):
        need(reg.rev(repo, PREVIOUS + ":" + p) == reg.rev(repo, SHA + ":" + p), "selector changed")
    a = reg.git(repo, "show", SHA + ":compiler/rustc_incremental/src/persist/fs/packed/objects.rs")
    need(
        b"Ok(_) => return Err(invalid())," in a
        and b"Ok(meta) if meta.is_file() => return Ok(true)" not in a,
        "legacy raw preference remained active",
    )
    return candidate


def required_tests(commit):
    need(commit == SHA, "unregistered compiler")
    return old.required_tests(PREVIOUS)


def names_for(commit):
    need(commit == SHA, "unregistered compiler")
    return {"changed_files": {r["path"]: r["new"]["sha256"] for r in load()["delta"]["rows"]}}


if __name__ == "__main__":
    if len(sys.argv) == 2:
        verify(Path(sys.argv[1]), load())
    elif len(sys.argv) != 1:
        raise SystemExit("corrected.py [LOCAL_RUST_WORKTREE]")
    print(json.dumps(load()["role"], sort_keys=True))
