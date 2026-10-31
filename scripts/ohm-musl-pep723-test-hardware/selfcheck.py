"""Exercise the new boundaries offline. Every simulated instruction value is artificial."""

import argparse
import copy
import gzip
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support as q
import score
import trace_checks
import stage


def refused(fn, reason):
    try:
        fn()
    except (AssertionError, ValueError, KeyError, RuntimeError, FileNotFoundError):
        return reason
    raise AssertionError("unexpected acceptance: " + reason)


def main(args):
    ledger = {"fresh_PMU_or_Ruff_commands": 0, "synthetic_endpoints_only": True, "mutations": []}
    prior = q.archive_oracle(args.original)
    [ident] = set(v["full_typed_roster"] for arm in prior.values() for v in arm.values())
    ledger["original_36_unit_roster"] = ident
    ledger["original_22_visit_artifact"] = q.file_sha(args.original)
    refused(lambda: q.gate(Path("/nonexistent")), "held permission")
    with mock.patch.object(
        stage, "request", side_effect=AssertionError("network used before clearance")
    ) as remote:
        try:
            stage.acquire(argparse.Namespace(clearance=Path("/nonexistent")))
        except ValueError as e:
            assert "HOLD" in str(e)
        else:
            raise AssertionError("acquired while held")
        remote.assert_not_called()
    ledger["held_acquisition"] = "refused before any network access"
    with tempfile.TemporaryDirectory() as t:
        w = Path(t)
        qa = w / "qualification"
        # The original checkout is a read-only object donor. Its active branch can advance.
        subprocess.run(
            ["git", "clone", "--quiet", "--shared", "--no-checkout", args.qual_donor, qa], check=True
        )
        subprocess.run(
            [
                "git",
                "-C",
                qa,
                "sparse-checkout",
                "set",
                "--no-cone",
                "/scripts/ohm-musl-ast-pair/v2/evidence.py",
            ],
            check=True,
        )
        subprocess.run(
            ["git", "-C", qa, "checkout", "--quiet", "--detach", q.REG["provider_head"]], check=True
        )
        case, meter, _, products, ev = q.modules(args.structural, args.hardware, qa)
        products.storage_calibration(w, w)
        alloc_dir = w / "storage-calibration"
        orig_alloc = json.loads((alloc_dir / "storage.json").read_bytes())
        raw_rows = json.loads(gzip.decompress((alloc_dir / "allocated-inodes.json.gz").read_bytes()))
        actual = score.allocated(raw_rows)
        assert all(orig_alloc[k] == v for k, v in actual.items())
        assert actual["physical_payloads"] == {".o": 2} and list(
            actual["exact_duplicate_payloads"].values()
        ) == [2]
        altered = copy.deepcopy(raw_rows)
        next(x for x in altered if x[0] == "shared/alias.o")[5] += 1
        ledger["mutations"].append(
            refused(lambda: score.allocated(altered), "inconsistent hardlink allocation")
        )
        ledger["disk_control"] = (
            "actual sparse file, symlink, same-inode alias and independently allocated duplicate, checked against GNU du and second reader"
        )
        ledger["proven_consecutive_source"] = q.file_sha(Path(meter.__file__))
        ledger["kernel_parser_source"] = q.file_sha(Path(ev.__file__))
        results = []
        with zipfile.ZipFile(args.original) as zz:
            ledger["trace_fixtures"] = trace_checks.exercise(zz, refused)
            for pos, roles in [(1, "PC"), (2, "CP")]:
                record = {
                    "position": pos,
                    "order": roles,
                    "boot": f"synthetic-{pos}",
                    "host": f"host-{pos}",
                    "runner": f"runner-{pos}",
                    "head": "unscored-test",
                    "run": "unscored-test",
                    "counts": {},
                }
                for role in roles:
                    folder = w / ("mock-" + str(pos) + role)
                    folder.mkdir()
                    watch = w / "never-executed"
                    names = []
                    real_reads = []
                    data = [
                        gzip.decompress(zz.read(f"{role}/{v}/stdout.gz")) for v in ("edit", "unchanged")
                    ]
                    oldread = Path.read_bytes

                    def monitor(p):
                        if p.is_relative_to(folder):
                            real_reads.append((len(names), str(p)))
                        return oldread(p)

                    def synthetic(argv, **k):
                        n = len(names)
                        phase = ("edit", "repeat")[n]
                        dest = folder / phase
                        assert (
                            argv == [watch, dest / "clock.json", *q.REG["ordinary_argv"]]
                            and k["cwd"] == w
                        )
                        assert k["env"] == {"OFFLINE_VALIDATION_ONLY": "yes"} and not real_reads
                        assert all(
                            (folder / v / f).exists()
                            for v in ["edit", "repeat"]
                            for f in ["stdout.raw", "stderr.raw"]
                        )
                        q.write(
                            dest / "clock.json",
                            {
                                "event_errno": 0,
                                "code": 0,
                                "instructions": {"P": 120, "C": 55}[role] + n,
                                "start": 11 + n * 2,
                                "stop": 12 + n * 2,
                                "running": 200,
                                "enabled": 200,
                                "user_us": 1,
                                "system_us": 0,
                            },
                        )
                        k["stdout"].write(data[n])
                        k["stderr"].write(b"fixture\n")
                        names.append(phase)
                        return subprocess.CompletedProcess(argv, 0)

                    with mock.patch.object(Path, "read_bytes", monitor):
                        v = meter.consecutive(
                            watch, folder, {"OFFLINE_VALIDATION_ONLY": "yes"}, w, runner=synthetic
                        )
                    assert (
                        names == ["edit", "repeat"]
                        and real_reads
                        and all(n == 2 for n, _ in real_reads)
                    )
                    record["counts"][role] = {key: score.clock(v[key]["clock"]) for key in names}
                    for key in names:
                        assert q.typed(v[key]["stdout"])[0] == prior[role][key]
                results.append(record)
            text = gzip.decompress(zz.read("P/edit/stdout.gz"))
            msgs = [json.loads(line) for line in text.splitlines()]

            def encode():
                return b"\n".join(json.dumps(m).encode() for m in msgs)

            root = next(m for m in msgs if m["reason"] == "compiler-artifact" and m.get("executable"))
            root["profile"]["test"] = False
            ledger["mutations"].append(refused(lambda: q.typed(encode()), "wrong test/lib selection"))
            root["profile"]["test"] = True
            msgs.pop()
            ledger["mutations"].append(
                refused(lambda: q.typed(encode()), "missing final build-finished")
            )
        synth = score.paired_ratios(results)
        assert synth["eligible_to_propose_larger_confirmation"]
        assert synth["positions"][0]["ratios"]["edit+repeat"]["exact"] == "241/111"
        r = copy.deepcopy(results)
        r[1]["counts"]["C"]["repeat"] = 100
        assert not score.paired_ratios(r)["eligible_to_propose_larger_confirmation"]
        r = copy.deepcopy(results)
        r[1]["boot"] = r[0]["boot"]
        ledger["mutations"].append(refused(lambda: score.paired_ratios(r), "duplicate boot"))
        for ident in ["host", "runner"]:
            r = copy.deepcopy(results)
            r[1][ident] = r[0][ident]
            ledger["mutations"].append(refused(lambda: score.paired_ratios(r), "duplicate " + ident))
        r = copy.deepcopy(results)
        r[1]["order"] = "PC"
        ledger["mutations"].append(refused(lambda: score.paired_ratios(r), "wrong second order"))
        r = copy.deepcopy(results)
        r[0]["boot"] = q.REG["screen"]["excluded_boot_ids"][0]
        ledger["mutations"].append(refused(lambda: score.paired_ratios(r), "historical visitor boot"))
        ledger["counter_boundary"] = (
            "all four stream FDs existed before the first fake command; no result/file was inspected until both fake commands exited, in PC and CP"
        )
    # Only calibration files are opened. Neither preceding hosted workflow's partial Ruff clocks are read.
    historical = [
        ("01", "2a30ac5f9d11b96ad12c30849471e30e27f07110fe3460c7e05eea3d8a4ad180"),
        ("02", "e84e00bb86c558f41970816dc1838bd7a7d60c5a8b62475f0cbcbedc4706f334"),
    ]
    ledger["calibration_components"] = []
    for n, sha in historical:
        path = args.calibration / (n + ".zip")
        assert q.file_sha(path) == sha
        with zipfile.ZipFile(path) as z:
            read = lambda leaf: z.read("musl-measurements/calibration/" + leaf)
            score.calibration(read)
            forgery = json.loads(read("9.json"))
            forgery["running"] = 0
            ledger["mutations"].append(
                refused(
                    lambda: score.calibration(
                        lambda leaf: json.dumps(forgery).encode() if leaf == "9.json" else read(leaf)
                    ),
                    "multiplexed or disabled calibration " + n,
                )
            )
            ledger["calibration_components"].append([n, sha, 28])
    return ledger


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for n in ["original", "structural", "hardware", "qual-donor", "calibration"]:
        p.add_argument("--" + n, type=Path, required=True)
    print(json.dumps(main(p.parse_args()), sort_keys=True, indent=2))
