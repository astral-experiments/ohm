"""Require the new native SDK and replayed collision witnesses before enrolling any worker."""
import hashlib
import json
from pathlib import Path
import zipfile

HERE = Path(__file__).resolve().parent
RUNTIME = HERE / "inputs/checked-e-source.json"
CERTIFICATE = HERE / "inputs/checked-source-replay.json"
PROVIDER = HERE / "inputs/checked-provider.json"
REG_SHA = "b3b58cb226e4673b8c94eb1088b0b99293174ec55f5186e05cb6058d3b2e21c2"
CERT_SHA = "5fcbd49bf99bad10ba4a0a5c5b7c1fe18535859f723c540061f7e99d4d619fb8"
SOURCE = "393b4b05a4bfa3f531a36023846f86236a6b71a9"
TREE = "f0996ec0915571479ff22b774da977fa25ac690c"
COMPILER = "89dcac9002ea6a0307d6fef82c0652b15c85dcca"
HEAD, RUN, JOB = "762fc25095e317ac5632ec835df3c7f9cfc64a64", 41242910474, 124660310979
REF = "charlie/qa-branch-checked-packed-source-20261031"
DRIVER_ZIP = "first-session-linux-source-driver"
OBS_ZIP = "first-session-linux-source-observations"
DRIVER_PATH = "lib/librustc_driver-c5276fb6f0cdddb4.so"
HISTORICAL = "2a59fb867b303820eb117f783aaef246add789581cd63d9874e4fe1937914038"
WILD = "0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5"
CARGO = "035e681081683f4141e4c544b8cf9492b73784051e4541c12bb3cbdb73a798a4"
SOURCE_STEPS = {
    "Build only the corrected compiler and run all checked-in and mixed native cases",
    "Publish the qualified Linux driver capsule",
    "Preserve source and native observations",
}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def validate(reg, proof):
    e = reg["source"]
    q = e["qualified"]
    require(reg["schema"] == 1 and (e["run"], e["attempt"], e["job"], e["head"]) == (RUN, 1, JOB, HEAD)
            and set(e["artifacts"]) == {DRIVER_ZIP, OBS_ZIP} and proof["official"] == e,
            "different corrected source enrollment")
    r, source = proof["restored"], proof["source"]
    require(source["commit"] == q["source"] == reg["reviewer"]["source"] == r["commit"] == SOURCE
            and source["tree"] == TREE and source["compiler"] == COMPILER
            and r["manifest"] == q["manifest"] == reg["reviewer"]["manifest"]
            and r["driver"] == q["driver"] and r["driver"][0] != HISTORICAL
            and set(r["changed"]) == {"bin/rustdoc", DRIVER_PATH}
            and r["cargo"][0] == CARGO and r["wild"][0] == WILD
            and r["members"] == q["members"] == proof["trusted_member_count"] == proof["separate_inodes"] == 81
            and proof["whole_cargo_counts"] is None, "different native compiler or non-independent source proof")
    require(set(proof["cross_readers"]) == {"E-cold-A-to-K", "E-first-A-to-K", "K-first-A-to-E", "K-packed-A-to-E"}
            and len(proof["actual_native_test_logs_sha256"]) == 11 and len(proof["tests"]["run_make"]) == 7
            and len(proof["tests"]["units"]["rustc_incremental"]) == 10, "incomplete original donor reads or suites")
    for case in proof["cross_readers"].values():
        for key, value in (("return_elf", 17), ("first_B", 29)):
            replay = proof["native_replayed_here"][case[key]]
            require(replay["value"] == value and replay["observed"] == {str(value): 0, str(value + 1): 19},
                    "missing signed native consumer or contradictory expectation")
    checked, reused = proof["checked_cases"], proof["executed_collision_elfs"]
    require(set(checked) == {"old", "corrected"} and proof["collision_sha256"] == proof["terminal"]["collision"]
            and proof["collision"]["roles"]["corrected"]["driver"] == r["driver"][0]
            and proof["collision"]["roles"]["old"]["driver"] == HISTORICAL, "incorrect collision sources")
    for role, tag, marker in (("old", 17, True), ("corrected", 29, False)):
        for key, val, mark in (("B-conflicting-raw", tag, marker), ("B-matching-raw", 29, marker),
                               ("B-honest", 29, True), ("B-raw-only-old", 17, True)):
            row = checked[role]["cargo"][key]
            require((row["value"], row["marker"], reused[row["elf"]]["observed"]) == (val, mark, {str(val): 0}),
                    "did not reproduce the old shadow, clean recovery, or raw-only boundary")
        mix, f = checked[role]["mixed"], checked[role]["F_bridge"]
        require(reused[mix["conflict-read-B"]]["value"] == tag
                and (mix["conflict-read-B"] == mix["empty-B"]) == (role == "corrected")
                and f["read-B83"] == f["empty-B83"] == f["F-B83"]
                and reused[f["read-B83"]]["value"] == 83, "wrong mixed-writer output")
    require(checked["old"]["cargo"]["B-malformed-raw"] == {"code": 101}
            and checked["corrected"]["cargo"]["B-malformed-raw"]["value"] == 29,
            "missing original malformed refusal or corrected repair")
    return e


def enrollment():
    reg, proof = RUNTIME.read_bytes(), CERTIFICATE.read_bytes()
    require(REG_SHA and CERT_SHA and sha(reg) == REG_SHA and sha(proof) == CERT_SHA, "unsealed corrected E")
    r = json.loads(reg)
    require(r["reviewer"]["raw_sha256"] == CERT_SHA, "different independent source evidence")
    certificate = json.loads(proof)
    native = PROVIDER.read_bytes()
    require(sha(native) == "5102e75e06555c17a55b0e5db5876f883034afb307962b357aaf18bbf525896a", "different native provider evidence")
    p = json.loads(native)
    tags = {"cold": 17, "repeat": 17, "higher": 29, "same-stat": 47, "malformed": None,
            "repeat-malformed": None, "repair": 29, "removed": 17}
    require({k:v[0] for k,v in p["shadow"].items()} == tags
            and p["real_native_archive_visits"] == 16 and p["malformed_native_links"] == 4
            and p["same_stat"] == certificate["native_provider"]["same_stat"]
            and set(p["shadow_elf_executed"].values()) == {17, 29, 47}, "incomplete native provider changes or own-empty controls")
    return validate(r, certificate)


def official(api, e):
    top = api(f"runs/{RUN}")
    jobs = api(f"runs/{RUN}/attempts/1/jobs?per_page=100")
    media = api(f"runs/{RUN}/artifacts?per_page=100")
    require((top["id"], top["head_sha"], top["head_branch"], top["run_attempt"], top["event"], top["path"],
             top["status"], top["conclusion"]) == (RUN, HEAD, REF, 1, "workflow_dispatch", ".github/workflows/ci.yml",
                                                   "completed", "success"), "wrong official corrected source")
    require(jobs["total_count"] == len(jobs["jobs"]) == 1 and media["total_count"] == len(media["artifacts"]) == 2,
            "unexpected source jobs or ZIPs")
    j, = jobs["jobs"]
    require((j["id"], j["head_sha"], j["run_id"], j["status"], j["conclusion"]) == (JOB, HEAD, RUN, "completed", "success")
            and SOURCE_STEPS <= {step["name"] for step in j["steps"] if step["conclusion"] == "success"},
            "required source/mixed or native step missing")
    got = {}
    for a in media["artifacts"]:
        require(not a["expired"] and (a["workflow_run"]["id"], a["workflow_run"]["head_sha"]) == (RUN, HEAD),
                "different or expired corrected original")
        got[a["name"]] = {k: a[k] for k in ("id", "digest", "size_in_bytes")}
    require(got == e["artifacts"], "mismatched official source artifacts")


def media(actual, folder):
    e = enrollment()
    require(actual == e, "source-specific verifier did not reopen the registered two ZIPs")
    with zipfile.ZipFile(folder / (DRIVER_ZIP + ".zip")) as capsule:
        raw = capsule.read("manifest.json")
        m = json.loads(raw)
    with zipfile.ZipFile(folder / (OBS_ZIP + ".zip")) as obs:
        end = json.loads(obs.read("qualified.json"))
        witness = sha(obs.read("E/collision/complete.json"))
    require(m["source"]["role"]["commit"] == end["commit"] == SOURCE
            and m["files"][m["driver"]] == end["driver"] == e["qualified"]["driver"]
            and (sha(raw), witness) == (end["manifest"], end["collision"]) == (e["qualified"]["manifest"], m["collision"]),
            "physical corrected source and collision receipts disagree")
    return actual, {"capsule_manifest_sha256": sha(raw), "collision_sha256": witness, "source": SOURCE}
