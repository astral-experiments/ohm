"""Off-clock real Cargo loader admission, isolated from all score roots."""

import json
import os
from pathlib import Path
import re
import subprocess

from support import need, put, replay, sha, visit


def run(root, out, tools, sdk, env):
    root.mkdir()
    out.mkdir()
    repo = root / "source"
    (repo / "src").mkdir(parents=True)
    manifest = "\n".join(('[package]', 'name="ldv-contact"', 'version="0.1.0"', 'edition="2024"',
                          '[profile.dev]', 'opt-level=1', 'debug="line-tables-only"', ''))
    (repo / "Cargo.toml").write_text(manifest)
    (repo / "Cargo.lock").write_text('version = 4\n\n[[package]]\nname = "ldv-contact"\nversion = "0.1.0"\n')
    env = {**env, "CARGO_TARGET_DIR": str(root / "target"), "CARGO_BUILD_BUILD_DIR": str(root / "build"),
           "CARGO_HOME": str(root / "cargo-home")}
    work = root
    baseline = {}
    for arm in ("plain", "sham", "original", "guard"):
        case = out / arm
        case.mkdir()
        with replay.empty_roots(work, case):
            for phase, value in (("old", 29), ("new", 36), ("repeat", 36)):
                body = ("#[inline(never)] fn emit(v: u32) -> u32 { std::hint::black_box(v) }\n"
                        "fn main() { println!(\"RESULT {}\", emit(" + str(value) + ")); }\n")
                src = repo / "src/main.rs"
                if not src.exists() or src.read_text() != body:
                    src.write_text(body)
                where = case / phase
                _, rust, roster = visit(where, work, repo, sdk, tools, arm, env, [
                    "cargo", "+ohm", "build", "--locked", "--offline", "-j2", "--message-format=json"], include_env=True)
                rows = [json.loads(b) for b in (where / "outer.stdout").read_bytes().splitlines()]
                artifact, = [r for r in rows if r["reason"] == "compiler-artifact"]
                need(artifact["fresh"] is (phase == "repeat"), (arm, phase, artifact["fresh"]))
                exe = Path(artifact["executable"])
                need(subprocess.check_output([exe], env=env) == f"RESULT {value}\n".encode(), (phase, value))
                sends = [r for r in rust if r["kind"] == "full" and r["name"] == "ldv_contact"]
                links = [link for link in roster["linkers"] if link[:2] == ["signed-Wild", "ldv_contact"]]
                need(len(sends) == (phase != "repeat") and sum(z[2] for z in links) == (phase != "repeat"),
                     (arm, phase, roster))
                if arm in ("original", "guard") and phase != "repeat":
                    need(sum(r["activation"] for r in sends) > 0, "missing real LLVM callback")
                    if arm == "guard":
                        need(sum(r["reason_totals"][0] for r in sends) > 0, "no actual omission")
                observation = {"sha256": sha(exe), "bytes": exe.stat().st_size, "argv": [r["argv"] for r in sends],
                               "native": roster, "value": value, "artifact_fresh": artifact["fresh"]}
                if arm == "plain":
                    baseline[phase] = observation
                need(observation == baseline[phase], ("loader changed workload", arm, phase))
                put(where / "admitted.json", observation)
    put(out / "accepted.json", baseline)
