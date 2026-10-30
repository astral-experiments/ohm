"""Qualify the tree counter and live jobserver on an independent one-library Cargo fixture."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tree_ir
from tree_ir import q, rt
from study import need, save, sha


def main():
    leaf = "gnu_counter_probe"
    rt.WORK.mkdir()
    rt.RUFF.mkdir()
    (rt.RUFF / "Cargo.toml").write_text('[package]\nname="gnu_counter_probe"\nversion="0.0.1"\nedition="2024"\n')
    (rt.RUFF / "src").mkdir()
    (rt.RUFF / "src/lib.rs").write_text('#[unsafe(no_mangle)] pub extern "C" fn counter_fixture(mut value:u64)->u64 { unsafe { core::arch::asm!("nop /*{}*/", inout(reg) value) }; value }\n')
    env = rt.environment()
    rt.record(["cargo","+ohm","generate-lockfile","--offline"], rt.LOG / "lock", rt.RUFF, env)
    q.COMMAND = ["cargo","+ohm","build","-p",leaf,"--target",rt.TARGET,"--locked","--offline","-j4","--message-format=json"]
    q.command(rt.LOG / "cold", env)
    ordinary = rt.LOG / "ordinary"
    result, native = q.command(ordinary, env)
    need([r["crate"] for r in native["rustcs"]] == [leaf], "no actual warm compiler to calibrate")
    rows = q.typed(result.stdout, True)[0]
    root, = [r for r in rows if r["target"]["name"] == leaf]
    rlib, = [Path(n) for n in root["filenames"] if n.endswith(".rlib")]
    save(ordinary / "verified.json", {"archive":q.archive(rlib.read_bytes())})
    observations = tree_ir.measure(rt.LOG / "physical-IR", env, ordinary, leaf=leaf)
    need(observations.keys() == {"cargo",leaf}, "wrong calibrated tree")
    save(rt.LOG / "rustc-gate.json", {"actual_cargo_and_rustc":observations, "typed":q.typed(result.stdout, True)[1],
                                      "workload":"unscored genuine warm one-library binary Rust+GNU-target fixture"})


if __name__ == "__main__":
    main()
