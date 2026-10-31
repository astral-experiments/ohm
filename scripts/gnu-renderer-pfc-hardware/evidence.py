"""Reopen original Cargo, kernel, PMU and physical allocation observations for each cell."""

import gzip
import hashlib
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ingress import AMENDMENT, PLAN, RUST, STUDIES, digest, legal, need, required_digest, sha

CLI = [
    "cargo",
    "+ohm",
    "build",
    "-p",
    "ruff_annotate_snippets",
    "--lib",
    "--locked",
    "--offline",
    "-j4",
    "--message-format=json",
]
UNITS = {"annotate_snippets", "memchr", "anstyle", "unicode_width"}
SCORED = ("old", "edit", "repeat")
STATES = ("old", "edit", "repeat", "repair", "repaired-repeat", "empty")
ROSTER = {
    "old": UNITS,
    "edit": {"annotate_snippets"},
    "repeat": set(),
    "empty": UNITS,
    "invalid": {"annotate_snippets"},
    "empty-invalid": UNITS,
    "repaired-repeat": set(),
}


def read(p):
    return json.loads(p.read_bytes())


def metered(raw, term):
    expected = {
        "start",
        "stop",
        "user_us",
        "system_us",
        "instructions",
        "enabled",
        "running",
        "event_errno",
        "code",
    }
    need(set(raw) == expected and all(type(v) == int for v in raw.values()), "unfamiliar perf record")
    need(
        raw["instructions"] > 0
        and raw["enabled"] == raw["running"] > 0
        and raw["event_errno"] == raw["code"] == term["status"] == 0,
        "incomplete or multiplexed observation",
    )
    need(
        term["begin_mono_ns"] <= raw["start"] < raw["stop"] <= term["end_mono_ns"]
        and min(raw["system_us"], raw["user_us"]) >= 0,
        "counter window is outside the real child",
    )
    return raw["instructions"]


def storage(z, state):
    unique = {}
    paths = set()
    labels = set(z["roots"])
    need(labels == {"target", "shared"} and z["roots"] == state["paths"]["roots"], "wrong storage roots")
    for name, dev, ino, nlink, size, blocks in z["rows"]:
        need(
            legal(name) and Path(name).parts[0] in labels and name not in paths,
            "duplicate/foreign retained name",
        )
        need(
            all(type(n) == int and n >= 0 for n in (dev, ino, nlink, size, blocks))
            and ino * nlink > 0
            and blocks % 512 == 0,
            "invalid stat record",
        )
        need(unique.setdefault((dev, ino), blocks) == blocks, "inconsistent hardlink allocation")
        paths.add(name)
    allocated = sum(unique.values())
    need(
        allocated == z["unique_allocated"] and z["unique_inodes"] == len(unique),
        "allocation is not hardlink-deduplicated",
    )
    full_rlibs = {}
    sessions = set()
    links = set()
    for n, dev, ino, *_ in z["rows"]:
        k = (dev, ino)
        if n.endswith(".rlib"):
            full_rlibs[k] = Path(n).name
        if Path(n).name == "work-products.bin":
            sessions.add(k)
        if n.endswith(".rlink"):
            links.add(k)
    return {
        "allocated": allocated,
        "unique_inodes": len(unique),
        "rlib_inodes": len(full_rlibs),
        "session_indices": len(sessions),
        "saved_link_payloads": len(links),
        "cgu_count": len(state["cgu"]),
        "unique_cgu_payloads": len({v["sha256"] for v in state["cgu"].values()}),
    }


def cell(folder, role, history, lane, plain, boot, logical_folder=None):
    logical_folder = folder if logical_folder is None else logical_folder
    complete = read(folder / "complete.json")
    run = read(folder / "runtime.json")
    need(
        (complete["role"], complete["history"], complete["lane"], complete["ordinary"], complete["source"])
        == (
            role,
            history,
            lane,
            CLI,
            (
                RUST[role]
                if role in RUST
                else "c79998a5cd143c445a4b2528f20953b176a65c5d"
                if role == "signed-control"
                else None
            ),
        ),
        "wrong completed cell",
    )
    need(
        (run["role"] if "role" in run else role, run["boot"], run["lane"], run["history"])
        == (role, boot, lane, history),
        "wrong host or history",
    )
    need(
        complete["structural_only"] == (lane == "structural")
        and required_digest(complete["consumer_corrected"]),
        "invalid native terminal",
    )
    counter = {}
    physical = {}
    space = {}
    windows = {}
    for phase in (*STATES, "invalid", "empty-invalid"):
        d = folder / "raw" / phase
        begin = read(d / "started.json")
        end = read(d / "terminal.json")
        bad = phase in ("invalid", "empty-invalid")
        need(
            begin["command"] == CLI
            and end["status"] == (101 if bad else 0)
            and end["begin_mono_ns"] < end["end_mono_ns"],
            "wrong Cargo verdict or invocation",
        )
        msgs = [json.loads(line) for line in (d / "stdout").read_bytes().splitlines()]
        need(msgs[-1] == {"reason": "build-finished", "success": not bad}, "wrong Cargo termination")
        if bad:
            e = [m for m in msgs if m.get("message", {}).get("level") == "error"]
            need(len(e) == 1 and e[0]["message"]["code"]["code"] == "E0308", "wrong invalid source verdict")
        else:
            fresh = {m["target"]["name"]: m["fresh"] for m in msgs if m["reason"] == "compiler-artifact"}
            need(
                len([m for m in msgs if m["reason"] == "compiler-artifact"]) == 4 and set(fresh) == UNITS,
                "wrong four Cargo units",
            )
            if phase in ROSTER:
                need(
                    {k for k, v in fresh.items() if not v} == ROSTER[phase],
                    "typed physical unit roster differs",
                )
        if lane == "structural":
            need(
                begin["launch"][0] == "strace"
                and begin["launch"][-len(CLI) :] == CLI
                and (d / "strace.gz").is_file(),
                "missing structural native tracing",
            )
            native = read(d / "native.json")
            names = [x["name"] for x in native["compilers"]]
            need(
                not native["linkers"]
                and len(names) == len(set(names))
                and (set(names) == ROSTER[phase] if phase in ROSTER else set(names) <= {"annotate_snippets"}),
                "wrong physical compiler/linker roster",
            )
            physical[phase] = names
        elif phase in SCORED:
            need(
                begin["launch"] == [str(plain), str(logical_folder / "raw" / phase / "pmu.json"), *CLI]
                and not (d / "strace.gz").exists(),
                "wrong counter/trace in scored command",
            )
            raw = read(d / "pmu.json")
            counter[phase] = metered(raw, end)
            windows[phase] = [end["begin_mono_ns"], end["end_mono_ns"]]
        else:
            need(begin["launch"] == CLI, "an independent control is incorrectly wrapped")
        need((d / "pmu.json").exists() == (lane == "whole" and phase in SCORED), "extra or missing event")
        if not bad:
            st = read(folder / "states" / phase / "state.json")
            externs = st["dependency_rmeta"]
            need(set(externs) == UNITS - {"annotate_snippets"}, "wrong three compiler metadata inputs")
            target_args = None
            if lane == "structural" and "annotate_snippets" in physical[phase]:
                (compiler,) = [q for q in native["compilers"] if q["name"] == "annotate_snippets"]
                target_args = compiler["argv"]
            for name, item in externs.items():
                need(required_digest(item["sha256"]), "invalid external CAS key")
                blob = (folder / "objects" / item["sha256"]).read_bytes()
                need(
                    len(blob) == item["bytes"]
                    and digest(blob) == item["sha256"]
                    and item["path"] in st["dependency_products"][name],
                    "archived external metadata differs",
                )
                need(
                    bool(item.get("compiler_opens")) == (target_args is not None),
                    "incorrect kernel metadata reader",
                )
                if target_args is not None:
                    need(
                        any(
                            opt == "--extern" and target_args[i + 1] == name + "=" + item["path"]
                            for i, opt in enumerate(target_args)
                        ),
                        "compiler selected different external metadata",
                    )
            z = json.loads(gzip.decompress((folder / "states" / phase / "storage.json.gz").read_bytes()))
            space[phase] = storage(z, st)
            need(
                space[phase]["allocated"] == complete["allocated"][phase],
                "complete and physical allocation disagree",
            )
    if lane == "whole":
        need(
            windows["old"][1] < windows["edit"][0] < windows["edit"][1] <= windows["repeat"][0],
            "invalid cold/edit/first-repeat order",
        )
    p = read(folder / "edit-pair.json")
    need(
        p["intervening_reads"] == False and p["untraced_pair"] == (lane == "whole"),
        "score is not the adjacent edit/repeat",
    )
    return {
        "history": history,
        "role": role,
        "source": complete["source"],
        "semantic_complete": digest((folder / "complete.json").read_bytes()),
        "kernel_compilers": physical,
        "instructions": counter,
        "clock_windows": windows,
        "storage": space,
    }


def tree_inventory(folder, exclude):
    return {
        p.relative_to(folder).as_posix(): [sha(p), p.stat().st_size]
        for p in sorted(folder.rglob("*"))
        if p.is_file() and p.relative_to(folder).as_posix() not in exclude
    }


def header(c, r, tag):
    source = r["source"]
    ids = sorted(role + "-" + h for role in RUST for h in STUDIES)
    need(
        c["schema"] == 1
        and c["phase"] == tag
        and c["plan"] == PLAN
        and c["amendment"] == AMENDMENT
        and c["source"] == [source["run"], source["head"], source["attempt"], source["manifest_sha256"]],
        "wrong source provenance in gate",
    )
    need(
        c["packets"] == {n: r[n]["sha256"] for n in ("adapter", "oracle", "mono", "membership")}
        and sorted(c["cells"]) == ids,
        "different packet or incomplete matrix",
    )
    need(
        set(c["cross"]) == set(STUDIES) and all(required_digest(x) for x in c["cross"].values()),
        "missing across-role semantic gate",
    )
    if tag == "screen":
        need(
            c["whole_oracle"] == r["whole_oracle"]["sha256"],
            "different independent whole-run native verifier",
        )
    if tag == "qualify":
        need(c.get("whole_oracle") is None, "structural native input was mislabelled as counted")
        need(
            set(c["mono"]) == set(RUST)
            and set(c["membership"]) == set(RUST)
            and all(required_digest(x) for x in [*c["mono"].values(), *c["membership"].values()]),
            "missing native qualification",
        )
    for role in RUST:
        for history in STUDIES:
            row = c["cells"][role + "-" + history]
            need(
                (row["history"], row["role"], row["source"]) == (history, role, RUST[role])
                and required_digest(row["external_oracle"]),
                "bad cell in aggregate",
            )
            if tag == "qualify":
                need(
                    row["instructions"] == {}
                    and set(row["kernel_compilers"]) == set((*STATES, "invalid", "empty-invalid")),
                    "traced diagnostic counted or missing compiled visits",
                )
            else:
                need(
                    set(row["instructions"]) == set(SCORED) and row["kernel_compilers"] == {},
                    "untraced primary scope differs",
                )


def qualify_zip(path, r, destination=None):
    """Authenticate all uncompressed observations in the original official qualification ZIP."""
    if destination is not None:
        destination.mkdir(mode=0o700)
    with zipfile.ZipFile(path) as z:
        names = [i.filename for i in z.infolist() if not i.is_dir()]
        need(
            len(names) == len(set(names)) and "certificate.json" in names and "members.json" in names,
            "ambiguous structural evidence",
        )
        raw = z.read("certificate.json")
        need(digest(raw) == r["structural"]["certificate_sha256"], "wrong structural proof")
        c = json.loads(raw)
        header(c, r, "qualify")
        g = r["structural"]
        need(
            [c["run"], c["attempt"], c["head"], c["job"], c["position"]]
            == [g["run"], g["attempt"], g["head"], g["job_ids"][0], "gate"],
            "wrong qualification job",
        )
        original = z.read("members.json")
        need(digest(original) == c["members"], "wrong structural member manifest")
        rows = json.loads(original)
        need(
            set(rows) == set(names) - {"certificate.json", "members.json"},
            "unaccounted or missing structural evidence",
        )
        for name, (wanted, nbytes) in rows.items():
            need(
                legal(name) and z.getinfo(name).file_size == nbytes and required_digest(wanted),
                "invalid structural member",
            )
            with z.open(name) as f:
                if destination is not None and name.startswith("cells/"):
                    target = destination / name.removeprefix("cells/")
                    need(
                        target.is_relative_to(destination) and target != destination, "unsafe witness member"
                    )
                    target.parent.mkdir(parents=True, exist_ok=True)
                    checksum = hashlib.sha256()
                    with target.open("xb") as out:
                        while chunk := f.read(2**20):
                            out.write(chunk)
                            checksum.update(chunk)
                    target.chmod(0o444)
                else:
                    checksum = hashlib.file_digest(f, "sha256")
                need(checksum.hexdigest() == wanted, "bad evidence " + name)
        tree = zipfile.Path(z)
        for k, v in c["cells"].items():
            independent = cell(tree / "cells" / k, v["role"], v["history"], "structural", None, c["boot"])
            need(
                all(v[key] == value for key, value in independent.items()),
                "independent typed/kernel/storage proof differs " + k,
            )
            need(
                rows["cells/" + k + "/complete.json"][0] == v["semantic_complete"]
                and rows["external/" + k + "/verified.json"][0] == v["external_oracle"],
                "cell not physically backed",
            )
        for k, v in c["cross"].items():
            need(rows["external/cross-" + k + "/verified.json"][0] == v, "unbacked cross-role gate")
        for k, v in c["mono"].items():
            need(rows["mono/" + k + "/verified.json"][0] == v, "unbacked mono gate")
        for k, v in c["membership"].items():
            need(rows["membership/" + k + "/verified.json"][0] == v, "unbacked membership gate")
    return {
        "sha256": digest(raw),
        "boot": c["boot"],
        "job": c["job"],
        "files": len(rows),
        "bytes": sum(b for _, b in rows.values()),
    }
