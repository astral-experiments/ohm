"""Unchanged check_native from the terminal receiver. Offline artifact reads only."""
import paired

def check_native(z, boot, lock, control, choice, lock_sha):
    assert paired.member(z, "boot-attestation.json") == boot
    for field, path in (("inherited", "calibration.json"), ("threads", "per-rustc-calibration/calibration.json"),
                        ("blocking", "blocking-clock-pre/verified.json")):
        assert paired.digest(z.read(path)) == boot[field]
    cal = paired.member(z, "calibration.json")
    clock = paired.member(z, "blocking-clock-pre/verified.json")
    assert cal["unmultiplexed_calibration_clocks"] == 28 and clock["eligible_blocking_calibration"]
    assert cal["ready"]["boot"] == clock["boot"] == boot["boot"]
    assert cal["ready"]["affinity"] == clock["affinity"] == boot["affinity"]
    signed = lock["signed_release"]
    for path in ("intake/latest.json", "latest-after-study.json"):
        latest = paired.member(z, path)
        assert latest["immutable"] and not latest["draft"] and not latest["prerelease"]
        assert latest["id"] == signed["release_id"] and latest["tag_name"] == signed["tag"] == "ohm-1.99.0-23"
        assert latest["target_commitish"] == signed["coordinator"]
    intake = paired.member(z, "intake.json")
    assert intake["signed_cargo_sha256"] == lock["signed_cargo"] and intake["release_lock"] == lock_sha
    assert set(intake["installed"]) == {control, "F"}
    for role, sdk in intake["installed"].items():
        assert sdk["files"] == 142 and sdk["effective_inventory"] == lock["effective_hashes"][role]
        assert sdk["source"] == lock["sources"][role]
        opening = "native-22958/opening-" + role + "/"
        assert paired.member(z, opening + "independent-cold.json")["all_guarded"]
        for state in ("A", "B"):
            noop = paired.member(z, opening + "noedit-" + state + "/verified.json")
            assert noop["same_material"] and noop["forms"] == {}
    migration = paired.member(z, "intake/release-migration.json")
    assert migration["fixtures_only"] and migration["ordinary_benchmark_caches_separate"]
    for label in ("incremental", "metadata"):
        assert paired.digest(z.read(f"intake/{label}-boundary/passed.json")) == migration["native_format_proofs"][label]
    inc = paired.member(z, "intake/incremental-boundary/passed.json")
    meta = paired.member(z, "intake/metadata-boundary/passed.json")
    assert inc["signed_argv_refusal_both_directions"] and inc["same_sdk_self_loaded_before_and_after"]
    assert inc["no_header_edit"] and inc["no_compiler_version_override"] and inc["reader_compilations"] == 10
    assert meta["cross_crate_E0514"] == meta["own_crate_reads"] == meta["own_native_typecheck_errors"] == 2
    assert not meta["file_edits"] and not meta["compiler_version_overrides"]
    measured = paired.member(z, "native-22958/score.json")
    assert measured["registered"] == boot["registered"] and measured["release_lock"] == lock_sha
    assert measured["sources"] == lock["sources"] and measured["signed_release"] == signed["tag"]
    assert measured["control_kind"] == choice["physical_role_choice"] and "predeclared" in measured
