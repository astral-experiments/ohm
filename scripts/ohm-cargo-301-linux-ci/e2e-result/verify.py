"""Verify the native receipt offline with Python 3.10+. Use --self-test to exercise its guards."""
import argparse
from collections import Counter
from copy import deepcopy
import gzip
from hashlib import sha256
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
INVENTORY = "76d24b892727ff181fdf019636ef5e928d741eb8df4f58f06dcc626d0bf67c52"
ORIGINAL = "e0a1f22f5370a1b05f13abbebb7bec9a912359db1dfb191827d9eca9cc01d425"
EDITED = "23f3dbc5be27f7e09033af7dbcace33ed8a81d936ce8b6e8f78a394ab219302a"
HOOK = "a8403201aa6242d404f365deb410ed548141f0257aca9cb4acb8289770c3bd01"
REPEATS = {"unchanged", "explain-unchanged", "final-unchanged"}


def keyed(args, key):
    return [value for prev, value in zip(args, args[1:]) if prev == key]


def check_feature(data):
    w = data["workspace"]
    assert w["run"] == 41114085548 or w["run"] == "41114085548"
    assert w["artifact"] == 13005843628
    assert w["zip_sha256"] == "cd0c0285bcb1d49f6560d9507f42fc06e1d69ee82c9f1e85cbf88473040fc953"
    original = w["phases"]["unchanged"]
    assert (original["typed"], original["typed_dirty"]) == (619, 56)
    assert original["actual"] == {"cargo": 1, "collect2": 50, "full": 51, "wild": 50}
    argv = w["e2e_argv_by_phase"]["unchanged"]
    assert len(argv) == 736 and all(a == argv for a in w["e2e_argv_by_phase"].values())
    assert "--test" in argv and "lto=off" in keyed(argv, "-C") and "-Zohm-check-relink-inputs" in argv
    direct = [v.partition("=") for v in keyed(argv, "--extern")]
    dirty = {path for _, _, _, paths in w["first_unchanged_dirty"] for path in paths}
    assert len(direct) == 73 and len({name for name, _, _ in direct}) == 37
    assert sorted((name, Path(p).suffix) for name, _, p in direct if p in dirty) == [
        ("insta", ".rlib"), ("insta", ".rmeta")
    ]
    assert set(w["ron_only_direct_consumers"]) == {"insta"}
    for phase in ("cold", "restored", "final-unchanged", "clean-original"):
        assert w["phases"][phase]["output"] == original["output"]
    assert w["phases"]["edited"]["output"] == "a1c402ed4702e0554951e1be31b1866754a029da01d1220a0cffbaa3191c4757"
    assert w["phases"]["clean-reversed"]["output"] == "feb60b6aacda1d71ae2e3cdc7c301bd0489a4ffd6daf9cdf990a55b66bf2d545"

    solo, feature = data["solo"], data["feature"]
    assert data["solo_archive"]["id"] == 13006059695 and data["feature_archive"]["id"] == 13007991573
    assert all(p["cargo_exit"] == p["case_exit"] == 0 and p["inventory_sha256"] == INVENTORY
               for collection in (solo, feature) for p in collection.values())
    for phase in ("unchanged", "explain-unchanged"):
        assert (solo[phase]["typed"], solo[phase]["counts"]) == (300, {})
        visit = feature[phase]
        assert (visit["typed"], visit["counts"]) == (309, {"full": 2, "wild": 1})
        assert [v[3] for v in visit["selected_real_execs"] if v[2] == "full"] == ["ron", "e2e"]
        assert [v[0] for v in visit["json_dirty"]] == ["ron", "insta", "e2e"]
    for phase in ("near-unchanged", "settled-near"):
        visit = feature[phase]
        assert (visit["typed"], visit["counts"]) == (308, {})
    near, with_ron = feature["near-unchanged"]["command"], feature["unchanged"]["command"]
    assert near[:-1] == with_ron[:-1] and near[-1] + ",insta/ron" == with_ron[-1]
    for name in ("ron", "insta"):
        def features(a):
            return sorted(v for v in keyed(a, "--cfg") if v.startswith("feature="))
        assert features(w["ron_and_insta_compilers"][name]) == features(data["with_feature_compilers"][name]["argv"])
    assert feature["restored"]["source_inputs"] == feature["unchanged"]["source_inputs"]
    assert feature["edited"]["source_inputs"] != feature["restored"]["source_inputs"]

    depfiles = data["serialized_depfiles"]
    ron, = [p for p in depfiles if Path(p).name.startswith("ron-")]
    marker = Path(ron).name + "/ohm-foreign-span-bytes"
    assert marker in depfiles[ron]
    assert all(".d/ohm-" not in s and "/dev/null/ohm-" not in s for p, s in depfiles.items() if p != ron)
    assert {p.split("/")[-1].split("-")[0] for p in depfiles} == {"ron", "insta", "e2e"}
    log = "\n".join(data["fingerprint_lines"])
    assert 'stale: missing "' in log and marker in log
    assert "early cutoff: skipping compilation of insta v1.48.0" in log
    assert re.search(r"ty_server v0\.0\.0: fs_status=StaleDepFingerprint [^\n]+/out/e2e-", log)
    items = data["selected_product_history"]
    for before, after in (("with-feature", "unchanged"), ("unchanged", "explain-unchanged")):
        for name, count in (("ron", 12), ("insta", 18)):
            rlibs = [p for p in items[after] if p.startswith("lib" + name + "-") and p.endswith(".rlib")]
            assert len(rlibs) == 1
            rlib = rlibs[0]
            first, last = items[before][rlib], items[after][rlib]
            assert first[1:] == last[1:] and len(last[2]) == count
            if name == "insta":
                assert first[0][:2] == last[0][:2] and first[0][4] < last[0][4]
            rmeta = rlib.removesuffix(".rlib") + ".rmeta"
            first, last = items[before][rmeta], items[after][rmeta]
            assert (first[1] == last[1]) == (name == "insta")
            if name == "ron":
                assert first[0][4] == last[0][4]


def check_receivers(data, paired):
    assert paired["native_run"] == 41120192553 and paired["qa"] == "a5c14d2bb3c2f3c47472872df6263fb0b77727a1"
    roles = paired["roles"]
    assert set(roles) == {"shipped", "strict-293"}
    shipped, strict = roles["shipped"], roles["strict-293"]
    assert shipped["driver"] == strict["driver"] == "dae4f8dc64b2b2ac9dc04dfe2cfad633d6af1a87da2dfc532e757ffe758680e3"
    assert {k for k in shipped["kit"] if shipped["kit"][k] != strict["kit"][k]} == {"cargo"}
    assert strict["kit"]["wild"] == "0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5"
    for role, r in roles.items():
        newer = role == "shipped"
        extra = data["receivers"][role]
        assert r["source"] == "93526150df078af7dd8fc4226cdcc469539d2001"
        assert r["history"] == "83a3afc3156d73ae4296f3fa74ede28e4c72bfcd"
        assert r["artifact_id"] == (13007937879 if newer else 13006989669)
        assert r["zip_sha256"] == (
            "22754e6f367e9548a9c756b9736d594e655efaa67004906a520cb1ec47ffb901" if newer else
            "d2984a32da7d50d8a582cc658b493b3984d4b4f0824653f226f550eaad872005"
        )
        assert ("2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c" if newer else
                "735e1528ed741015c57676dccf05dbdc0ff7bed1") in extra["actual_versions"]["cargo"]
        assert "c79998a5cd143c445a4b2528f20953b176a65c5d" in extra["actual_versions"]["rustc"]
        real, = [v["argv"] for v in extra["ordinary_rustc"].values() if v["name"] == "e2e"]
        assert ("link-only" in keyed(real, "-Z")) == (not newer)
        assert any(v.endswith(".rlink") for v in real) == (not newer)
        assert any("reusing cached codegen for ty_server" in line for line in extra["cargo_lines"]) == (not newer)
        assert r["cold_restored_equal"] and r["edited_empty_equal"]
        assert set(r["phases"]) == REPEATS | {"cold", "clean-edited", "edited", "restored"}
        for phase, row in r["phases"].items():
            assert (row["typed"], row["tests"], row["list_sha"]) == (309, 200, INVENTORY)
            assert row["e2e"] == (EDITED if phase in ("edited", "clean-edited") else ORIGINAL)
            if phase in REPEATS:
                expected = {"full": 2, "wild": 1} if newer else {"full": 3, "link-only": 1, "wild": 2}
                complete = sorted(v[2] for v in row["all_actual_jobs"] if v[1] == "full")
                assert complete == (["e2e", "ron"] if newer else ["build_script_build", "ron", "unicode_names2"])
                cached = [v[2] for v in row["all_actual_jobs"] if v[1] == "link-only"]
                assert cached == ([] if newer else ["e2e"])
            elif phase in ("edited", "restored"):
                expected = {"full": 18, "wild": 2} if newer else {"full": 20, "wild": 3}
                assert any(op == "full" and name == "e2e" for _, op, name in row["all_actual_jobs"])
            else:
                expected = {"full": 312, "wild": 49}
            assert row["counts"] == expected
            if "all_actual_jobs" in row:
                assert Counter(t for _, t, _ in row["all_actual_jobs"]) == expected
                assert len({pid for pid, _, _ in row["all_actual_jobs"]}) == sum(expected.values())

        assert set(r["providers"]) == {"valid", "valid-force", "malformed", "malformed-force", "removed"}
        for phase, row in r["providers"].items():
            assert any(mode == "wild" and name.startswith("e2e-") for _, mode, name in row["physical"])
            if phase == "removed":
                assert (row["cargo"], row["exec"], row["raw_elf"]) == (0, 0, ORIGINAL)
            else:
                assert any("psm/" in line and "/out/libgcc_s.so" in line and re.search(r" = [0-9]+$", line)
                           for _, line in row["actual_successful_private_opens"])
                if phase.startswith("valid"):
                    assert (row["cargo"], row["exec"], row["raw_elf"]) == (0, 83, HOOK)
                else:
                    assert row["cargo"] == 101 and row["exec"] is None
                    diag = extra["native_diagnostic"][phase]
                    assert "libgcc_s.so" in diag and "UNRECOGNIZED_E2E_PRIVATE_LINK_SCRIPT" in diag


def check_files():
    manifest = {}
    for line in (ROOT / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ", 1)
        assert name not in manifest and Path(name).name == name
        manifest[name] = digest
    assert set(manifest) == {"README.md", "verify.py", "feature.json.gz", "receivers.json", "custody.json"}
    for name, digest in manifest.items():
        assert sha256((ROOT/name).read_bytes()).hexdigest() == digest, name
    custody = json.loads((ROOT/"custody.json").read_bytes())
    assert custody["reader"] == 41121963155 and custody["archive_id"] == 13007264753
    assert (custody["phase_count"], custody["provider_count"]) == (14, 10)
    assert custody["payload_sha256"] == manifest["receivers.json"]
    assert custody["zip_sha256"] == "bcfd31cde3439c51e3d2a4f42a45e935290647952bb2a4cc30ff0af0f2a5e9c8"


def self_test(feature, receivers):
    for name, path, value in [
        ("unlink feature intervention", ("feature", "feature", "unchanged", "counts", "full"), 0),
        ("lose compiler-mode distinction", ("receivers", "roles", "strict-293", "phases", "unchanged", "counts", "link-only"), 0),
        ("hide invalid native input", ("receivers", "roles", "shipped", "providers", "malformed", "cargo"), 0),
        ("mismatch independent clean", ("receivers", "roles", "strict-293", "phases", "clean-edited", "e2e"), ORIGINAL),
    ]:
        altered = {"feature": deepcopy(feature), "receivers": deepcopy(receivers)}
        node = altered
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value
        try:
            check_feature(altered["feature"])
            check_receivers(altered["feature"], altered["receivers"])
        except AssertionError:
            continue
        raise AssertionError("mutation was accepted: " + name)


if __name__ == "__main__":
    if not __debug__:
        raise SystemExit("Run without Python's -O option")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    check_files()
    feature = json.loads(gzip.decompress((ROOT/"feature.json.gz").read_bytes()))
    receivers = json.loads((ROOT/"receivers.json").read_bytes())
    check_feature(feature)
    check_receivers(feature, receivers)
    if args.self_test:
        self_test(feature, receivers)
    print("Original 619 units: 51 full rustcs and 50 Wild links. Ron feature: 0 to 2 full / 1 Wild and back to zero.")
    print("Shipped: 2 full / 0 link-only / 1 Wild; strict #293: 3 full / 1 link-only / 2 Wild on all three repeats.")
    print("Both receivers passed all 14 ordinary visits and all 10 native-provider visits; four offline mutations rejected." if args.self_test
          else "Both receivers passed all 14 ordinary visits and all 10 native-provider visits.")
