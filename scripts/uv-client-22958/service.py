"""Apply the original two-SDK authority and its calibrated PMU to the separately locked uv case."""

from pathlib import Path
import json
import os
import re
import sys
import uuid

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "uv-callables-21041"))
import core as old

sys.path.insert(0, str(HERE))
m = old.m
case = m.read(HERE / "case.json")
register = m.read(HERE / "registration.json")
assert (
    m.filesha(HERE / "registration.json")
    == case["registered"]
    == "2d2ad20912693be58458ec355dea335e2967c0a6dd3da80e2ef43ac70640f658"
)
assert old.PAIR["arms"] == case["upstream_native_inputs"]
old.P.update(
    branch=case["branch"],
    parent=case["parent"],
    edited_workspace_roster=["uv_client", "uv_configuration"],
)
ROLES = old.ROLES
CHECK = old.CHECK = [
    str(m.SDK / "bin/cargo"),
    *register["complete_original_ordinary_argv"][1:],
]
assert CHECK[1:] == ["check", "-p", "uv-client", "--locked", "--offline", "-j8"]
for name, role in zip(("mature", "callable"), ROLES, strict=True):
    reg = register["artifact_identity"][name]
    arm = old.PAIR["arms"][role]
    assert (
        reg["artifact"] == arm["artifact"]
        and reg["source"]["commit"] == arm["source"]["commit"]
        and reg["source"]["tree"] == arm["source"]["tree"]
    )
m.ENV.update(
    LC_ALL="C",
    GIT_CONFIG_NOSYSTEM="1",
    GIT_CONFIG_GLOBAL="/dev/null",
    GIT_ALLOW_PROTOCOL="file",
    GIT_NO_LAZY_FETCH="1",
    RUSTC_BOOTSTRAP="1",
)
m.ENV.pop("CARGO_TERM_COLOR", None)


def host():
    w, tmp = old.host()
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    excluded = os.environ["EXCLUDED_PRODUCTION_BOOT"].split(",")
    assert 1 <= len(excluded) == len(set(excluded)) <= 8 and all(
        str(uuid.UUID(x)) == x for x in excluded
    )
    for key, row in case["required_production_boots"].items():
        assert (
            key in excluded
            and m.filesha(HERE / row["raw_file"]) == row["raw_sha256"]
            and m.read(HERE / row["raw_file"])["ready"]["boot"] == key
        )
    assert boot not in excluded and os.environ["GITHUB_REPOSITORY_ID"] == "1319437234"
    return w, tmp, boot


def main(mode):
    w, tmp, boot = host()
    out = w / "trait-results"
    if mode == "calibrate":
        m.pmu(w, tmp)[0].calibrate()
        obj = m.read(out / "calibration.json")
        assert (
            obj["ready"]["boot"] == boot
            and obj["unmultiplexed_calibration_clocks"] == 28
        )
        import scoped

        mask = set(obj["ready"]["affinity"])
        assert mask <= os.sched_getaffinity(0)
        os.sched_setaffinity(0, mask)
        scoped.calibrate()
        receipt = dict(
            boot=boot,
            workspace=str(w),
            excluded=os.environ["EXCLUDED_PRODUCTION_BOOT"],
            run=int(os.environ["GITHUB_RUN_ID"]),
            job="root",
            coordinator=os.environ["REVIEWED_HEAD"],
            inherited=m.filesha(out / "calibration.json"),
            threads=m.filesha(out / "per-rustc-calibration/calibration.json"),
            affinity=sorted(mask),
            registered=case["registered"],
        )
        m.save(out / "boot-attestation.json", receipt)
        print(json.dumps(receipt, sort_keys=True), flush=True)
    elif mode == "admit":
        import admit_pair

        admit_pair.admit()
    elif mode == "migration":
        import admit_pair

        admit_pair.migration()
    elif mode == "study":
        import native

        native.run()
    elif mode == "reduce":
        import result

        result.close(out)
    else:
        raise ValueError(mode)


if __name__ == "__main__":
    main(*sys.argv[1:])
