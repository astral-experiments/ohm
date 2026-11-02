"""Small ordinary Cargo gate using Ruff's actual locked autocfg dependency."""

import ast
import json
import os
from pathlib import Path
import shutil
import subprocess

import needed
from support import need, put, replay, sha


def cargo_argv(directory):
    seen = []
    for file in (directory / "trace").glob("exec.[0-9]*"):
        for line in file.read_text().splitlines():
            if line.startswith("execve(") and line.rstrip().endswith("= 0"):
                m = needed.support.EXEC.fullmatch(line)
                need(m, "unparsed successful calibration exec")
                exe, argv = [ast.literal_eval(x) for x in m.groups()[:2]]
                if Path(exe).name == "cargo":
                    seen.append([exe, argv])
    return sorted(seen)


def proxy_calibration(contact, env, root, out):
    out.mkdir()
    command = ["cargo", "+ohm", "--version"]
    seen, output = [], []
    for name, measured in (("plain", False), ("counted", True)):
        dest = out / name
        value, rusts, roster, _, _ = needed.visit(contact, dest, root, root, "plain", env, command, score=measured)
        need(not rusts and not roster["linkers"] and (value is not None) == measured, "different version control")
        seen.append(cargo_argv(dest))
        output.append((dest / "outer.stdout").read_bytes())
    proxy = shutil.which("cargo", path=env["PATH"])
    sdk_cargo = str(contact.sdk / "bin/cargo")
    need(seen[0] == seen[1] and len(seen[0]) == 2 and [proxy, command] in seen[0] and
         any(p == sdk_cargo and a[1:] == ["--version"] for p, a in seen[0]) and
         output[0] == output[1] and output[0].startswith(b"cargo "), "counter changed the rustup or native Cargo argv")
    # Reproduce the rejected invocation. It enters rustup with +ohm as argv[0]
    # and must not execute the installed Cargo or any compiler.
    bad = out / "rejected"
    (bad / "trace").mkdir(parents=True)
    wrong = [contact.tools / "count", bad / "pmu.json", proxy, *command[1:]]
    proc = subprocess.run(["/usr/bin/strace", "-ff", "-qq", "-v", "-s", "131072", "-e", "trace=%process",
                           "-o", bad / "trace/exec", "--", *wrong], cwd=root, env=env, capture_output=True, timeout=60)
    (bad / "stderr").write_bytes(proc.stderr)
    bad_counter = json.loads((bad / "pmu.json").read_bytes())
    need(proc.returncode == os.waitstatus_to_exitcode(bad_counter["status"]) == 1 and
         b"unknown proxy name: '+ohm'" in proc.stderr and cargo_argv(bad) == [[proxy, command[1:]]],
         "failed to reproduce the rejected argv[0]")
    put(out / "accepted.json", {"ordinary": command, "plain": seen[0], "counted": seen[1],
                                "stdout_sha256": sha(out / "plain/outer.stdout"), "rejected": cargo_argv(bad)})


def run(contact, base, donor, expected, work, out, *, hosted_shared=True):
    work.mkdir()
    out.mkdir()
    repo = work / "source"
    (repo / "src").mkdir(parents=True)
    (repo / "Cargo.toml").write_text(
        '[package]\nname="contact-registry"\nversion="0.1.0"\nedition="2024"\n'
        '[dependencies]\nautocfg="=1.5.0"\n[build-dependencies]\nautocfg="=1.5.0"\n'
        '[profile.dev]\nopt-level=1\ndebug="line-tables-only"\nlto="off"\n')
    (repo / "Cargo.lock").write_text(
        'version = 4\n\n[[package]]\nname = "autocfg"\nversion = "1.5.0"\n'
        'source = "registry+https://github.com/rust-lang/crates.io-index"\nchecksum = "' + expected + '"\n\n'
        '[[package]]\nname = "contact-registry"\nversion = "0.1.0"\ndependencies = ["autocfg"]\n')
    (repo / "build.rs").write_text(
        'fn main() { let a=autocfg::new(); assert!(a.probe_type("u128")); '
        'println!("cargo::rerun-if-changed=build.rs"); }\n')
    archive, = (donor / "registry/cache").glob("*/autocfg-1.5.0.crate")
    row, = (donor / "registry/index").glob("*/.cache/au/to/autocfg")
    need(sha(archive) == expected, "different pinned probe library")
    env = {**base, "CARGO_HOME": str(work / "cargo-home"), "CARGO_TARGET_DIR": str(work / "target"),
           "CARGO_BUILD_BUILD_DIR": str(work / "build")}
    baseline = {}
    proofs = {}
    for label in ("plain-A", "plain-B", "original", "guard"):
        arm = "plain" if label.startswith("plain-") else label
        contact.select(arm)
        dest = out / label
        dest.mkdir()
        proofs[label] = {}
        with replay.empty_roots(work, dest):
            home = work / "cargo-home"
            cache = home / "registry/cache" / archive.parent.name
            cache.mkdir(parents=True)
            shutil.copyfile(archive, cache / archive.name)
            index = home / "registry/index" / archive.parent.name
            (index / ".cache/au/to").mkdir(parents=True)
            shutil.copyfile(row, index / ".cache/au/to/autocfg")
            shutil.copyfile(row.parents[3] / "config.json", index / "config.json")
            for phase, val in (("old", 29), ("edit", 36), ("repeat", 36)):
                source = repo / "src/main.rs"
                body = f'fn main(){{println!("{{}} {{}}",std::any::type_name::<autocfg::AutoCfg>(),{val});}}\n'
                if not source.exists() or source.read_text() != body:
                    source.write_text(body)
                spot = dest / phase
                counted_edit = label == "original" and phase == "edit"
                value, rusts, raw, roster, actual = needed.visit(contact, spot, work, repo, arm, env,
                    ["cargo", "+ohm", "build", "--locked", "--offline", "-j2", "--message-format=json"],
                    score=counted_edit, cold=phase == "old", fixture=True)
                need((value is not None) == counted_edit, "missing small real counted Cargo edit")
                rows = [json.loads(l) for l in (spot / "outer.stdout").read_bytes().splitlines()]
                item, = [r for r in rows if r["reason"] == "compiler-artifact" and r["target"]["kind"] == ["bin"]]
                exe = Path(item["executable"])
                verdict = subprocess.check_output([exe], env=env).decode().strip()
                owners = [r for r in rusts if r["kind"] == "full" and r["name"] == "contact_registry"]
                need(item["fresh"] == (phase == "repeat") and verdict.endswith(" " + str(val)) and
                     len(owners) == (phase != "repeat"), ("fixture did not observe true edit/freshness", label, phase))
                if owners and hosted_shared:
                    need(any(a.startswith("autocfg=") and "/build/debug/build/registries/v2-" in a
                             for a in owners[0]["argv"]), "registry fixture was already private")
                if owners and arm != "plain":
                    need(owners[0]["activation"] > 0, "real probe did not contact signed compiler")
                if owners and arm == "guard":
                    need(owners[0]["reason_totals"][0] > 0, "real compiler recorded no skips")
                if phase == "old":
                    need(sorted(r["equivalence"]["suffix"] for r in actual) == ["0", "1"], "wrong small probe multiplicity")
                observed = {"root_argv": [r["argv"] for r in owners], "elf": sha(exe), "verdict": verdict,
                            "fresh": item["fresh"], "roster": roster}
                put(spot / "phase.json", {**observed, "actual_probes": actual, "raw_native": raw})
                if label == "plain-A":
                    baseline[phase] = observed
                need(observed == baseline[phase], ("small no-wrapper workload/bytes differed", label, phase))
                proofs[label][phase] = {"elf": observed["elf"], "verdict": verdict, "raw_native": raw,
                                        "actual_probes": actual, "root_argv": observed["root_argv"],
                                        "hits": sum(r["reason_totals"][0] for r in owners),
                                        "counted_dispatch": counted_edit}
    contact.select("plain")
    put(out / "accepted.json", proofs)
