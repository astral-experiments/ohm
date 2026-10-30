"""Restore the matched binary-only SDKs and run the two original-order Ruff histories."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import subject
import tree_ir
from tree_ir import q, rt
from study import digest, load, need, physical, save, sha


def installable(archive, archive_sha, native_dir):
    import capsule
    need(rt.room()["disk"] > 32 * 2**30 and archive.is_file() and sha(archive) == archive_sha, "insufficient room or wrong frozen SDK")
    raw = {}
    for role in "PC":
        root = rt.ROOT / ("donor-" + role)
        raw[role] = capsule.verify(archive, role, root)
    need(raw["P"] == raw["C"], "asymmetric SDK materialization")
    # Each byte and signed-release metadata was verified on BOTH complete independent passes.
    # Read the exact allowlisted role table a third time without extracting executable files.
    with subprocess.Popen(["zstd", "-qdc", str(archive)], stdout=subprocess.PIPE) as proc:
        with tarfile.open(fileobj=proc.stdout, mode="r|") as members:
            first = next(iter(members))
            need(first.name == "roles.json" and first.size < 2**20, "missing frozen role table")
            roles = json.load(members.extractfile(first))
        while proc.stdout.read(2**20):
            pass
        need(proc.wait() == 0, "truncated physical SDK transport")
    capsule.table(roles)
    need(roles["P"]["source"] == subject.BASE and roles["C"]["source"] == subject.TREATMENT, "wrong Rust sources")
    need(roles["C"]["tree"] == "5b86b3516db45ace6bbbdd536bbff9face291fbd", "wrong candidate tree")
    for role in "PC":
        registered = load(native_dir / (role + "-sdk.json"))
        need({k:v for k,v in roles[role].items() if k != "files"} == {k:v for k,v in registered.items() if k != "files"}, "damaged host/source receipt")
        files = {n:r for n,r in roles[role]["files"].items() if n not in rt.TOOLS}
        need(files == registered["files"] and all(roles[role]["files"][n][0] == k for n,k in rt.TOOLS.items()), "damaged SDK member receipt")
        save(rt.LOG / (role + "-sdk.json"), roles[role])
    need(load(native_dir / "sdk-custody.json")["sha256"] == archive_sha, "archive differs from the original bootstrap result")
    diff = [n for n in roles["P"]["files"] if roles["P"]["files"][n] != roles["C"]["files"][n]]
    def select(role):
        files = roles[role]["files"]
        root = rt.ROOT / ("donor-" + role)
        for name, (key, size, mode) in files.items():
            source, target = root / name, rt.SDK / name
            need((source.stat().st_size, source.stat().st_mode & 0o777, sha(source)) == (size, mode, key), "stored SDK changed")
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists() or sha(target) != key:
                tmp = target.with_name(target.name + ".installing")
                need(not tmp.exists(), "unexpected partially installed member")
                shutil.copyfile(source, tmp)
                tmp.chmod(mode)
                os.replace(tmp, target)
            need((target.stat().st_size, target.stat().st_mode & 0o777, sha(target)) == (size, mode, key), "live SDK file mismatch")
        need({p.relative_to(rt.SDK).as_posix() for p in rt.SDK.rglob("*") if p.is_file()} == set(files), "undocumented SDK file")
        return diff
    return select, roles, raw


def integration():
    archive, expected, native = sys.argv[1:]
    native = Path(native)
    select, roles, restored = installable(Path(archive), expected, native)
    select("P")
    q.rt.select = select
    q.counter = tree_ir.measure
    save(rt.LOG / "subjects.json", {"base": subject.BASE, "treatment": subject.TREATMENT, "capsule": expected, "physical": restored,
         "native_gates": {n: sha(native / n) for n in ["sdk-custody.json", "direct-new/complete.json", "direct-old/complete.json", "x86-host-run-make-pass"]},
         "signed": rt.TOOLS, "driver": {r:{n:v[0] for n,v in rec["files"].items() if n.startswith("lib/librustc_driver")} for r,rec in roles.items()},
         "GNU_link_driver": physical(Path(q.CROSS)), "QEMU": physical(Path(q.QEMU[0])), "loader": physical(Path("/usr/aarch64-linux-gnu/lib/ld-linux-aarch64.so.1"))})
    tree_ir.calibrate()
    q.prepare_graph()
    q.screen()
    observations = load(rt.LOG / "terminal.json")
    need(observations["mechanism_observed"], "failed registered native reduction; retain complete output")
    trials = {n:load(rt.LOG / n / "complete.json") for n in observations["sha256"]}
    reference = trials["mirror1-P"]
    for label,s in trials.items():
        for state in ("old", "cold"):
            need(s[state] == reference[state], f"cross-role reference, including whole independent reader, differs: {label}/{state}")
        need(s["measured"] is not None, f"counter failed on {label}; the corrupted/partial profile receives no observations")
    ratios = {}
    counts = {}
    for name in ("mirror1","mirror2"):
        totals = []
        for role in "PC":
            label = name + "-" + role
            counts[label] = load(rt.LOG / label / "counter/verified.json")
            need(set(counts[label]["processes"]) == {"cargo", *trials[label]["stages"]["unchanged-1"]["rustcs"]}, "changed physical roster")
            totals.append(counts[label]["Ir"])
        ratios[name] = totals[0] / totals[1]
    save(rt.LOG / "independent-terminal.json", {"all_registered_native_admissions": True, "two_independent_mirrors": ratios,
         "all_ratios_above_two": all(r > 2 for r in ratios.values()), "all_host_process_Ir": counts,
         "ordinary_flanks": observations["two_mirrors"], "independent_CLI_reader_and_objects_equal": True,
         "records": observations["sha256"], "native_and_sdk": sha(rt.LOG / "subjects.json"),
         "parent_compiler": subject.BASE, "treatment_compiler": subject.TREATMENT,
         "scope": "Linux x86 host, real Ruff AArch64 GNU target build; genuine signed Cargo entry plus all complete rustc process trees; no wall-time or native AArch64 host measurement"})


if __name__ == "__main__":
    integration()
