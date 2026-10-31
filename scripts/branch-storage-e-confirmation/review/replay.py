"""Read twelve complete originals in place. Classify native correctness on all hosts before reading any clocks."""

from contextlib import ExitStack
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json
import subprocess
import sys
import zipfile

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]
import decision
import media
import physical as p
import confirm_binding as r
from replay_metrics import measured_count, need

BASE_ZIP = "3e8b9f19c21b90b1a281c349f6c812453ad7afe327ce0930dbd6be9d4c46a620"
CHILD_ZIP = "b4372e9d8d51decdd0d68ddb620ddfc8807368d1de76f5f607bc745bb7a2115c"
BASE_MANIFEST = "c29e2e57626491804d9c24e5fa50a709015a002067a3bf39e884d8b6ef0fea43"


def archive_input(z, pos, head, run, schedule, old, seen):
    infos = z.infolist()
    names = {m.filename for m in infos}
    need(
        len(names) == len(infos)
        and all(
            not PurePosixPath(n).is_absolute() and ".." not in PurePosixPath(n).parts for n in names
        )
        and "failure.txt" not in names
        and "complete.json" in names,
        "invalid original media",
    )
    en = p.top(z, "enrollment.json")
    complete = p.top(z, "complete.json")
    boot = en["boot"]
    need(
        en["position"] == pos
        and en["head"] == head
        and en["run"] == run
        and en["attempt"] == 1
        and en["command"] == p.COMMAND
        and en["order"] == schedule[pos] == complete["order"]
        and complete["host_complete"],
        "wrong position, ordinary entry or order",
    )
    need(
        r.BOOT.fullmatch(boot)
        and boot not in seen
        and boot not in old
        and en["plan"] == r.PLAN
        and p.sha(z.read("PLAN.md")) == r.PLAN,
        "wrong or reused boot or study",
    )
    need(
        en["F"]["manifest"] == BASE_MANIFEST
        and en["E"] == json.loads((p.SCREEN / "inputs/e-source.json").read_bytes())["source"],
        "unbound compiler sources",
    )
    for directory, files in [
        (
            p.SCREEN / "inputs",
            (
                "e-source.json",
                "source-replay.json",
                "ruff-28233.json",
                "ruff-28233.patch",
                "cold-units.json",
            ),
        ),
        (
            r.INPUTS,
            (
                "excluded-boots.json",
                "orders.json",
                "previous-boots.json",
                "pilots.json",
                "integration-boots.json",
                "projections.json",
            ),
        ),
    ]:
        for name in files:
            need(z.read(name) == (directory / name).read_bytes(), "changed enrollment file " + name)
    need(
        p.top(z, "meter-ready.json")["boot"]
        == p.top(z, "host.json")["raw_system"]["/proc/sys/kernel/random/boot_id"]
        == boot,
        "reported identity differs from actual kernel",
    )
    return en


def measured(z, en, ordinary, parsers):
    expected = set()
    values = {}
    prev = 0
    windows = []
    for arm in en["order"]:
        values[arm] = {}
        roles = ordinary["roles"]
        guard = ordinary["visits"][arm]
        for study, phases in (("main", p.metrics.PHASES), ("same", p.metrics.SAME)):
            slot = f"measured/{arm}/{study}"
            env = p.active(
                z,
                slot,
                arm,
                roles,
                en["F"]["manifest"] if arm[0] == "F" else en["E"]["qualified"]["manifest"],
            )
            need(env == ordinary["envs"][arm], "different metered environment")
            for ph in phases:
                state = p.STATE[ph]
                prefix = slot + "/" + ph
                record, _ = p.operation(
                    z,
                    prefix,
                    arm,
                    "measured",
                    ph,
                    state,
                    env,
                    parsers,
                    ordinary["refs"][arm, state],
                )
                clock = prefix + "/clock.json"
                expected.add(clock)
                c = p.top(z, clock)
                n = measured_count(c, 101 if ph == "invalid" else 0)
                need(
                    prev < c["start"] < c["stop"] and n == record["record"]["instructions"],
                    "out-of-order or mislabeled native interval",
                )
                prev = c["stop"]
                windows.append([arm, ph, c["start"], c["stop"]])
                paired = guard[ph]
                cleaned = lambda row: {
                    k: v for k, v in row.items() if k not in ("instructions", "allocated")
                }
                need(
                    cleaned(record["record"]) == cleaned(paired) and paired["instructions"] is None,
                    "independent normal and measured result differ",
                )
                values[arm][ph] = {
                    "instructions": n,
                    "enabled": c["enabled"],
                    "running": c["running"],
                    "allocated": record["allocated"],
                    "unmetered_allocated": paired["allocated"],
                }
    need(
        len(windows) == 33
        and {n for n in z.namelist() if n.startswith("measured/") and n.endswith("/clock.json")}
        == expected,
        "wrong number of metered Cargo visits",
    )
    return values, windows


def main(a):
    if a.mode == "collect":
        media.collect(a.run, a.head, a.media, a.catalog)
        return
    _, _, old = r.local()
    schedule = decision.orders(json.loads((r.INPUTS / "orders.json").read_bytes()))
    need(
        subprocess.check_output(["git", "-C", HERE, "rev-parse", "HEAD"], text=True).strip()
        == a.head
        and not subprocess.check_output(["git", "-C", HERE, "status", "--porcelain"]),
        "independent replay needs the clean exact QA source",
    )
    docs = json.loads(a.catalog.read_bytes())
    rows = media.catalog(a.run, a.head, docs, require_success=True)
    kits = {"F": a.f_sdk, "E": a.e_sdk}
    for role, path in kits.items():
        with path.open("rb") as h:
            need(
                hashlib.file_digest(h, "sha256").hexdigest()
                == {"F": BASE_ZIP, "E": CHILD_ZIP}[role],
                "different source archive",
            )
    inputs, parsers = p.corpus.source(a.ruff)
    p.replay_controls.OBSERVER = a.observer
    p.replay_controls.PACKAGING = a.calibration
    with ExitStack() as stack:
        originals = {}
        enrolled = {}
        boots = set()
        guards = {}
        for pos in decision.POSITIONS:
            row = rows[pos]
            file = a.media / row["filename"]
            media.verify(file, row)
            z = stack.enter_context(zipfile.ZipFile(file))
            originals[pos] = z
            en = archive_input(z, pos, a.head, a.run, schedule, old, boots)
            boots.add(en["boot"])
            enrolled[pos] = en
        for pos in decision.POSITIONS:
            guards[pos] = p.unmetered(originals[pos], enrolled[pos], inputs, parsers, kits)
        # Every original source/graph, hardware calibration, native archive and strict provider across twelve is now admitted.
        hosts = {}
        native = {}
        for pos in decision.POSITIONS:
            whole, windows = measured(originals[pos], enrolled[pos], guards[pos], parsers)
            hosts[pos] = {
                "boot": enrolled[pos]["boot"],
                "order": enrolled[pos]["order"],
                "numbers": whole,
            }
            native[pos] = {
                "official": rows[pos],
                "physical_ELFs": guards[pos]["native"],
                "table_inventory": guards[pos]["tables"],
                "native_providers": guards[pos]["providers"],
                "calibration": guards[pos]["calibration"],
                "transient": guards[pos]["transient"],
                "measured_windows": windows,
            }
    report = decision.cohort(hosts, schedule, old)
    report.update(
        run=a.run, head=a.head, attempt=1, evidence=native, plan=r.PLAN, prior_boots=len(old)
    )
    with a.out.open("x") as f:
        json.dump(report, f, indent=2, sort_keys=True)
        f.write("\n")
    print(
        json.dumps(
            {
                "included_boots": 12,
                "all_five_and_all_boots_pass": report["all_five_and_all_boots_pass"],
                "report_sha256": r.sha(a.out),
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    for name in ("collect", "replay"):
        call = sub.add_parser(name)
        call.add_argument("--run", required=True, type=int)
        call.add_argument("--head", required=True)
        call.add_argument("--media", required=True, type=Path)
        call.add_argument("--catalog", required=True, type=Path)
        if name == "replay":
            for opt in ("ruff", "observer", "calibration", "f-sdk", "e-sdk", "out"):
                call.add_argument("--" + opt, required=True, type=Path)
    main(parser.parse_args())
