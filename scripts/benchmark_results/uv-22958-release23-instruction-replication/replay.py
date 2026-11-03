#!/usr/bin/env python3
"""Replay complete authenticated Actions archives offline, using Python 3.11+ and zstd."""
import argparse
import hashlib
import io
import json
from pathlib import Path
from statistics import median
import subprocess
import sys
import tempfile
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent
READER = ROOT / "reader"
sys.path.insert(0, str(READER))
import paired
import split_binding
import split_host
import terminal

HEAD = "aca48cdac3a4c37076a4e91ef53efa17d0144efc"
TREE = "cbcc4ad27e9d106a5dc1a2dd04e1da85068c50e3"
LOCK = "d5b6bd481827f274f858be917aaa62fe1a3a5567760c34d6ca211b3dc16862c8"
SLOTS = {"marginal-primary": 41577930987, "signed-primary": 41578145223,
         "marginal-repeat": 41579572319, "signed-repeat": 41579685157}
BASES = {"marginal-primary": None, "signed-primary": "marginal-primary",
         "marginal-repeat": "marginal-primary", "signed-repeat": "signed-primary"}
FILES = {"run.json", "jobs.json", "artifacts.json", "commit.json", "early-run.json",
         "early-jobs.json", "early-artifacts.json", "early-commit.json", "early.json",
         "boot.zip", "accepted.json", "reopened.json"}
REPEAT_FILES = {"repeat-registration.json", "repeat-placement.json", "repeat-verdict.json",
                "repeat-host-exclusion.json", "repeat-boot-service.json"}
METRICS = ("uv_configuration", "uv_client", "sum_two", "whole", "wall")


def need(ok, message):
    if not ok:
        raise ValueError(message)


def read(path):
    return json.loads(path.read_bytes())


def checked_file(row):
    path = ROOT / row["path"]
    need(path.resolve().is_relative_to(ROOT) and not path.is_symlink(), "unsafe packaged member")
    need(path.stat().st_size == row["bytes"] and paired.file_hash(path) == row["sha256"], str(path))
    return path


def restore(slot, entry, folder, raw_paths):
    """Undo the optional reference compression and compare the entire resulting service ZIP."""
    original = folder / "original.zip"
    reference = BASES[slot]
    need(entry["reference"] == reference and entry["run"] == SLOTS[slot], "wrong run or reference")
    cmd = ["zstd", "-q", "-d", "-c", "--long=28"]
    if reference:
        cmd.append("--patch-from=" + str(raw_paths[reference]))
    frame = hashlib.sha256()
    with original.open("xb") as out, subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=out) as proc:
        for part in entry["parts"]:
            path = checked_file(part)
            with path.open("rb") as source:
                while data := source.read(1 << 20):
                    frame.update(data)
                    proc.stdin.write(data)
        proc.stdin.close()
        need(proc.wait() == 0, "zstd could not reconstruct the original ZIP")
    need(frame.hexdigest() == entry["compressed_sha256"], "compressed frame differs")
    need(original.stat().st_size == entry["original"]["bytes"], "reconstructed ZIP length")
    need(paired.file_hash(original) == entry["original"]["sha256"], "reconstructed ZIP SHA-256")
    raw_paths[slot] = original
    return original


def open_receipts(slot, entry, folder):
    expected = FILES | (REPEAT_FILES if slot.endswith("-repeat") else set())
    with ZipFile(checked_file(entry["receipt"])) as bundle:
        need(set(bundle.namelist()) == expected and len(bundle.namelist()) == len(expected), "receipt names")
        need(sum(item.file_size for item in bundle.infolist()) < 8 << 20, "oversized receipt bundle")
        for name in expected:
            (folder / name).write_bytes(bundle.read(name))
    return read(folder / "accepted.json")


def context():
    frozen = {"signed-23-split-lock.json": LOCK, "signed-23-split-choice.json": split_binding.CHOICE,
              "split-prospective.json": split_binding.REGISTRATION, "split-pair.json": split_binding.NATIVE_PAIR,
              "prospective-23.json": split_binding.PROSPECTIVE, "r2-amendment.json": split_binding.AMENDMENT}
    for name, sha in frozen.items():
        need(paired.file_hash(READER / name) == sha, "wrong registration " + name)
    lock, choice, split, pair, original, amendment = [read(READER / name) for name in frozen]
    tiny = ROOT / "receipts/signed-ctfe.json"
    need(paired.file_hash(tiny) == pair["original_fixture"] and read(tiny)["checks"] == {
        "A_differs_from_B": True, "B_warm_equals_cold": False, "C_warm_equals_cold": True,
        "pointer_switch_changes_public_hash": True}, "published stock CTFE classification")
    refusal = paired.file_hash(ROOT / "receipts/stock-opening-refusal.log")
    need(all(r["original_chooser"]["native_refusal_log"] == refusal and r["original_chooser"]["decision_sha"] is None
             for r in pair["two_observations"]), "original single-choice refusal")
    split_binding.require_media(lock)
    groups = {key: split_binding.select(lock, original, amendment, choice, split, pair, key)
              for key in split_host.CONTRASTS}
    return dict(scope=split_binding, host=split_host, lock=lock, rule=split, groups=groups,
                head=HEAD, lock_sha=LOCK, tree=TREE)


def approved_endpoints(result):
    decision = result["verdict"]
    instr = decision["instruction_declarations"]
    need(set(instr) == {"uv_configuration", "uv_client", "sum_two"}, "registered instruction endpoints")
    return {"named": sorted(k for k, row in instr.items() if row["qualifies_20_percent"]),
            "wall": decision["qualifies_2x_on_this_host"]}


def check_repeat(slot, folder, accepted, observed, primary, primary_path, boot, known):
    reg = read(folder / "repeat-registration.json")
    place = read(folder / "repeat-placement.json")
    verdict = read(folder / "repeat-verdict.json")
    stamp, = read(folder / "repeat-host-exclusion.json").values()
    early_artifact = read(folder / "repeat-boot-service.json")
    need(stamp["run"] == accepted["run"] and stamp["job"] == accepted["job"] and stamp["head"] == HEAD and
         early_artifact["id"] == accepted["artifacts"]["boot"]["id"] and
         early_artifact["digest"] == "sha256:" + accepted["artifacts"]["boot"]["sha256"], "repeat calibration original")
    for field, member in (("archive", "boot.zip"), ("jobs", "early-jobs.json"), ("service", "repeat-boot-service.json")):
        need(stamp[field]["sha256"] == paired.file_hash(folder / member), "repeat placement service binding")
    other_hosts = {**reg["supplemental"], **place["extra"], **verdict["newly_added_hosts"]}
    with ZipFile(ROOT / "receipts/additional-calibrations.zip") as aux:
        for label, item in other_hosts.items():
            raws = {}
            for key, filename in (("archive", "boot.zip"), ("service", "artifact.json"), ("jobs", "jobs.json")):
                raws[key] = aux.read(label + "/" + filename)
                need(paired.digest(raws[key]) == item["refs"][key]["sha256"], "supplemental original")
            service = json.loads(raws["service"])
            need({k: service[k] for k in ("id", "digest", "size_in_bytes", "name")} == item["artifact"] and
                 service["digest"] == "sha256:" + paired.digest(raws["archive"]) and service["size_in_bytes"] == len(raws["archive"]),
                 "supplemental artifact")
            need(service["workflow_run"]["id"] == item["run"] and service["workflow_run"]["head_sha"] == item["head"] and
                 service["workflow_run"]["repository_id"] == split_host.REPOSITORY_ID, "supplemental run")
            job, = [v for v in json.loads(raws["jobs"])["jobs"] if v["id"] == item["job"]]
            need(job["run_id"] == item["run"] and job["head_sha"] == item["head"] and job["runner_id"] == item["runner_id"] and
                 job["runner_name"] == item["runner_name"], "supplemental job")
            with ZipFile(io.BytesIO(raws["archive"])) as archive:
                member, = archive.infolist()
                payload = archive.read(member)
            need(paired.digest(payload) == item["raw_sha256"] and json.loads(payload)["boot"] == item["boot"] and
                 all(item[k] != boot[k] for k in ("boot", "run", "job", "runner_id", "runner_name")), "supplemental calibration")
    need(any(i["artifact"]["name"] == "uv-22536-release23-boot" for i in other_hosts.values()),
         "independent secondary boot missing")
    reg_sha = paired.file_hash(folder / "repeat-registration.json")
    need(place["registered"] == verdict["registration_sha256"] == reg_sha, "repeat registration binding")
    need(place["before_result_archive_read"] and place["early"]["sha256"] == paired.file_hash(folder / "early.json"),
         "blind repeat host placement")
    need(boot["boot"] not in place["excluded_boots"] and
         set(place["excluded_boots"]) == set(reg["boot_census"]) | {v["boot"] for v in place["extra"].values()},
         "repeat boot exclusions")
    need(boot["runner_name"] not in reg["runner_names"] and boot["runner_id"] not in reg["runner_ids"],
         "repeat runner exclusions")
    need(all(row["boot"] in place["excluded_boots"] or row["boot"] in
             {v["boot"] for v in verdict["newly_added_hosts"].values()} for row in known.values()),
         "prior measurement host missing from repeat exclusions")
    need(reg["head"] == accepted["head"] == HEAD and reg["lock"] == accepted["release_lock"] == LOCK and
         reg["contrast"] == accepted["contrast"] == verdict["contrast"], "repeat source or cohort differs")
    need(verdict["original"] == reg["original"] and reg["original"]["sha256"] == paired.file_hash(primary_path / "accepted.json")
         and reg["reopened"]["sha256"] == paired.file_hash(primary_path / "reopened.json"), "primary decision changed")
    need(verdict["repeat"]["sha256"] == paired.file_hash(folder / "accepted.json") and
         verdict["checked_boot"]["sha256"] == paired.file_hash(folder / "repeat-placement.json"), "external verdict material")
    first = approved_endpoints(primary)
    second = approved_endpoints(observed)
    need(first == reg["eligible"] == verdict["first"] and (first["named"] or first["wall"]) and second == verdict["second"],
         "incorrect repeat eligibility")
    names = sorted(set(first["named"]) & set(second["named"]))
    wall = first["wall"] and second["wall"]
    need(verdict["replicated_named_endpoints"] == names and verdict["replicated_2x_bare_wall"] == wall, "repeat verdict")
    return {"named": names, "wall": wall, "external_sha256": paired.file_hash(folder / "repeat-verdict.json")}


def witness(z, path, expected):
    record = paired.member(z, path + "/witness.json")
    actual = {"codes": record["codes"], "linked": {k: v.get("actual", v.get("error")) for k, v in record["linked"].items()},
              "module": record["module"], "unchanged": record["verified_unchanged_client_methods"]}
    need(actual == expected, "typed and linked witness: " + path)


def native_rows(z, roles):
    cold = {}
    signed_pair = read(READER / "split-pair.json")["two_observations"]
    guards = paired.member(z, "native-22958/all-native-guards.json")
    for role in roles:
        base = f"native-22958/opening-{role}/"
        opening = paired.member(z, base + "admitted.json")
        for state in ("A", "B"):
            need(all(opening[state+"_observable"] == src["actual_"+state] for src in signed_pair),
                 "typed or linked native result changed")
        for name, state in (("cold-A", "A"), ("initial-kernel", "B"), ("fresh-B", "B")):
            witness(z, base + name + "/native", opening[state + "_observable"])
        warm = paired.member(z, base + "initial-kernel/products.json")
        fresh = paired.member(z, base + "fresh-B/products.json")
        need(warm == paired.member(z, base + "initial-bare/products.json"), "same-seed bare opening")
        need(warm["all_public_sidecars"] == fresh["all_public_sidecars"] and
             len(warm["all_public_sidecars"]) == 423, "public sidecars on independent cold B")
        need(set(warm["workspace"]) == set(fresh["workspace"]) and len(warm["workspace"]) == 39,
             "workspace product roster")
        changed = {k for k, v in warm["workspace"].items() if fresh["workspace"][k] != v}
        row = paired.member(z, base + "independent-cold.json")
        need(row["all_guarded"] and row["all_workspace"] == 39 and changed == set(row["changes"]).intersection(warm["workspace"]),
             "independent fresh workspace check")
        for owner in row["fixed_input_owners_required"]:
            fix = paired.member(z, base + f"fixed-input-{owner}/fixed.json")
            need(fix["qualified"] and fix["owner"] == owner and fix["source"] == paired.EDIT and fix["stable_inputs"],
                 "fixed-input evidence")
            need(set(fix["coverage"]) <= set(guards["fixed"][role][owner]) and
                 [fix["rows"][str(i)]["threads"] for i in range(4)] == [8, 1, 1, 8] and
                 all(r["fixed_inputs"] == fix["stable_inputs"] for r in fix["rows"].values()) and
                 len({r["rmeta"][1] for r in fix["rows"].values()}) >= 2, "fixed-input roster")
        cold[role] = {"different_workspace": len(changed), "different_all_recorded": len(row["changes"]),
                      "fixed_input_owners": row["fixed_input_owners_required"],
                      "raw_all_exact": row["raw_all_exact"]}
        for n in range(1, 9):
            prefix = f"native-22958/{n}-{role}/"
            argv = paired.member(z, prefix + "kernel-B/forms.json")
            need(argv == {k: [v] for k, v in opening["full_first_B_argv"].items()}, "original first-edit argv")
            witness(z, prefix + "new-cold-A/native", opening["A_observable"])
            for visit in ("kernel-B", "wall", "whole", "threads"):
                witness(z, prefix + visit + "/native", opening["B_observable"])
            prod = paired.member(z, prefix + "kernel-B/products.json")
            need(len(prod["workspace"]) == 39 and len(prod["all_public_sidecars"]) == 423, "actual product/sidecar scope")
            bare = paired.member(z, prefix + "wall/products.json")
            need(prod == bare, "same-seed native and bare products")
    return cold


def reduce_run(slot, entry, work, ctx, all_runs, raw_paths, hosts):
    contrast, attempt = slot.split("-")
    rid = SLOTS[slot]
    folder = work / slot
    folder.mkdir()
    accepted = open_receipts(slot, entry, folder)
    values = lambda prefix: [read(folder / (prefix + n + ".json")) for n in ("run", "jobs", "artifacts", "commit")]
    early = read(folder / "early.json")
    previous = None if contrast == "marginal" else hosts["marginal-primary"]
    recorded = terminal.unlock_boot(ctx, values("early-"), rid, contrast, folder, previous)
    need(early == recorded["form"] and all(accepted[k] == v for k, v in early.items()), "wrong early receipt")
    final_values = values("")
    need(final_values[0]["status"] == "completed" and final_values[0]["conclusion"] == "success" and
         final_values[1]["jobs"][0]["conclusion"] == "success", "unsuccessful run or job")
    live = terminal.unlock_boot(ctx, final_values, rid, contrast, folder, previous)
    need(live["form"] == early, "terminal/early host mismatch")
    assignment, items = terminal.opened(ctx, final_values, rid, contrast)
    remotes = {k: {"name": v["name"], "id": v["id"], "bytes": v["size_in_bytes"], "sha256": v["digest"][7:]}
               for k, v in items.items()}
    need(remotes == accepted["artifacts"] and entry["original"] == remotes["original"], "service artifacts mismatch")
    boot = recorded["boot"]
    for field in ("boot", "runner_id", "runner_name", "run", "job"):
        need(all(other["boot"][field] != boot[field] for other in hosts.values()), "duplicate measured host: " + field)
    # The independent repeat owner issued these receipts before this adapter may open the score archive.
    old_reduction = read(folder / "reopened.json")
    need(paired.file_hash(folder / "reopened.json") == accepted["reopened_sha256"], "externally accepted reduction")
    verified = None
    if attempt == "repeat":
        verified = check_repeat(slot, folder, accepted, old_reduction, all_runs[contrast+"-primary"],
                                work / (contrast+"-primary"), boot, {k: v["boot"] for k, v in hosts.items()})
    original = restore(slot, entry, folder, raw_paths)
    control, orders = ctx["groups"][contrast]
    with ZipFile(original) as z:
        score_sha = terminal.check_complete(ctx, z, live, contrast, previous, assignment)
        need(score_sha == accepted["score_sha256"] and accepted["sources"] ==
             {r: ctx["lock"]["sources"][r] for r in (control, "F")}, "wrong score or installed sources")
        cold = native_rows(z, (control, "F"))
    actual = paired.reopen(original, remotes["original"]["sha256"], (control, "F"), orders, boot["boot"],
                           READER / "verify-eight.py", READER / "release23_verdict.py")
    need(actual == old_reduction, "raw reduction disagrees with external admission")
    ea = approved_endpoints(actual)
    need(sorted(accepted["independent_replication_eligible"]["named_instruction_endpoints"]) == ea["named"] and
         accepted["independent_replication_eligible"]["bare_wall"] == ea["wall"], "eligibility differs")
    hosts[slot] = recorded
    all_runs[slot] = actual
    medians = {}
    for metric, pairs in actual["raw"].items():
        c = [p[0] for p in pairs]
        t = [p[1] for p in pairs]
        medians[metric] = {"control": median(c), "treatment": median(t),
                           "paired_median_reduction_pct": 100 * (1 - median(b / a for a, b in pairs)),
                           "paired_median_speedup": median(a / b for a, b in pairs)}
    return {"run": rid, "job": boot["job"], "contrast": contrast, "attempt": attempt, "control": control, "treatment": "F",
            "boot": boot["boot"], "runner_id": boot["runner_id"], "runner_name": boot["runner_name"], "archives": remotes,
            "order": orders, "independent_histories": 16, "native": cold, "raw": actual["raw"],
            "compiler_traces": actual["compiler_traces"], "compiler_executions": actual["compiler_executions"],
            "medians": medians, "verdict": actual["verdict"], "replicated": verified}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--emit", action="store_true", help="Print the full independently computed JSON")
    p.add_argument("--controls", action="store_true", help="Run eight adverse checks on the first raw archive")
    p.add_argument("--primary-only", action="store_true", help="Replay only the two independently admitted primaries")
    args = p.parse_args()
    need(__debug__, "run without Python optimization: the pinned native readers use assertions")
    manifest = read(ROOT / "manifest.json")
    required = list(SLOTS)[:2] if args.primary_only else list(SLOTS)
    need(manifest["version"] == 1 and all(slot in manifest["runs"] for slot in required), "requested original or verdict is absent")
    ctx = context()
    table = {}
    with tempfile.TemporaryDirectory(prefix="uv-22958-r23-") as tmp:
        all_runs, raw_paths, hosts = {}, {}, {}
        for slot in required:
            table[slot] = reduce_run(slot, manifest["runs"][slot], Path(tmp), ctx, all_runs, raw_paths, hosts)
        if args.controls:
            import controls
            slot = "marginal-primary"
            n = controls.run(raw_paths[slot], table[slot], all_runs[slot])
            print(f"Passed {n} adverse service, PID, counter, clock and decision checks.", file=sys.stderr)
    if args.emit:
        print(json.dumps(table, indent=2, sort_keys=True))
    else:
        expected = read(ROOT / "paired-results.json")
        need(table == {k: expected[k] for k in required}, "published result table")
        print(f"Verified {len(required)} original Actions ZIPs, {32 * len(required)} per-rustc PMU records, "
              f"{16 * len(required)} inherited whole-Cargo PMUs and {16 * len(required)} bare wall clocks.")
        for k in required:
            r = table[k]
            print(k, r["run"], r["boot"], json.dumps(r["replicated"] or approved_endpoints(r), sort_keys=True))
if __name__ == "__main__":
    main()
