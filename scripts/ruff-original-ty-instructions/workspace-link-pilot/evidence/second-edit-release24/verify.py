"""Reopen the complete unmetered signed -24 ordinary Cargo source and output safety study."""

import gzip
import hashlib
import json
import sys
from pathlib import Path
from zipfile import ZipFile


HERE = Path(__file__).resolve().parent
PILOT = HERE.parent.parent
sys.path[:0] = [str(PILOT), str(HERE.parent / "second-edit-release23")]
import read_pilot
import repeated_edit
import sections_and_fallbacks


RUN = 41747172339
SHA = "6df78409d5903049c988e3f4219f823e0e1e50f0d643ea4919c42b8238bb34ae"
HEAD = "31b89aefc9a96e9ec7d340cf990e3ada0e5644ef"


def verify(archive):
    assert archive.stat().st_size == 72_455_006
    r = read_pilot.intake(archive, SHA, HEAD, RUN, 24)
    assert r["complete"] and r["stage_count"] == r["registered_stages"]
    assert not r["qualified"] and not r["clocks"] and len(r["refusal"]) == 4
    second = repeated_edit.reopen(archive, SHA, 24)
    sections = sections_and_fallbacks.reopen(archive, SHA)
    assert not second["forecast_only"] and not second["unexpected_actual"]
    assert len(second["actual_fresh_roles"]) == 32
    assert not second["hits_with_different_whole_elf_from_empty_signed"]
    assert not second["all50_source_second_vs_signed_second"]
    assert not second["all50_source_empty_vs_signed_empty"]
    audit = r["ordinary_second_edit"]
    assert audit["certified_hit_matches_clean"]
    assert second["actual_fresh_roles"] == audit["certified_second_edit_hits"]
    assert set(sections["refusals"]) == set(r["refusal"])
    for phase, bad in sections["refusals"].items():
        assert set(bad) == set(r["refusal"][phase])
        assert all(q["fallback"] == "full-typed-refusal" for q in bad.values())
    with ZipFile(archive) as z:

        def j(n):
            v = z.read(n)
            return json.loads(gzip.decompress(v) if n.endswith(".gz") else v)

        manifests = {}
        for name, expected in (
            (
                "release-compiler-24.json",
                "47919d5c6bf266b70c65c291f0fa5c37859b73fa9ec457bf47a50cc07448cd7c",
            ),
            (
                "release-published-24.json",
                "0fc1e7bd51c18928ca0ec1f4400a85c49b4c92a30391a3b426afa1816e2527c1",
            ),
        ):
            body = (PILOT / name).read_bytes()
            assert hashlib.sha256(body).hexdigest() == expected
            manifests[name] = json.loads(body)
        compiler = manifests["release-compiler-24.json"]
        public = manifests["release-published-24.json"]
        sdk = j("sdk-24.json")
        asset = public["assets"]["ohm-1.99.0-24-x86_64-unknown-linux-gnu.tar.gz"]
        assert (
            sdk["archive"] == asset
            and asset["sha256"] == "sha256:" + compiler["tar_sha256"]
        )
        assert set(sdk["files"]) == set(compiler["members"]) and len(sdk["files"]) == 79
        for name, (digest, mode, device, inode) in sdk["files"].items():
            assert digest == compiler["members"][name]["sha256"] and mode in (
                0o644,
                0o755,
            )
            assert device >= 0 and inode > 0
        assert len({tuple(r[2:]) for r in sdk["files"].values()}) == 79
        assert set(sdk["versions"]) == {"cargo", "rustc"}
        for tool, text in sdk["versions"].items():
            strip_runtime_os = lambda t: [
                l for l in t.splitlines() if not l.startswith("os: ")
            ]
            assert strip_runtime_os(text) == strip_runtime_os(public["linux_sdk"][tool])
        assert sdk["files"][compiler["wild"]][0] == j("actor.json")["stock"]
        failure = j("complete.json")
        assert not failure["qualified"]
        states = {}
        for arm in ("P", "C"):
            for stage in (
                "old",
                "edit",
                "warm1",
                "ordinary-repeat-old",
                "ordinary-repeat-edit",
                "empty-new",
            ):
                tag = f"{arm}-{stage}"
                row = j(tag + "-receipt.json.gz")
                inv = j(tag + "/inventory.json.gz")
                assert row["exit"] == 0 and ("fresh_roles" in row) == (arm == "C")
                tests = z.read(tag + "-native/stdout")
                states[tag] = {
                    "source_state": inv["state"],
                    "actual_units": len(inv["units"]),
                    "fresh_units": sum(fresh for _, fresh in inv["units"]),
                    "executables": len(inv["executables"]),
                    "native_test_list_SHA256": hashlib.sha256(
                        z.read(tag + "-native/test-list")
                    ).hexdigest(),
                    "actual_existing_output_hits": row.get("fresh_roles", []),
                    "complete_role_SHA256": row["published"],
                    "candidate_receipt_bytes": row.get("metadata_bytes"),
                    "observed_Ruff_test_stdout_sha256": hashlib.sha256(
                        tests
                    ).hexdigest(),
                }
        negative = {
            k: j(k)
            for k in (
                "C-native-four-verdict.json",
                "C-native-four-actual-change.json",
                "C-native-malformed-actual-change.json",
                "C-native-save-actual-change.json",
                "C-native-earlier-actual-change.json",
                "actual-canonical-OPATHs.json",
                "before-output-selection.json",
                "actual-output-repair-stage.json",
            )
        }
        corrupt_files = [
            name
            for name in z.namelist()
            if name.startswith("corrupted-existing-")
            and name.endswith(".json")
            and "/" not in name
        ]
        assert len(corrupt_files) == 2
        negative.update({name: j(name) for name in corrupt_files})
        negative["guarded_native_outputs"] = r["guarded_native_outputs"]
        for tag in (
            "C-native-malformed",
            "C-native-save",
            "C-actual-type-error",
            "C-actual-type-repair",
        ):
            negative[tag] = {
                "exit": j(tag + "-receipt.json.gz")["exit"],
                "stdout_SHA256": hashlib.sha256(
                    z.read(tag + "/stdout.jsonl")
                ).hexdigest(),
                "stderr_SHA256": hashlib.sha256(z.read(tag + "/stderr")).hexdigest(),
            }
        withheld = {}
        for arm in ("P", "C"):
            for stage in ("withheld-old-on-new", "withheld-ordinary-repeat-old"):
                raw = z.read(f"{arm}-{stage}/stdout")
                assert (
                    b"1 failed;" in raw
                    and b"source_text" in raw
                    and b"script_tag" in raw
                )
                withheld[f"{arm}-{stage}"] = hashlib.sha256(raw).hexdigest()
        checked_hits = {}
        for tag, native in r["native"].items():
            if tag + "/inventory.json.gz" not in z.namelist() or tag == "C-native-four":
                continue
            ref = "P-old" if tag.endswith("-old") else "P-empty-new"
            role_sha = j(tag + "-receipt.json.gz")["published"]
            signed_sha = j(ref + "-receipt.json.gz")["published"]
            hits = sorted(native["fresh"])
            assert all(role_sha[k] == signed_sha[k] for k in hits)
            checked_hits[tag] = {"count": len(hits), "reference": ref}
        assert checked_hits["C-ordinary-repeat-edit"]["count"] == 32
        return {
            "unchanged_output_hits_compared_to_signed": checked_hits,
            "original": {
                "repository": "astral-experiments/ohm",
                "run_id": RUN,
                "job_id": 126302999192,
                "artifact_id": 13285298735,
                "qa_commit": HEAD,
                "bytes": archive.stat().st_size,
                "sha256": SHA,
            },
            "release_sdk_JSON_SHA256": hashlib.sha256(
                z.read("sdk-24.json")
            ).hexdigest(),
            "signed_SDK": {
                "archive": sdk["archive"],
                "versions": sdk["versions"],
                "signed_members": len(sdk["files"]),
                "Wild_SHA256": sdk["files"][compiler["wild"]][0],
            },
            "admission": r["admission"],
            "complete_phases": r["stage_count"],
            "qualified": False,
            "hardware_measurements": r["clocks"],
            "ordinary": states,
            "second_edit": second,
            "empty_and_second_role_checks": audit,
            "negative_controls": negative,
            "withheld_OLD_on_NEW": withheld,
            "whole_ELF_refusals": sections,
            "all_native_differences_recorded_by_role": r["all_native_differences"],
        }


if __name__ == "__main__":
    print(json.dumps(verify(Path(sys.argv[1])), sort_keys=True, indent=2))
