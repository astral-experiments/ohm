"""One physical Cargo on the complete Linux release. Products come from prequalified ELFs."""

import argparse
import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "mixed-generics-ruff")]
from kits import CARGO, ENROLL, HOST, WILD, WILD_HASH, need, sha, write
import state as s
import panel
import observe
import counter
import cost

CARGOS = {
    "strict": ("761ea115605c34f11a1cd29afd68812c1e1359dd", CARGO),
    "293": ("735e1528ed741015c57676dccf05dbdc0ff7bed1", "869a24e83ff84cca6e9d6cb35eb62f149aa48555cf8bb7ee9b94d44ad90d2914"),
}
SDK = {
    "cargo": "4695ab8e260ba4d6363e42b785c8f410dd79d9255f0313dab6c19e978878f43e",
    "rustc": "f7663fb7dec7e5c7ea613a85ff1d6e4c00bf97b8c50534f17e5c95cd599712b9",
    "driver": "dae4f8dc64b2b2ac9dc04dfe2cfad633d6af1a87da2dfc532e757ffe758680e3",
    "wild": WILD_HASH,
}
PANEL = "e2e-parent"  # unchanged semantics, derives actual Cargo identity from installed/current


def acquire(root, workspace, cargo, signed, role):
    assets = root / "receipts/sdk"
    assets.mkdir()
    shutil.copytree(signed / "receipts/21", assets / "release")
    shutil.copy2(cargo / "custody.json", assets / "cargo-custody.json")
    original = signed / "sdk-21"
    sdk = root / "installed/current"
    original.rename(sdk)
    driver, = list((sdk / "lib").glob("librustc_driver*.so"))
    sources = [sdk / "bin/cargo", sdk / "bin/rustc", driver, sdk / WILD]
    need([sha(f) for f in sources] == list(SDK.values()), "release changed")
    need((sdk / "bin/rustdoc").is_file() and len(list((sdk / "lib/rustlib" / HOST / "lib").glob("libstd-*.rlib"))) == 1,
         "missing signed host rustdoc or std")
    before = s.roster(sdk)
    old = root / "original-signed-cargo"
    sources[0].rename(old)
    shutil.copy2(cargo / "cargo", sources[0])
    after = s.roster(sdk)
    need(set(before) == set(after) and {n for n in before if before[n] != after[n]} == {"bin/cargo"}
         and after["bin/cargo"]["sha256"] == CARGOS[role][1], "more than the receiver changed")
    for label, data in (("complete-release", before), ("actual-installed", after)):
        s.payload(assets / (label + ".json.gz"), json.dumps(data, sort_keys=True).encode())
    e = s.identity_env(root, "signed-installed")
    versions = {name: s.output([name, "+ohm", flag], env=e).decode()
                for name, flag in (("cargo", "-Vv"), ("rustc", "-vV"), ("rustdoc", "-vV"))}
    need(CARGOS[role][0] in versions["cargo"] and all("c79998a5cd143c445a4b2528f20953b176a65c5d" in versions[n]
         for n in ("rustc", "rustdoc")) and Path(s.output(["rustc", "+ohm", "--print", "sysroot"], env=e).decode().strip()).samefile(sdk),
         "rustup proxy does not select the actual full release")
    need(sha(workspace / "physical/scripts/ron-check-share/observe.c")
         == "b36f563ba76ae952c9e09eb532491e4b525502d4953dd1964fb236744abb0d18", "changed exec observer")
    obs = root / "observers"
    obs.mkdir()
    subprocess.run(["cc", "-O2", "-Wall", "-Werror", workspace / "physical/scripts/ron-check-share/observe.c",
                    "-o", obs / "observe"], check=True)
    shutil.copy("/usr/bin/false", obs / "never-selected")
    write(assets / "versions.json", versions)
    return sdk


def census(root, label):
    d = root / "receipts" / label
    graph = json.loads((d / "physical.json").read_text())
    exe, = [item["output"] for item in graph["wild"] if item["same_returned_e2e"]]
    (pid, gen), = graph["generators"]
    ev = json.loads(gzip.decompress((d / "execs.json.gz").read_bytes()))
    script, = [row for row in ev if "--crate-name" in row[3]
               and row[3][row[3].index("--crate-name")+1] == "build_script_build"
               and "crates/ruff_unicode_names2/build.rs" in row[3]]
    out = Path(script[3][script[3].index("--out-dir")+1])
    need(any(Path(item["output"]).parent == out and Path(item["output"]).samefile(gen) for item in graph["wild"]),
         "cold generator lacked its authenticated source compiler and a real Wild link")
    compiler = Path(shutil.which("cc")).resolve()
    need(any(Path(row[2]).samefile(compiler) and "-o" in row[3] and row[3][row[3].index("-o")+1] == exe for row in ev
             if Path(row[2]).is_file()), "unrecognized actual system linker driver")
    sdk = root / "installed/current"
    return {"paths": [str(Path(p).resolve()) for p in [sdk / "bin/rustc", sdk / WILD, gen, exe, compiler]],
            "fixed_identities": {k: [p.stat().st_dev, p.stat().st_ino] for k, p in
                                 (("rustc", sdk / "bin/rustc"), ("wild", sdk / WILD),
                                  ("cargo", sdk / "bin/cargo"), ("gcc", compiler))},
            "cold_generator": {"pid": pid, "path": gen, "sha256": sha(Path(gen)), "bytes": Path(gen).stat().st_size}}


def snapshot(root, name, enrolled):
    dest = root / "receipts" / name / "proof-inputs"
    dest.mkdir()
    exe = Path(enrolled["paths"][3])
    markers = {}
    for container in (root / "slot/target", root / "slot/shared"):
        for p in container.rglob(".ohm-worktree-seed*"):
            if p.is_file():
                need(p.stat().st_size <= 65536, "unbounded workspace marker")
                markers[str(p.relative_to(root / "slot"))] = [p.stat().st_size, sha(p), p.read_bytes().hex()]
    write(dest / "workspace-markers.json", markers)
    recipe = Path(str(exe) + ".rlink")
    native = Path(str(exe) + ".rlink-objects")
    fp = exe.parent.parent / "fingerprint"
    members = {str(p.relative_to(native)): [p.stat().st_size, sha(p)] for p in native.rglob("*") if p.is_file()}
    write(dest / "rlink-objects.json", members)
    files = [recipe, Path(str(exe) + ".d"), Path(str(exe) + ".rlink-cache.json"),
             *(p for p in fp.glob("*test-integration-test-e2e*") if p.is_file())]
    rows = {}
    for f in files:
        if f.is_file():
            need(f.stat().st_size < 8 * 2**20, "unbounded fingerprint payload")
            s.payload(dest / (f.name + ".gz"), f.read_bytes())
            rows[str(f)] = [f.stat().st_size, sha(f)]
    write(dest / "fingerprints.json", rows)


def native_reference(root, label, raw, names, reference):
    path = cost.oracle(raw, names, root)
    # Actual test execution, images and inventories are outside any PMU process.
    result = observe.native_reader(root, label, path, "original")
    write(root / "receipts" / label / "test.json", result)
    if result["elf"]["sha256"] != reference["elf"]["sha256"]:
        dest = root / "receipts/elf-divergences"
        dest.mkdir(exist_ok=True)
        for data in [reference["elf"], result["elf"]]:
            name = data["sha256"]
            if not (dest / (name + ".zst")).exists():
                subprocess.run(["zstd", "-q", "-T3", "-3", "-o", dest / (name + ".zst"), root / "image-vault" / name], check=True)
    for key in ("names", "list_sha", "runtime", "new_cases", "stable_cases"):
        need(result[key] == reference[key], f"{label} changed {key}")
    need(result["elf"]["sha256"] == reference["elf"]["sha256"] and result["valid_inventory"], label + " changed ELF")


def main(args):
    root, workspace, role = args.root, args.workspace, args.role
    s.unit_dir(root)
    s.source(root)
    need(s.output(["git", "-C", HERE, "rev-parse", "HEAD"]).decode().strip() == os.environ["GITHUB_SHA"], "wrong registration")
    write(root / "receipts/enrollment.json", {"role": role, "head": os.environ["GITHUB_SHA"],
          "attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]), "run": int(os.environ["GITHUB_RUN_ID"]),
          "argv": panel.E2E, "source": ENROLL["source"], "patch": ENROLL["e2e"]["patch_sha256"]})
    write(root / "receipts/ordinary-environment.json", s.env(root))
    acquire(root, workspace, args.cargo, args.signed, role)
    (root / "receipts/sdk/issuer").mkdir()
    stamp = observe.issuer(root, "sdk/issuer")
    s.seed_registry(root)
    records = {}
    issues = []

    def visit(stream, name, mode):
        key = f"{stream}/{name}"
        row = panel.visit(root, PANEL, stream, name, mode, stamp)
        records[key] = row
        issues.extend(key + ": " + message for message in row["issues"])
        return row

    s.fresh(root, registry=True)
    visit("trace", "cold", "original")
    # The bare e2e native output anchors receipts even if later allocation scopes differ.
    native, = [v["output"] for v in records["trace/cold"]["physical"]["wild"] if v["same_returned_e2e"]]
    source = {"paths": [None, None, None, native]}
    for phase, state in (("prior-repeat-1", "original"), ("prior-repeat-2", "original"), ("edited", "reversed"),
                         ("edit-repeat", "reversed"), ("restored", "original"), ("restore-repeat", "original")):
        visit("trace", phase, state)
        if phase in ("prior-repeat-1", "prior-repeat-2"):
            snapshot(root, "trace/" + phase, source)
    for state in ("reversed", "original"):
        s.fresh(root, registry=True)
        visit("clean", state, state)
    panel.compare_e2e(root, records, issues)
    write(root / "receipts/semantics.json", {"issues": issues, "compared": sorted(records)})
    def semantic_stop():
        write(root / "receipts/verdict.json", {"semantic_issues": issues, "attribution_unavailable": ["semantic qualification failed"],
                                              "qualified_cost": False})
        return False

    if records["clean/original"]["test"] is None:
        return semantic_stop()
    ref = records["clean/original"]["test"]
    names = json.loads((root / "receipts/clean/original/logical-units.json").read_text())
    # The independent original control now supplies an isolated logging-only history.
    for i in (1, 2):
        tag = f"info/repeat-{i}"
        d = root / "receipts" / tag
        d.mkdir(parents=True)
        e = s.env(root) | {"CARGO_LOG": "cargo::compiler=info,cargo::compiler::fingerprint=debug"}
        p = subprocess.run(panel.E2E, cwd=root / "ruff", env=e, capture_output=True, timeout=3900)
        s.payload(d / "stdout.gz", p.stdout)
        s.payload(d / "stderr.gz", p.stderr)
        write(d / "command.json", {"status": p.returncode, "argv": panel.E2E, "logging": e["CARGO_LOG"]})
        try:
            need(p.returncode == 0, "logging-only Cargo failed")
            native_reference(root, tag, p.stdout, names, ref)
            snapshot(root, tag, source)
        except (AssertionError, RuntimeError, ValueError) as error:
            issues.append(tag + ": " + repr(error))
    write(root / "receipts/semantics.json", {"issues": issues, "compared": sorted(records)})
    if issues:
        return semantic_stop()

    tool_dir = counter.build(root, workspace / "tree/scripts/strict-unicode-cost")
    attribution = root / "receipts/attribution"
    attribution.mkdir(exist_ok=True)
    unavailable = []
    try:
        calibration = cost.calibrate(root, tool_dir)
        write(attribution / "calibration.json", calibration)
    except (AssertionError, RuntimeError, ValueError, OSError) as error:
        unavailable.append("calibration: " + repr(error))
    # A counter failure never turns a completed semantic failure into success.
    if not unavailable:
        s.fresh(root, registry=True)
        visit("trace", "cost-cold", "original")
        if issues:
            write(root / "receipts/semantics.json", {"issues": issues, "compared": sorted(records)})
            return semantic_stop()
        try:
            enrollment = census(root, "trace/cost-cold")
        except (ValueError, StopIteration, OSError, RuntimeError) as error:
            unavailable.append("cold enrollment: " + repr(error))
            write(root / "receipts/verdict.json", {"semantic_issues": [], "attribution_unavailable": unavailable,
                                                  "qualified_cost": False})
            return True
        write(attribution / "enrollment.json", enrollment)
        selector = tool_dir / "selected"
        selector.write_text("\n".join(enrollment["paths"]) + "\n")
        samples = attribution / "unchanged"
        for i, mode in enumerate(cost.SCHEDULE, 1):
            tag = f"attribution/unchanged/{i}-{mode}"
            p = cost.run_scope(root / "receipts" / tag, tool_dir / "counter", mode, selector,
                               panel.E2E, root / "ruff", s.env(root))
            if p.returncode != 0:
                unavailable.append(tag + " observer/command exit " + str(p.returncode))
                terminal_error = any(b'"build-finished"' in line and b'false' in line for line in p.stdout.splitlines())
                if terminal_error:
                    issues.append(tag + " recorded a failed Cargo command")
                fallback = "attribution/direct-recheck"
                d = root / "receipts" / fallback
                d.mkdir()
                clean = subprocess.run(panel.E2E, cwd=root / "ruff", env=s.env(root), capture_output=True, timeout=3900)
                s.payload(d / "stdout.gz", clean.stdout)
                s.payload(d / "stderr.gz", clean.stderr)
                write(d / "command.json", {"status": clean.returncode, "argv": panel.E2E})
                try:
                    need(clean.returncode == 0, "ordinary direct repeat after observer failure failed")
                    native_reference(root, fallback, clean.stdout, names, ref)
                except (AssertionError, RuntimeError, ValueError) as error:
                    issues.append(fallback + ": " + repr(error))
                break
            try:
                native_reference(root, tag, p.stdout, names, ref)
            except (AssertionError, RuntimeError, ValueError) as error:
                issues.append(tag + ": " + repr(error))
        if not unavailable and not issues:
            try:
                score = cost.score(samples, enrollment)
                write(attribution / "scores.json", score)
                if not score["measurement_admitted"]:
                    unavailable.append("adjacent untraced whole-command observer guard failed")
            except (AssertionError, RuntimeError, ValueError, OSError) as error:
                unavailable.append("scope topology or counters: " + repr(error))
    write(root / "receipts/verdict.json", {"semantic_issues": issues, "attribution_unavailable": unavailable,
                                          "qualified_cost": not unavailable and not issues})
    print(json.dumps({"role": role, "semantic": issues, "unavailable": unavailable}), flush=True)
    return not issues


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    for k in ["root", "workspace", "cargo", "signed"]:
        ap.add_argument("--" + k, type=Path, required=True)
    ap.add_argument("--role", choices=CARGOS, required=True)
    args = ap.parse_args()
    try:
        rc = main(args)
    except Exception as error:
        import traceback
        if (args.root / "receipts").is_dir():
            write(args.root / "receipts/harness-error.json", {"error": repr(error), "traceback": traceback.format_exc()})
        raise
    raise SystemExit(0 if rc else 1)
