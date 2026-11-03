"""Replay the original uv #21134 scorer from the compact packet, or reopen the full native archives."""
import argparse
import csv
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parents[1]
sys.path.insert(0, str(SCRIPTS / "uv-check-21134"))
import common
import custody
import score

HEAD = "0eaa9388c5a8539ed982b74200592c6800c692de"
VERDICT = "b61d60b43a31ff4c8f85a145270027b9b1e0a3991a0a65af456161f113b8a745"
RUNS = ["41607449517", "41608956208"]
NATIVE = HERE / "native-v4"


def check(value, message):
    if not value:
        raise ValueError(message)


def csv_text(columns, rows):
    output = io.StringIO()
    writer = csv.writer(output, delimiter="\t", lineterminator="\n")
    writer.writerow(columns)
    writer.writerows(rows)
    return output.getvalue()


def unpack(packet, directory):
    """Verify every uncompressed member before giving anything to the original reader."""
    pool = directory / "payloads"
    pool.mkdir()
    sizes = packet["payloads"]
    check(0 < sum(sizes.values()) <= 512 << 20, "payload size")
    seen = set()
    with tarfile.open(HERE / "original-members.tar.xz", "r|xz") as archive:
        for member in archive:
            h = member.name
            check(re.fullmatch("[a-f0-9]{64}", h) and h not in seen, "member name or duplicate")
            check(member.isfile() and member.size == sizes[h] <= 12 << 20, "member size or type")
            data = archive.extractfile(member).read()
            check(hashlib.sha256(data).hexdigest() == h, "member sha256")
            (pool / h).write_bytes(data)
            seen.add(h)
    check(seen == sizes.keys(), "incomplete byte packet")
    for run, group in packet["hosts"].items():
        check(run in RUNS, "unexpected service run")
        for category in ("members", "service", "native"):
            for name, digest in group[category].items():
                path = Path(name)
                check(not path.is_absolute() and ".." not in path.parts, "member path")
                target = directory / run / category / path
                target.parent.mkdir(parents=True, exist_ok=True)
                os.link(pool / digest, target)


def service(folder, files, enrolled):
    """The small early ZIP and official responses survive intact; the full original has a receipt."""
    run = common.read(folder / "run.json")
    jobs = common.read(folder / "jobs.json")
    artifacts = common.read(folder / "artifacts.json")
    check(common.read(folder / "owner-custody.json") == enrolled, "original custody")
    check(run["id"] == enrolled["run"] and run["head_sha"] == HEAD, "service run or source")
    check(run["repository"]["id"] == run["head_repository"]["id"] == 1319437234, "repository")
    check(run["repository"]["full_name"] == "astral-experiments/ohm", "repository name")
    check(run["event"] == "workflow_dispatch" and run["run_attempt"] == 1, "run origin")
    check(run["status"] == "completed" and run["conclusion"] == "success", "run outcome")
    check(len(jobs["jobs"]) == jobs["total_count"] == 1, "job population")
    job, = jobs["jobs"]
    check(job["id"] == enrolled["job"] and job["runner_id"] == enrolled["runner_id"], "physical worker")
    check(job["run_id"] == run["id"] and job["head_sha"] == HEAD and job["conclusion"] == "success", "job")
    records = {x["name"]: x for x in artifacts["artifacts"]}
    check(len(records) == artifacts["total_count"] == 2, "artifact population")
    for kind, receipt in enrolled["originals"].items():
        row = records[f"uv-21134-{enrolled['series']}-{kind}"]
        check([row["id"], row["size_in_bytes"], row["digest"]] ==
              [receipt["id"], receipt["size"], "sha256:" + receipt["sha256"]], "Actions artifact identity")
        check(row["workflow_run"]["id"] == run["id"] and row["workflow_run"]["head_sha"] == HEAD,
              "artifact service head")
    early = enrolled["originals"]["boot"]
    check(common.blob(folder / "boot.zip") == [early["size"], early["sha256"]], "early ZIP identity")
    with zipfile.ZipFile(folder / "boot.zip") as boot:
        check(boot.namelist() == ["boot-attestation.json"], "early boot member")
        check(boot.read("boot-attestation.json") == files.raw("boot-attestation.json"), "same early boot")
    boot = files.get("boot-attestation.json")
    check(boot["boot"] == enrolled["boot"] and boot["runner_id"] == job["runner_id"] and
          boot["head"] == HEAD and boot["run"] == run["id"], "physical placement")
    check(custody.capture_receipt(files) == enrolled["capture"], "complete final capture")


def software(files):
    installed = files.get("installed.json")
    g_lock = common.read(common.HERE / "G-qualified-lock.json")
    f_lock = common.read(SCRIPTS / "uv-client-22958/signed-23-split-lock.json")
    check(set(installed) == {"F", "G"}, "SDK roles")
    for key in ("F", "G"):
        actual = files.get(f"intake/material-{key}/registered.json")
        check(actual == installed[key] and actual["files"] == 142, "SDK installation receipt")
        inventory = files.get(f"intake/material-{key}/sdk-inventory.json")
        expected = f_lock["raw"]["F"] if key == "F" else g_lock["G"]["raw"]
        check(inventory == expected, "producer SDK paths and file contents")
        signed_cargo = f_lock["signed_cargo_row"]
        hashes = {k: v["sha256"] for k, v in (inventory | {"bin/cargo": signed_cargo}).items()}
        check(common.canonical(hashes) == actual["effective_inventory"], "installed content digest")
        check(actual["runtime"]["bin/cargo"] == signed_cargo["sha256"], "signed Cargo")
        check(actual["source"]["commit"] == common.P["roles"][key]["rust"], "source role")
        check(actual["source"]["tree"] == common.P["roles"][key]["tree"], "source tree")
    return {role: record["effective_inventory"] for role, record in installed.items()}


def lossless_tables(files, run):
    boot = files.get("boot-attestation.json")
    mode = boot["series"].split(".")[-1]
    counters, pairs = [], []
    for i, order in enumerate(common.P["orders"][mode], 1):
        by_role = {}
        order = order.replace("control", "F")
        for role in order.split("/"):
            path = f"panel/{i}-{role}/"
            perf = files.get(path + "per-rustc/per-rustc.json")
            counts = {}
            for name, row in sorted(perf["targets"].items()):
                raw = score.words(row["raw_hex"])
                counters.append([run, i, role, name, perf["root"], row["pid"], raw["event_id"],
                                 raw["instructions"], raw["time_enabled_ns"], raw["time_running_ns"],
                                 row["raw_hex"], common.canonical(row["argv"])])
                counts[name] = raw["instructions"]
            wall = files.get(path + "bare/clock.json")["ns"]
            whole = files.get(path + "whole/raw.json")["instructions"]
            by_role[role] = [wall, counts["uv"], sum(counts.values()), whole]
        pairs.append([run, i, order, *by_role["F"], *by_role["G"]])
    return counters, pairs


def native_receipts(tmp, run, packet, expected):
    entries = packet["hosts"][run]["native"]
    proofs = {name: common.read(tmp / run / "native" / name) for name in entries}
    check(common.canonical(proofs) == expected[run] and len(proofs) == 18, "native proof closure")
    for name, row in proofs.items():
        check(row["all_metadata"] == 657 and row["all_public"] == 525, "native population " + name)
    return proofs


def original_check(folders, packet, enrollment):
    for run, original, enrolled in zip(RUNS, folders, enrollment["receipts"], strict=True):
        check(custody.check(original, HEAD, enrolled["G_lock"], enrolled["series"]) == enrolled,
              "complete Actions archive and early custody")
        with zipfile.ZipFile(original / "original.zip") as archive:
            for name, h in packet["hosts"][run]["members"].items():
                check(hashlib.sha256(archive.read(name)).hexdigest() == h, "different original member " + name)


def full_native(args, tmp):
    """Replay the original native adjudicator with the three frozen, source-qualified changes."""
    out = tmp / "frozen-worker"
    frozen = common.read(NATIVE / "frozen.json")
    check(frozen["immutable_worker"] == HEAD and
          common.sha(NATIVE / "source-qualification.json") == frozen["v4"] and
          common.sha(NATIVE / "independent-native-holdout.json") == frozen["independent_S_21179"],
          "v4 qualification")
    check(set(frozen["replacement"]) == {"proof.py", "metadata_refs.py", "inherited_clauses.py"},
          "unexpected source replacement")
    for name, digest in frozen["files"].items():
        rel = Path(name)
        source = SCRIPTS.parent / rel
        if rel.parent == Path("scripts/uv-check-21134") and rel.name in frozen["replacement"]:
            source = NATIVE / rel.name
        check(common.sha(source) == digest, "frozen native source " + name)
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    result = tmp / "full-native"
    subprocess.run([sys.executable, "-ISB", str(out / "scripts/uv-check-21134/adjudicate.py"),
                    "--head", HEAD, "--sdk-F", str(args.sdk_f), "--sdk-G", str(args.sdk_g),
                    "--proof-dir", str(result), *map(str, args.originals)], check=True)
    check(common.sha(result / "replication.json") == VERDICT, "full native replay result")


def adverse(directory, proofs, results):
    """Exercise the actual measurement checks with locally mutated copies of genuine input."""
    def refused(test, message):
        try:
            test()
        except ValueError as exc:
            check(message in str(exc), "unexpected refusal: " + str(exc))
        else:
            raise ValueError("mutation accepted: " + message)

    files = score.Files(directory)
    phase = "panel/1-F/"
    tree = common.EV["decode"](files.get(phase + "per-rustc/kernel-events.json"))
    scope = files.get(phase + "request.json")["selectors"]
    image = files.get(phase + "per-rustc/images.json")["rustc"]
    result = files.get(phase + "per-rustc/per-rustc.json")
    terminal = result["targets"]["uv"]
    altered_word = bytearray.fromhex(terminal["raw_hex"])
    altered_word[0] ^= 1
    terminal["raw_hex"] = altered_word.hex()
    refused(lambda: score.validate_scoped(tree, result, scope, image), "unknown or reused counter")
    result = files.get(phase + "per-rustc/per-rustc.json")
    result["targets"]["uv"]["pid"] = result["targets"]["uv_python"]["pid"]
    refused(lambda: score.validate_scoped(tree, result, scope, image), "physical PID/argv")
    fewer = {k: v for k, v in proofs.items() if k != "panel/8-G"}
    refused(lambda: score.replay(directory, fewer), "all 18 original native comparisons")
    refused(lambda: score.jointly(results[0], results[1] | {"boot": results[0]["boot"]}),
            "nonindependent host")
    return 4


def mechanism():
    data = json.loads(gzip.decompress((HERE / "mechanism/owners.json.gz").read_bytes()))
    sources = json.loads(gzip.decompress((HERE / "mechanism/source-origins.json.gz").read_bytes()))
    check(len(sources["owners"]) == 30 and not sources["unresolved_trait_keys"], "surviving owner evidence")
    enrolled = [r for r in data["owners"].values() if r["group"] == "primary37"]
    check(len(enrolled) == 37 and sum(r["G_executed"] for r in enrolled) == 30, "provider evidence")
    expected = {
        "F": (41690, "1174cff8a45bf8b767ee8c1a38cd2666ac86d3dabdcf6180e06cb86db6f6e772"),
        "G": (41514, "8fb938394083e6bbe0b38c67b602f256586db1f39a4f4ab95eec04af6644457d"),
    }
    for role, (pid, digest) in expected.items():
        data_raw = gzip.decompress((HERE / "mechanism" / (role + ".callgrind.gz")).read_bytes())
        check(hashlib.sha256(data_raw).hexdigest() == digest, "full Callgrind bytes")
        def word(label):
            v, = re.findall(rb"^" + label + rb": (.+)$", data_raw, re.M)
            return v
        check(word(b"events") == b"Ir" and int(word(b"pid")) == pid and
              int(word(b"summary")) == int(word(b"totals")) == data["ordinary_terminal_Ir"][role],
              "ordinary whole-PID Ir")
    return data["ordinary_terminal_Ir"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--originals", type=Path, nargs=2, metavar=("INITIAL", "REPEAT"),
                        help="also verify both full original Actions archives, their service receipts and all selected raw bytes")
    parser.add_argument("--sdk-f", type=Path)
    parser.add_argument("--sdk-g", type=Path)
    parser.add_argument("--write-tables", action="store_true",
                        help="create reviewer TSVs from the original raw entries in an empty destination")
    parser.add_argument("--table-dir", type=Path, help="destination for --write-tables")
    args = parser.parse_args()
    check(bool(args.sdk_f) == bool(args.sdk_g) and (not args.sdk_f or args.originals), "full-native arguments")
    check(not args.write_tables or args.table_dir, "supply an empty table directory")
    check(common.sha(HERE / "replication.json") == VERDICT, "original independent adjudication")
    packet = common.read(HERE / "packet.json")
    enrollment = common.read(NATIVE / "enrolled.json")
    completed = common.read(NATIVE / "native-complete.json")
    check(packet["worker"] == enrollment["head"] == HEAD and set(packet["hosts"]) == set(RUNS), "enrollment")
    for name, digest in enrollment["readers"].items():
        native = NATIVE / name
        check(common.sha(native if native.exists() else common.HERE / name) == digest, "actual scorer " + name)
    if args.originals:
        original_check(args.originals, packet, enrollment)
    with tempfile.TemporaryDirectory() as temp:
        tmp = Path(temp)
        unpack(packet, tmp)
        results, counters, pairs, native = [], [], [], []
        inventories = []
        # Open all 36 accepted native classifications before the original numerical reader.
        proofs = {run: native_receipts(tmp, run, packet, completed) for run in RUNS}
        for run, enrolled in zip(RUNS, enrollment["receipts"], strict=True):
            directory = tmp / run / "members"
            files = score.Files(directory)
            service(tmp / run / "service", files, enrolled)
            inventories.append(software(files))
            results.append(score.replay(directory, proofs[run]))
            words, times = lossless_tables(files, run)
            counters.extend(words)
            pairs.extend(times)
            for visit, row in sorted(proofs[run].items()):
                native.append([run, visit, row["all_public"], row["all_metadata"], len(row["nonliteral"]),
                               packet["hosts"][run]["native"][visit]])
        check(inventories[0] == inventories[1], "mixed SDKs")
        combined = {"runs": results, "replicated": score.jointly(*results)}
        check(common.canonical(combined) == common.canonical(common.read(HERE / "replication.json")),
              "reconstruction differs from the complete independent adjudication")
        check(len(counters) == 448 and len(pairs) == 16 and len(native) == 36, "experiment population")
        artifacts = {
            "counters.tsv": csv_text(["run", "pair", "role", "crate", "cargo_pid", "rustc_pid", "event_id",
                "user_instructions", "time_enabled_ns", "time_running_ns", "original_raw_hex",
                "canonical_argv_sha256"], counters),
            "pairs.tsv": csv_text(["run", "pair", "order", "F_bare_ns", "F_uv", "F_rustc_sum", "F_whole_cargo",
                "G_bare_ns", "G_uv", "G_rustc_sum", "G_whole_cargo"], pairs),
            "native.tsv": csv_text(["run", "visit", "public_sidecars", "metadata_paths", "nonliteral_image_pairs",
                "proof_sha256"], native),
        }
        for name, value in artifacts.items():
            if args.write_tables:
                with (args.table_dir / name).open("x") as f:
                    f.write(value)
            else:
                check((HERE / name).read_text() == value, "reviewer table differs: " + name)
        if args.sdk_f:
            full_native(args, tmp)
        mutations = adverse(tmp / RUNS[0] / "members", proofs[RUNS[0]], results)
        print(json.dumps({"runs": RUNS, "kernel_qualified_rustc_counters": len(counters),
            "independent_pairs": len(pairs), "native_validations": len(native), "full_native_rerun": bool(args.sdk_f),
            "adverse_counter_pid_native_host_controls": mutations,
            "source": results[0]["source"], "effective_SDK_inventories": inventories[0],
            "thresholds_on_both_hosts": combined["replicated"], "separate_local_guest_Ir": mechanism(),
            "original_verdict_sha256": VERDICT}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
