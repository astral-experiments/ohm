"""Bind the source-qualified -23 cohort to the independent signed-SDK decision."""

PROSPECTIVE = "58596f3d7dde5ce7236c3c59fdbabfc5ffea72ba0db3363ec76c233a08026264"
AMENDMENT = "345be518fbc300e8c48d47ea09820a286a98b5eb5af0a93fd96fc754ce5a4f3b"


def select(lock, registration, amendment, choice):
    release = lock["signed_release"]
    assert amendment["registration"] == PROSPECTIVE
    assert choice["toolchain"] == release["tag"] == "ohm-1.99.0-23"
    assert not choice["classification_only"] and choice["ordinary_samples"] == 0
    assert release["release_id"] == choice["release_id"]
    assert choice["signed_archive"] == "sha256:" + release["sha256"]
    assert release["coordinator"] == amendment["merge"]
    assert release["manifest_sha256"] == amendment["manifest_sha256"]
    assert choice["commits"] == {
        "rust": amendment["replacement_rust_pin"],
        "cargo": amendment["replacement_cargo_pin"],
    }
    assert release["rustc"] == choice["commits"]["rust"] and release["cargo"] == choice["commits"]["cargo"]
    builders = lock["builders"]
    sources = lock["sources"]
    roles = choice["roles_after_actual_23_intake"]
    if choice["physical_role_choice"] == "published stock":
        assert roles == ["full_without_ctfe"] and set(builders) == {"F"}
        assert choice["five_visit_fixture"] == "passed" and not choice["distinct_uv_sidecars"]
        control = "R"
        assert sources[control] == {"commit": release["rustc"], "tree": amendment["replacement_rust_tree"],
                                    "epoch": 26655, "metadata_epoch": 3}
    else:
        assert choice["physical_role_choice"] == "matched correction required"
        assert roles == ["ctfe_control", "full_with_ctfe"] and set(builders) == {"S", "F"}
        assert choice["five_visit_fixture"] == "specific_ctfe_B_mismatch"
        assert len(choice["distinct_uv_sidecars"]) == 1
        control = "S"
    assert set(sources) == {control, "F"}
    assert [builders[key]["role"] for key in (control, "F") if key in builders] == roles
    for field in ("commit", "tree", "epoch", "metadata_epoch"):
        assert sources[control][field] != sources["F"][field]
    assert registration["cohort"]["pairs"] == 8 and registration["cohort"]["holds"] == [4, 4]
    orders = [[control if role == "S" else role for role in order] for order in registration["cohort"]["orders"]]
    assert [order[0] for order in orders] == [control, "F", "F", control, "F", control, control, "F"]
    return control, orders
