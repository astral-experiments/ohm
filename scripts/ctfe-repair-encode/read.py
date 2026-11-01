"""Reopen the two official diagnostic workers and the original raw native fixtures without running archived code."""

import argparse
import json
import re
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "ctfe-crossover-pilot")]
import archive
import evidence as ev
import reopen as old

REG = json.loads((HERE / "owners.json").read_bytes())
GRAPH = "f5909e1cbd4832369f783bdbd733e54562bcce15e44592b8ec15793e9996c660"
ORDERS = {"01": ["P", "B"], "02": ["B", "P"]}
PREVIOUS = {x["boot"] for x in REG["originals"]} | {
    "4f4d4a31-68c1-447b-9909-8f4c951d6d82",
    "c9fb2eab-3d98-4154-b864-cfac6df82005",
}
get = old.dataset


def calls(z, pre, certificate, sdk, paths, mode, lib, identity):
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        base = pre + "/calls/"
        members = [x for x in z.infolist() if x.filename.startswith(base) and not x.is_dir()]
        ev.need(
            40 < len(members) < 150 and sum(x.file_size for x in members) < 24 << 20,
            "unexpected call capture size",
        )
        for x in members:
            name = x.filename.removeprefix(base)
            ev.need(
                name == "config"
                or re.fullmatch(r"(?:rustc|cargo|wild)-[1-9]\d*\.(?:cmdline|maps|events|image)", name),
                "foreign call capture file",
            )
            ev.need(x.file_size < 2 << 20, "excessive per-process data")
            (out / name).write_bytes(z.read(x))
        ev.need((out / "config").read_text() == ev.config(mode, paths), "changed intervention list")
        images, events = ev.physical(out, sdk, paths, inventory=certificate["files"])
        ev.mapped_observer(out, images, lib, identity)
        wanted = {"config"}
        for pid, im in images.items():
            for ext in (
                ("cmdline", "maps", "events", "image") if im["role"] == "rustc" else ("cmdline", "image")
            ):
                wanted.add(im["role"] + "-" + pid + "." + ext)
        ev.need(wanted == {p.name for p in out.iterdir()}, "incomplete/orphaned native process")
        return images, events


def products(actual, wanted):
    ev.need(
        actual["graph"] == wanted["graph"]
        and old.behavior(actual["native"]) == old.behavior(wanted["native"])
        and all(actual[k] == wanted[k] for k in ("cli", "reader")),
        "native products differ from independent empty",
    )


def read(path, pos, run, head):
    result = {}
    counts = {}
    clocks = set()
    visits = {}
    last = 0
    commands = {}
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        ev.need(
            len(names) == len(set(names))
            and all(not PurePosixPath(n).is_absolute() and ".." not in PurePosixPath(n).parts for n in names),
            "ambiguous ZIP",
        )
        ev.need(
            "failure.txt" not in names and not any(n.endswith(("kernel.tsv.gz", "exec.raw.gz")) for n in names),
            "failed or traced diagnostic",
        )
        rec = get(z, "position.json")
        meter = get(z, "meter-ready.json")
        boot = meter["boot"]
        cal = old.replay_controls.calibration(z, boot)
        hardware = old.hardware.verify(z, cal, meter)
        ev.need(
            rec
            == dict(
                position=pos,
                order=ORDERS[pos],
                boot=boot,
                run=str(run),
                head=head,
                plan=ev.sha(HERE / "PLAN.md"),
                registration=ev.sha(HERE / "owners.json"),
                command=old.CARGO,
            )
            and re.fullmatch(r"[a-f0-9]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", boot)
            and boot not in PREVIOUS
            and meter["affinity"] == cal["affinity"]
            and meter["observer"] == old.replay_controls.OBS
            and meter["calibrator"] == old.replay_controls.CAL,
            "incorrect source, PMU, schedule, or reused boot",
        )
        sdks = old.sdk_pair(z)
        files = sdks["C"]["files"]
        bodies = {}
        refs = {}
        tool = get(z, "tools/tool.json")
        emitter = Path(tool["argv"][8])
        binary = z.read("tools/pack-gate.so")
        ev.need(
            emitter.is_absolute()
            and emitter.parts[-4:] == ("enrolled", "scripts", "ctfe-repair-encode", "pack_gate.c")
            and tool["argv"]
            == [
                "/usr/bin/cc",
                "-std=gnu11",
                "-O2",
                "-fPIC",
                "-shared",
                "-Wall",
                "-Wextra",
                "-Werror",
                str(emitter),
                "-ldl",
                "-o",
                str(Path(meter["plain"]).parents[1] / "tools/pack-gate.so"),
            ]
            and re.fullmatch(r"[0-9a-f]{64}", tool["compiler"])
            and tool["source"] == ev.sha(HERE / "pack_gate.c")
            and re.fullmatch(r"[0-9a-f]{64}", tool["b3sum"])
            and tool["file"]["sha256"] == tool["elf"]
            and tool["file"]["bytes"] == len(binary)
            and tool["elf"] == old.digest(binary)
            and binary[:6] == b"\x7fELF\x02\x01"
            and binary[16:20] == b"\x03\x00\x3e\x00",
            "unbound QA interceptor",
        )
        cert, root = old.active(z, "clean-reference-Con", "Con", files)
        ev.need(meter["plain"] == str(root / "logs/observers/plain"), "wrong meter")
        for phase in old.REFS:
            pre = "clean-reference-Con/" + phase
            refs[phase] = old.read_phase(z, pre, phase, "clean", "reference", "Con", cert, root, bodies)
            ev.need(refs[phase]["graph"] == GRAPH, "foreign empty graph")
        ev.need(refs["clean-A"]["cli"] != refs["clean-B"]["cli"], "inactive genuine historical edit")
        for mode in ORDERS[pos]:
            top = "return-" + mode
            active, sameroot = old.active(z, top, "Con", files)
            ev.need(cert == active and root == sameroot, "changed physical SDK or normal environment")
            visits[mode] = {}
            for phase in old.PHASES:
                pre = top + "/" + phase
                repair = phase == "repair"
                sdk = Path(active["sdk"])
                actual = active
                if repair:
                    actual = {**active, "env": active["env"] | ev.hooks(root, sdk)}
                obs = old.read_phase(
                    z, pre, phase, "measured" if repair else "ordinary", "return", "Con", actual, root, bodies
                )
                visits[mode][phase] = {k: obs[k] for k in ("status", "graph", "dirty", "cli", "reader")}
                if phase == "unchanged":
                    ev.need(obs["source"] == get(z, top + "/comment/source.json"), "source changed on repeat")
                if phase != "invalid":
                    products(obs, refs[obs["reference"]])
                if not repair:
                    continue
                v = get(z, pre + "/clock.json")
                ev.need(
                    v["running"] == v["enabled"] and last < v["start"], "partial or overlapping repair count"
                )
                last = v["stop"]
                clocks.add(pre + "/clock.json")
                counts[mode] = obs["instructions"]
                before, after, pl = [
                    get(z, pre + "/" + n + ".json.gz") for n in ("before", "after", "placements")
                ]
                owners = REG["selected"] + REG["other"]
                paths = [before["owners"][o] for o in REG["selected"]]
                ev.need(
                    len(owners) == 16
                    and set(before["owners"]) == set(owners)
                    and before["owners"] == after["owners"],
                    "unexpected selected owner set",
                )
                images, events = calls(
                    z, pre, active, sdk, paths, mode, root / "logs/tools/pack-gate.so", tool["file"]
                )
                commands[mode] = ev.compiler_commands(images)
                linker = ev.roster(images, events, REG, old.CARGO, before["owners"])
                physical = ev.routes(
                    before, after, images, events, REG["selected"], mode == "B", all_owners=owners
                )
                ev.need(
                    physical == {o: {k: pl[o][k] for k in ("final", "donor", "packed_pair")} for o in pl},
                    "wrong donor or publication",
                )
                link = get(z, pre + "/link.json")
                ev.need(link["wild_output"] == linker, "foreign output argv")
                archive.publication(
                    get(z, top + "/invalid/path-inodes.json.gz"),
                    get(z, pre + "/path-inodes.json.gz"),
                    before,
                    after,
                    pl,
                    link,
                    obs["cli"],
                    root / "work",
                )
                ev.need(
                    sorted([r["name"], r["kind"][0]] for r in get(z, pre + "/roster.json.gz")["dirty"])
                    == REG["physical_units"],
                    "dirty graph mismatch",
                )
                result[mode] = pl
        ev.need(commands["P"] == commands["B"], "physical Rust compiler argv changed")
        ev.need(
            visits["P"] == visits["B"]
            and {
                n for n in names if n.startswith(("return-", "clean-reference-")) and n.endswith("/clock.json")
            }
            == clocks,
            "unmatched histories/clocks",
        )
        comparison = ev.comparison(result["P"], result["B"], REG)
        delta = counts["P"] - counts["B"]
        ev.need(
            get(z, "diagnostic.json")
            == dict(instructions=counts, pass_minus_blocked=delta, placement=comparison, issues=[]),
            "invalid or misreported outcome",
        )
        return dict(
            position=pos,
            boot=boot,
            counts=counts,
            pass_minus_blocked=delta,
            placement=comparison,
            visits=visits,
            hardware=hardware,
        )


def official(directory, run, head, paths):
    runrow, jobs, assets = [
        json.loads((directory / (k + ".json")).read_bytes()) for k in ("run", "jobs", "artifacts")
    ]
    ev.need(
        (
            runrow["id"],
            runrow["head_sha"],
            runrow["head_branch"],
            runrow["run_attempt"],
            runrow["path"],
            runrow["event"],
            runrow["conclusion"],
        )
        == (
            run,
            head,
            "charlie/qa-ctfe-repair-encode-20261101",
            1,
            ".github/workflows/ci.yml",
            "workflow_dispatch",
            "success",
        )
        and runrow["repository"]["full_name"]
        == runrow["head_repository"]["full_name"]
        == "astral-experiments/ohm",
        "wrong official run",
    )
    ev.need(
        jobs["total_count"] == len(jobs["jobs"]) == assets["total_count"] == len(assets["artifacts"]) == 2,
        "unexpected media or missing worker",
    )
    result = []
    for pos, path in zip(("01", "02"), paths, strict=True):
        (job,) = [j for j in jobs["jobs"] if j["name"] == "Separate Ruff repair table encoding " + pos]
        (asset,) = [a for a in assets["artifacts"] if a["name"] == "ctfe-repair-encode-" + pos]
        ev.need(
            (job["run_id"], job["run_attempt"], job["head_sha"], job["conclusion"], job["labels"])
            == (run, 1, head, "success", ["namespace-profile-ubuntu-24-04-16"])
            and all(
                any(s["name"] == n and s["conclusion"] == "success" for s in job["steps"])
                for n in ("Authenticate the source-built candidate SDK", "Run paired candidate repairs")
            )
            and (
                asset["workflow_run"]["id"],
                asset["workflow_run"]["head_sha"],
                asset["expired"],
                asset["digest"],
                asset["size_in_bytes"],
            )
            == (run, head, False, "sha256:" + ev.sha(path), path.stat().st_size),
            "incorrect official result, job or ZIP",
        )
        result.append(read(path, pos, run, head))
    ev.need(result[0]["boot"] != result[1]["boot"], "repeated boot")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--official", required=True, type=Path)
    parser.add_argument("--run", required=True, type=int)
    parser.add_argument("--head", required=True)
    parser.add_argument("archives", nargs=2, type=Path)
    args = parser.parse_args()
    print(json.dumps(official(args.official, args.run, args.head, args.archives), sort_keys=True, indent=2))
