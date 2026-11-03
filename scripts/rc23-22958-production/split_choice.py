"""Validate the two real stock uv openings and preserve the earlier classifier's refusal."""
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
REGISTRATION = "4d17e7b41ca0e422174b0ae43a9a0b4aee25c72e58ac2be6989751e95a65d58c"
PAIR = "c5d25c2c448e04cacb05da0b8d909afd23cd5bd7fd2d87965385e30b44b93377"


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def make_choice(directory):
    q = Path(directory)
    reg_path = HERE / "split-registration.json"
    assert sha(reg_path) == REGISTRATION and sha(q / "split-pair.json") == PAIR
    reg, pair = read(reg_path), read(q / "split-pair.json")
    release, native = reg["release"], reg["native"]
    role, intake = read(q / "signed-role.json"), read(q / "intake.json")
    assert role["tag"] == intake["tag"] == release["tag"] and role["release_id"] == intake["release_id"] == release["id"]
    assert role["rust"] == release["rust"] and role["cargo"] == release["cargo"]
    assert role["runtime"]["bin/cargo"] == release["signed_cargo_sha256"]
    assert role["signed_archive"]["digest"] == intake["asset"]["digest"] == "sha256:" + release["asset_sha256"]
    assert intake["asset"]["id"] == release["asset"]
    tiny = read(q / "native-ctfe.json")
    checks = {"A_differs_from_B": True, "B_warm_equals_cold": False, "C_warm_equals_cold": True,
              "pointer_switch_changes_public_hash": True}
    assert tiny["checks"] == checks and pair["initial_refusals"] == 2 and pair["emitted_original_decisions"] == 0
    assert pair["scored_samples"] == 0 and pair["former_R_to_F_score"] is None
    assert pair["qualified_defined_ordinary_case_only"] and pair["both_originals_genuinely_disagree_with_tiny_fixture"]
    assert pair["original_native_sdk"] == native["installed_sdk_sha256"] == sha(q / "actual-linux-sdk.json")
    assert pair["original_fixture"] == native["tiny_sha256"] == sha(q / "native-ctfe.json")
    assert pair["reader_sha256"] == native["pair_reader"] and pair["single_reader_sha256"] == native["single_reader"]
    rows = pair["two_observations"]
    assert [row["cohort"] for row in rows] == native["histories"]
    origins = []
    for row in rows:
        name = row["cohort"]
        review_path, refusal_path = q / (name + "-review.json"), q / (name + "-refusal.json")
        review, refusal = read(review_path), read(refusal_path)
        assert row["supplement"] == sha(review_path) and row["all_prospective_checks"] == review
        assert row["original_chooser"] == refusal and refusal["decision_sha"] is None
        assert sha(q / (name + "-physical.json")) == refusal["physical_sha"] == review["physical"]
        assert read(q / (name + "-physical.json"))["exit"] == review["original_exit"] == 1
        assert refusal["reader_sha256"] == native["old_choice_reader"] and not review["prior_roles_to_build"]
        assert row["toolchain"] == review["release_role"] == sha(q / "signed-role.json")
        assert review["native_conditions"] == checks and review["ordinary_first_B_rustcs"] == ["uv_client", "uv_configuration"]
        assert row["performance_samples"] == review["scored_samples"] == 0 and row["separate_studies"]
        assert review["sidecars_equal"] == 423 and review["physical_workspace_outputs"] == 39
        assert review["all_available_typed_checks"] and row["native_warm_cold_file"] == review["typed_receipt"]
        assert sha(q / (name + "-typed.json")) == review["typed_receipt"]
        assert row["kernel"]["cold-A"]["n"] == row["kernel"]["fresh-B"]["n"] > 400
        assert row["kernel"]["initial-kernel"]["n"] == 2
        fixed = review["all_fixed_input_controls"]
        assert set(fixed) == {"uv_client", "uv_extract"}
        for owner, proof in fixed.items():
            assert [v["threads"] for v in proof["actual_original_units"]] == native["fixed_threads"]
            assert proof["distinct_native_encodings"] >= 2
            assert sha(q / (name + "-" + owner + "-fixed.json")) == proof["fixed_source_receipt"]
        origins.append({"cohort": name, "typed": review["typed_receipt"], "physical": review["physical"],
                        "review": sha(review_path), "original_refusal": sha(refusal_path)})
    for field in ("A_seed", "cold_B_seed"):
        assert rows[0][field]["sha256"] != rows[1][field]["sha256"]
    for phase in ("cold-A", "fresh-B"):
        assert rows[0]["kernel"][phase]["original"] != rows[1]["kernel"][phase]["original"]
    assert all(rows[0][key] == rows[1][key] for key in ("source_record", "toolchain", "graph", "actual_A", "actual_B"))
    return {"schema": 1, "study": reg["study"], "registration_sha256": REGISTRATION, "pair_sha256": PAIR,
            "toolchain": release["tag"], "release_id": release["id"], "signed_archive": role["signed_archive"]["digest"],
            "commits": {"rust": release["rust"], "cargo": release["cargo"]},
            "roles_after_actual_23_intake": reg["build_roles"], "contrasts": reg["contrasts"],
            "five_visit_fixture": "specific_ctfe_B_mismatch", "distinct_uv_sidecars": [],
            "physical_role_choice": "signed stock qualified on two uv openings; canonical CTFE corrected in both private builds",
            "ordinary_samples": 0, "original_decisions": 0, "classification_only": False, "openings": origins}
