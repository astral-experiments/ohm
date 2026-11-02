"""Fresh-reader verification of a transferred original worker archive, with no compiler or SDK."""

import ast
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
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from probes import CHILD, read_stdin, require

EXEC = re.compile(r'^execve\(("(?:\\.|[^"\\])*"), (\[.*?\]), (.*)\)\s+= 0$')
REASONS = re.compile(rb"^OHM_LDV_REASONS((?: [0-9]+){8})$", re.M)
STORE = re.compile(r"^ldv/(native-bodies|probe-owners)/([0-9a-f]{64})\.gz$")


def digest(data):
    return hashlib.sha256(data).hexdigest()


class Member:
    def __init__(self, archive, name):
        self.archive, self.name = archive, name

    def open(self):
        return io.TextIOWrapper(self.archive.open(self.name), encoding="utf-8")


def physical_probe(z, folder, r, eq, owner_bodies):
    args = list(r["argv"])
    pos = args.index("--crate-name") + 1
    require(args[pos] == r["name"] and re.fullmatch(r"autocfg_[0-9a-f]{16}_" + eq["suffix"], r["name"]),
            "different probe crate")
    args[pos] = "autocfg_<independently-random>_" + eq["suffix"]
    require(args == eq["argv"] and eq["owner_sha256"] in owner_bodies, "different probe input or owner")
    pending, done, bodies = [r["pid"]], set(), []
    while pending:
        tid = pending.pop()
        require(tid not in done, "thread cycle")
        done.add(tid)
        file = Member(z, folder + f"/trace/exec.{tid}")
        with file.open() as stream:
            for line in stream:
                match = CHILD.match(line.rstrip("\n"))
                if match:
                    pending.append(int(match[1]))
        data, eof = read_stdin(file)
        if data or eof:
            require(eof, "unterminated probe input")
            bodies.append(data)
    require(len(bodies) == 1 and bodies[0].decode() == eq["stdin_utf8"] and digest(bodies[0]) == eq["stdin_sha256"],
            "different physical autocfg bytes")


def scan(z, run_id, head, suite, pair, stage):
    infos = z.infolist()
    require(len(set(i.filename for i in infos)) == len(infos) and
            sum(i.file_size for i in infos) <= 48 << 30 and all(i.file_size <= 6 << 30 for i in infos),
            "unsupported raw archive")
    require(z.testzip() is None, "invalid original ZIP member CRC")
    terminal = json.loads(z.read("ldv/verified.json"))
    physical = json.loads(z.read("ldv/physical-contact.json"))
    require((terminal["qa"], terminal["run"], terminal["suite"], terminal["assignment"]["pair"], terminal["stage"])
            == (head, run_id, suite, pair, stage) and physical["signed_members"] == 79 and
            terminal["physical"] == digest(z.read("ldv/physical-contact.json")) and
            terminal["acquired"] == digest(z.read("ldv/acquired.json")), "different original")
    frontend, = [p for p in physical["stable_file_identities"] if p.endswith("/bin/rustc")]
    bodies = {"native-bodies": set(), "probe-owners": set()}
    for f in infos:
        m = STORE.fullmatch(f.filename)
        if m:
            sha = hashlib.sha256()
            with z.open(f) as gz, gzip.GzipFile(fileobj=gz) as body:
                magic = body.read(4)
                require(magic == b"\x7fELF", "invalid native custody")
                sha.update(magic)
                while chunk := body.read(1 << 20):
                    sha.update(chunk)
            require(sha.hexdigest() == m[2], "wrong independently reopened native bytes")
            bodies[m[1]].add(m[2])
    observed = json.loads(z.read("ldv/acquired.json"))
    require(set(observed) == {"plain-A", "plain-B", "original", "guard"}, "missing arm")
    compilers = linkers = controls = probes = hits = 0
    counter_proofs = {}
    for arm, phases in observed.items():
        for phase, obs in phases.items():
            case = "edit" if phase in ("old", "new", "unchanged", "invalid", "repair") else "clean"
            folder = f"ldv/{arm}-{case}/{phase}"
            kernel = z.read(folder + "/kernel.json")
            require(digest(kernel) == obs["kernel_sha256"] and json.loads(z.read(folder + "/result.json")) == obs,
                    "different phase")
            k = json.loads(kernel)
            require(k["rustc"] == obs["raw_roster"]["rustc"] and k["linkers"] == obs["raw_roster"]["linkers"],
                    "different physical roster")
            if "elf" in obs:
                require(obs["elf"] in bodies["native-bodies"], "missing final complete ELF")
            else:
                require(phase == "invalid" and obs["error"] == "E0308" and b"E0308" in z.read(folder + "/outer.stdout"),
                        "missing genuine invalid compile")
            captured = z.read(folder + "/linker-argv.json")
            links = json.loads(captured)
            require(digest(captured) == obs["linker_argv_sha256"] and
                    sorted((r["pid"], r["path"]) for r in k["tree"]["linkers"]) ==
                    sorted((r["pid"], r["path"]) for r in links) and
                    all(r["sha256"] == physical["wild"] for r in links if r["signed_wild"]), "different native links")
            verify = [(r["pid"], r["exec"], r["argv"]) for r in k["compilers"]]
            verify += [(r["pid"], r["path"], r["argv"]) for r in links]
            for pid, exe, argv in verify:
                found = []
                with Member(z, folder + f"/trace/exec.{pid}").open() as stream:
                    for line in stream:
                        if line.startswith("execve(") and line.rstrip().endswith("= 0"):
                            m = EXEC.fullmatch(line.rstrip())
                            require(m, "unparsed successful native exec")
                            if ast.literal_eval(m[1]) == exe:
                                found.append(ast.literal_eval(m[2]))
                require(found == [argv], ("different actual compiler/linker argv", arm, phase, pid, exe))
            actual_links = sum(r["signed_wild"] for r in links)
            require(actual_links == sum(n for name, _, n in k["linkers"] if name == "signed-Wild"), "missing genuine Wild")
            if suite == "e2e" and phase == "unchanged":
                require(k["linkers"] == [["signed-Wild", "e2e", 1]] and
                        [r for r in k["rustc"] if r[0] != "probe"] == [["link-only", "e2e", 1]], "not ordinary e2e")
            rows = {r["pid"]: r for r in k["compilers"]}
            if stage == "score" and arm in ("original", "guard") and phase in ("new", "unchanged"):
                body = z.read(folder + "/pmu.json")
                pm = json.loads(body)
                require(os.waitstatus_to_exitcode(pm["status"]) == 0 and pm["enabled"] == pm["running"] > 0 and
                        pm["instructions"] == obs["count"] == terminal["whole_tree_user_instructions"][arm][phase] > 0,
                        "different raw hardware result")
                task = json.loads(z.read(folder + "/command.json"))
                ordinary = task["ordinary"]
                proxy = task["actual"][task["actual"].index("--") + 3]
                parents = {int(child): int(parent) for child, parent in k["tree"]["parents"].items()}
                def counted(pid):
                    seen = set()
                    while pid != pm["pid"] and pid in parents:
                        require(pid not in seen, "cycle in counted process tree")
                        seen.add(pid)
                        pid = parents[pid]
                    return pid == pm["pid"]
                require(all(counted(pid) for pid, _, _ in verify), "a genuine compiler/linker escaped the hardware event")
                signed = frontend[:-len("/bin/rustc")] + "/bin/cargo"
                signed_pids = {s["pid"] for s in k["tree"]["processes"] if s["path"] == signed and counted(s["pid"])}
                def executed(pid, exe, argv):
                    with Member(z, folder + f"/trace/exec.{pid}").open() as stream:
                        for line in stream:
                            m = EXEC.fullmatch(line.rstrip())
                            if m and ast.literal_eval(m[1]) == exe and ast.literal_eval(m[2]) == argv:
                                return True
                    return False
                require(executed(pm["pid"], proxy, ordinary) and
                        any(executed(pid, signed, [signed, *ordinary[2:]]) for pid in signed_pids),
                        "the event did not start at ordinary Cargo dispatch")
                counter_proofs[arm + "/" + phase] = {"sha256": digest(body), "signed_cargo": signed, **pm}
            if arm in ("original", "guard"):
                ids = physical["stable_file_identities"][frontend][:2]
                for r in rows.values():
                    if r["selected"]:
                        record = z.read(folder + "/native/" + str(r["pid"]) + ".loaded").decode().split()
                        require(record[0] == arm and [int(x) for x in record[1:3]] == ids,
                                "wrong physical signed rustc")
            if arm == "guard" and phase == "new":
                for r in rows.values():
                    if [r["name"], r["argv"]] in obs["root_argv"]:
                        messages = z.read(folder + "/native/" + str(r["pid"]) + ".stderr")
                        count = sum(int(row.split()[0]) for row in REASONS.findall(messages))
                        require(count == r["reason_totals"][0], "wrong physical skip count")
                        hits += count
            raw_probes = json.loads(z.read(folder + "/probes.json"))
            require(raw_probes == obs["physical_autocfg"], "wrong projected probe")
            for probe in raw_probes:
                r = rows[probe["pid"]]
                require(r["name"] == probe["actual_crate"], "wrong compiler PID")
                physical_probe(z, folder, r, probe["equivalence"], bodies["probe-owners"])
            compilers += len(rows)
            linkers += actual_links
            probes += len(raw_probes)
            controls += 1
    require(hits == terminal["guarded_owner_skips"] > 0 and len(bodies["native-bodies"]) >= 2 and probes >= 12,
            "missing real native/guard coverage")
    require(len(counter_proofs) == (4 if stage == "score" else 0), "wrong number of raw counter observations")
    for arm in ("plain-B", "original", "guard"):
        for phase in ("old", "new", "unchanged"):
            for key in ("root_argv", "roster", "inventory", "verdict", "elf", "dirty"):
                require(observed[arm][phase][key] == observed["plain-A"][phase][key], ("ordinary mismatch", arm, phase, key))
    return {"qa": head, "suite": suite, "pair": pair, "stage": stage, "run": run_id, "members": len(infos),
            "uncompressed_bytes": sum(i.file_size for i in infos), "native_bodies": sorted(bodies["native-bodies"]),
            "probe_owners": sorted(bodies["probe-owners"]), "phases": controls, "kernel_compilers": compilers,
            "kernel_Wild": linkers, "probe_sources": probes, "new_guard_skips": hits,
            "terminal_sha256": digest(z.read("ldv/verified.json")), "acquired": terminal["acquired"],
            "hardware_events": counter_proofs}


def main(stage, suite, pair, output):
    repo = "astral-experiments/ohm"
    origin = f"repos/{repo}/actions"
    run_id, head = int(os.environ["GITHUB_RUN_ID"]), os.environ["GITHUB_SHA"]
    name = f"ldv-needed-{stage}-originals-{suite}-{pair}"
    run = json.loads(subprocess.check_output(["gh", "api", f"{origin}/runs/{run_id}"]))
    require(run["run_attempt"] == 1 and run["head_sha"] == head and run["event"] == "workflow_dispatch"
            and run["head_branch"] == "charlie/qa-ruff-workspace-link-census-20261102", "different worker run")
    arts = json.loads(subprocess.check_output(["gh", "api", f"{origin}/runs/{run_id}/artifacts?per_page=100"]))
    a, = [a for a in arts["artifacts"] if a["name"] == name]
    require(not a["expired"] and 0 < a["size_in_bytes"] <= 4 << 30 and
            shutil.disk_usage(output.parent).free >= a["size_in_bytes"] + (8 << 30), "raw download reserve")
    with tempfile.TemporaryDirectory(dir=output.parent) as local:
        arc = Path(local) / "raw.zip"
        with arc.open("xb") as target:
            subprocess.run(["gh", "api", f"{origin}/artifacts/{a['id']}/zip"], stdout=target, check=True)
        with arc.open("rb") as stream:
            require(arc.stat().st_size == a["size_in_bytes"] and
                    "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest() == a["digest"], "bad original download")
        with zipfile.ZipFile(arc) as z:
            result = scan(z, run_id, head, suite, pair, stage)
    result.update({"artifact_id": a["id"], "archive_digest": a["digest"], "archive_bytes": a["size_in_bytes"]})
    with output.open("x") as dst:
        json.dump(result, dst, sort_keys=True)
        dst.write("\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]), Path(sys.argv[4]))
