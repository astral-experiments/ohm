"""Small ordinary Cargo gate using Ruff's actual locked autocfg dependency."""

import json
from pathlib import Path
import shutil
import subprocess

import needed
from support import need, put, replay, sha


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
                _, rusts, raw, roster, actual = needed.visit(contact, spot, work, repo, arm, env,
                    ["cargo", "+ohm", "build", "--locked", "--offline", "-j2", "--message-format=json"],
                    cold=phase == "old", fixture=True)
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
                                        "hits": sum(r["reason_totals"][0] for r in owners)}
    contact.select("plain")
    put(out / "accepted.json", proofs)
