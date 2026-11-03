"""Select one prespecified comparison from the two independent signed-23 uv admissions."""

import hashlib
import json
import re
import posixpath

from release23_binding import AMENDMENT, PROSPECTIVE
from split_host import BRANCH, CONTRASTS, baseline

REGISTRATION = "4d17e7b41ca0e422174b0ae43a9a0b4aee25c72e58ac2be6989751e95a65d58c"
NATIVE_PAIR = "c5d25c2c448e04cacb05da0b8d909afd23cd5bd7fd2d87965385e30b44b93377"
PARENT = "8b2ffa46cb0b3d37188f7c286048865237ff6128"
CHOICE = "9565a7bd1431188300fe3b227a8fe2e86096fef99000fc036fafe816c1c0f030"
SOURCE_S = {"commit":"b5bbf6e74cd71de00a5c805d365e93673f248265", "tree":"28ef6f93dd22a679d369bbd9fbc8bc05e240f1a7", "epoch":43421, "metadata_epoch":3}
SOURCE_F = {"commit":"60bd529e1a0d59e5904912bd38e6a13702d10263", "tree":"2b6ae56e2269366bed9e28438451690ff64abc54", "epoch":43422, "metadata_epoch":43422}


def select(lock, registration, amendment, choice, split, pair, contrast):
    assert split["study"] == "signed-23-uv-22958-split"
    assert split["original_registration"] == PROSPECTIVE and split["r2_amendment"] == AMENDMENT
    assert split["contrasts"] == lock["contrasts"] == CONTRASTS and contrast in CONTRASTS
    assert lock["branch"] == BRANCH and lock["parent"] == PARENT
    assert split["cohorts"]["pairs"] == registration["cohort"]["pairs"] == 8
    assert split["cohorts"]["holds"] == registration["cohort"]["holds"] == [4, 4]
    assert split["native"]["command"][1:] == registration["argv"][1:] == ["check","-p","uv-client","--locked","--offline","-j8"]
    signed, admission = lock["signed_release"], split["release"]
    assert admission["id"] == signed["release_id"] and admission["tag"] == signed["tag"] == "ohm-1.99.0-23"
    assert signed["manifest_sha256"] == amendment["manifest_sha256"] and signed["coordinator"] == admission["coordinator"] == amendment["merge"]
    assert signed["asset"]["id"] == admission["asset"] and signed["asset"]["digest"] == "sha256:" + admission["asset_sha256"]
    assert signed["sha256"] == admission["asset_sha256"] and signed["rustc"] == admission["rust"] == amendment["replacement_rust_pin"]
    assert signed["cargo"] == admission["cargo"] == amendment["replacement_cargo_pin"]
    assert lock["signed_cargo"] == admission["signed_cargo_sha256"] == lock["signed_cargo_row"]["sha256"]
    assert set(lock["raw"]) == set(lock["sources"]) == set(lock["effective_hashes"]) == {"R","S","F"}
    assert lock["signed_cargo"] == lock["raw"]["R"]["bin/cargo"]["sha256"]
    assert set(lock["builders"]) == {"S","F"}
    assert [lock["builders"][r]["role"] for r in ("S","F")] == split["build_roles"] == ["ctfe_control","full_with_ctfe"]
    assert lock["sources"]["R"] == {"commit":admission["rust"], "tree":amendment["replacement_rust_tree"], "epoch":26655, "metadata_epoch":3}
    assert lock["sources"]["S"] == SOURCE_S and lock["sources"]["F"] == SOURCE_F
    baseline(lock)
    verify_choice(choice, split, lock, pair)
    control = CONTRASTS[contrast]["control"]
    orders = [[control if role == "S" else role for role in row] for row in registration["cohort"]["orders"]]
    assert all(sorted(row) == sorted([control,"F"]) for row in orders)
    assert [row[0] for row in orders] == [control,"F","F",control,"F",control,control,"F"]
    return control, orders



def require_media(lock):
    """Refuse to allocate clocks from source-only projections or incomplete builder receipts."""
    for role in ("R", "S", "F"):
        raw = lock["raw"][role]
        assert {"bin/cargo","bin/rustc","bin/rustdoc"} <= set(raw)
        assert any(p.startswith("lib/librustc_driver-") and p.endswith(".so") for p in raw)
        assert any(p.startswith("lib/libLLVM.so.") for p in raw)
        assert any(p.startswith("lib/rustlib/x86_64-unknown-linux-gnu/lib/libstd-") for p in raw)
        effective = {}
        for path, data in raw.items():
            assert path == posixpath.normpath(path) and not path.startswith("/") and ".." not in path.split("/")
            assert type(data["bytes"]) is int and data["bytes"] >= 0 and re.fullmatch("[0-9a-f]{64}", data["sha256"])
            effective[path] = data["sha256"]
        effective["bin/cargo"] = lock["signed_cargo"]
        digest = hashlib.sha256(json.dumps(effective,sort_keys=True,separators=(",",":")).encode()).hexdigest()
        assert lock["effective_hashes"][role] == digest
    artifacts = set()
    for owner in ("S","F"):
        row = lock["builders"][owner]
        assert row["run"] > 0 and row["job"] > 0 and re.fullmatch("[0-9a-f]{40}", row["head"])
        assert re.fullmatch("[0-9a-f]{64}",row["archive_sha256"]) and row["archive_bytes"] > 0
        for kind, stem in (("qa","rc23-22958-qa-"),("sdk","rc23-22958-sdk-")):
            obj = row[kind]
            assert obj["name"] == stem+row["role"]+("-attempt-1" if kind=="qa" else "")
            assert obj["id"] > 0 and obj["size_in_bytes"] > 0 and re.fullmatch("sha256:[0-9a-f]{64}",obj["digest"])
            assert obj["id"] not in artifacts
            artifacts.add(obj["id"])


def verify_choice(choice, split, lock, pair):
    signed = lock["signed_release"]
    assert choice["schema"] == split["schema"] == 1 and choice["study"] == split["study"]
    assert choice["registration_sha256"] == REGISTRATION and choice["pair_sha256"] == NATIVE_PAIR
    assert choice["toolchain"] == signed["tag"] and choice["release_id"] == signed["release_id"]
    assert choice["signed_archive"] == "sha256:" + signed["sha256"]
    assert choice["commits"] == {"rust":signed["rustc"], "cargo":signed["cargo"]}
    assert choice["roles_after_actual_23_intake"] == split["build_roles"] and choice["contrasts"] == CONTRASTS
    assert choice["ordinary_samples"] == choice["original_decisions"] == 0 and choice["classification_only"] is False
    assert choice["physical_role_choice"] == "signed stock qualified on two uv openings; canonical CTFE corrected in both private builds"
    assert choice["distinct_uv_sidecars"] == [] and choice["five_visit_fixture"] == "specific_ctfe_B_mismatch"
    assert pair["scored_samples"] == pair["emitted_original_decisions"] == 0 and pair["initial_refusals"] == 2
    assert pair["qualified_defined_ordinary_case_only"] is True and pair["both_originals_genuinely_disagree_with_tiny_fixture"] is True
    assert pair["former_R_to_F_score"] is None and pair["reader_sha256"] == split["native"]["pair_reader"]
    assert pair["single_reader_sha256"] == split["native"]["single_reader"]
    assert pair["original_fixture"] == split["native"]["tiny_sha256"] and pair["original_native_sdk"] == split["native"]["installed_sdk_sha256"]
    one,two=pair["two_observations"]
    assert [one["cohort"],two["cohort"]] == split["native"]["histories"]
    assert all(one[k] == two[k] for k in ("actual_A","actual_B","graph","source_record","toolchain"))
    for k in ("A_seed","cold_B_seed"):
        assert one[k]["sha256"] != two[k]["sha256"]
    for k in ("cold-A","fresh-B"):
        assert one["kernel"][k]["original"] != two["kernel"][k]["original"]
    assert all(r["original_chooser"]["decision_sha"] is None and r["performance_samples"] == 0 for r in (one,two))
