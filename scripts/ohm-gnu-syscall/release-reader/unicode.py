"""Check both shipped and integrated Cargo on the native Ruff generator and an actual data edit."""
import collections
import gzip
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build import env_for, h, HOST, LOG, record, REGISTERED, ROOT, SDK, SIGNED

RUFF = "93526150df078af7dd8fc4226cdcc469539d2001"
PROBE = """
fn main() {
    for name in ["NULL", "OHM CHANGED CONTROL", "NUL"] {
        println!("{:?}", unicode_names2::character(name).map(u32::from));
    }
}
"""


def main(repo):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=repo).decode().strip()
    assert git("rev-parse", "HEAD") == RUFF and not git("status", "--porcelain", "--untracked-files=no")
    assert git("rev-parse", "HEAD:crates/ruff_unicode_names2") == "6204e19cfc0fc74f827f8bd5d2f7d807d7045272"
    data = repo / "crates/ruff_unicode_names2/data/NameAliases.txt"
    script = repo / "crates/ruff_unicode_names2/build.rs"
    original, valid_script = data.read_bytes(), script.read_bytes()
    assert original.count(b"0000;NULL;control") == 1
    changed = original.replace(b"0000;NULL;control", b"0000;OHM CHANGED CONTROL;control")
    test = ROOT / "unicode-probe.rs"
    test.write_text(PROBE)
    product = ROOT / "construction/target/release/cargo"
    manifest = json.loads((ROOT / "product/product.json").read_bytes())
    assert h(product) == manifest["sha256"]
    signed = ROOT / "signed-cargo"
    os.link(SDK / "bin/cargo", signed)
    assert h(signed) == SIGNED
    env = env_for("host-registry")
    record("ruff-registry", ["cargo", "+ohm", "fetch", "--locked", "--target", HOST], repo, dict(env, CARGO_NET_OFFLINE="false"))
    outcomes = []
    for role, image, key in [("signed", signed, SIGNED), ("integrated", product, manifest["sha256"])]:
        if role == "integrated":
            temp = SDK / "bin/cargo.integration"
            shutil.copy2(image, temp)
            temp.replace(SDK / "bin/cargo")
        assert h(SDK / "bin/cargo") == key
        for separate in (False, True):
            arm = role + ("-explicit-host" if separate else "-plain")
            env = env_for(arm)
            version = record(arm + "/identity", ["cargo", "+ohm", "-Vv"], repo, env)
            assert REGISTERED["integrated" if role == "integrated" else "released"]["commit"].encode() in version.stdout
            assert not Path(env["CARGO_TARGET_DIR"]).exists() and not Path(env["CARGO_BUILD_BUILD_DIR"]).exists()
            args = ["cargo", "+ohm", "build", "-p", "ruff_unicode_names2", "--locked", "--offline", "-j4", "--message-format=json"]
            if separate:
                args += ["--target", HOST]
            generated = {}
            for phase in ("cold", "first", "repeat", "edit", "edit-repeat", "clean-edit", "bad", "repair"):
                if phase == "edit":
                    data.write_bytes(changed)
                if phase == "bad":
                    script.write_bytes(valid_script + b"\nconst _: usize = OHM_UNKNOWN_294_QA;\n")
                if phase == "repair":
                    script.write_bytes(valid_script)
                    data.write_bytes(original)
                run_env = env_for(arm + "-clean") if phase == "clean-edit" else env
                prefix = arm + "/" + phase
                traces = ROOT / "unicode-trace" / prefix
                traces.mkdir(parents=True)
                command = ["strace", "-ff", "-q", "-s", "262144", "-e", "trace=execve,execveat", "-o", traces / "proc", *args]
                proc = record(prefix, command, repo, run_env, 101 if phase == "bad" else 0)
                rows = [json.loads(line) for line in proc.stdout.splitlines()]
                assert rows[-1] == {"reason": "build-finished", "success": phase != "bad"}
                if phase == "bad":
                    assert any(r.get("message", {}).get("code", {}).get("code") == "E0425" for r in rows if isinstance(r.get("message", {}).get("code"), dict))
                    continue
                typed = [r for r in rows if r["reason"] == "compiler-artifact"]
                assert len(typed) == 17
                unit, = [r for r in typed if (r["target"]["name"], r["target"]["kind"]) == ("unicode_names2", ["lib"])]
                (archive,) = [Path(v) for v in unit["filenames"] if v.endswith(".rlib")]
                gen, = [Path(r["out_dir"]) for r in rows if r["reason"] == "build-script-executed" and r["package_id"] == unit["package_id"]]
                generated[phase] = {p.name: h(p) for p in gen.glob("*.rs")}
                assert len(generated[phase]) == 3
                events = collections.Counter()
                bitstream = []
                for path in sorted(traces.iterdir()):
                    for line in path.read_bytes().splitlines():
                        item = re.match(rb'^execve\("([^"]+)",', line)
                        if item and line.endswith(b" = 0"):
                            bitstream.append(line)
                            events[os.path.basename(os.fsdecode(item[1]))] += 1
                (LOG / prefix / "execve.gz").write_bytes(gzip.compress(b"\n".join(bitstream), mtime=0))
                dirty = [r["target"]["name"] for r in typed if not r["fresh"]]
                if phase in ("first", "repeat", "edit-repeat"):
                    assert not dirty and events["rustc"] == events["ld.bfd"] == 0, (arm, phase, dirty, events)
                if phase in ("edit", "repair"):
                    assert "build-script-build" in dirty and "unicode_names2" in dirty and events["rustc"] >= 2 and events["ld.bfd"] >= 1
                exe = ROOT / "unicode-probe"
                depdirs = sorted({str(Path(name).parent) for r in typed for name in r["filenames"]})
                lookup = [arg for directory in depdirs for arg in ("-L", "dependency=" + directory)]
                record(prefix + "/probe-build", ["rustc", "+ohm", "--crate-name", "unicode_probe", test, "--extern",
                        "unicode_names2=" + str(archive), *lookup, "-o", exe], repo, run_env)
                result = record(prefix + "/probe", [exe], repo, run_env).stdout
                edited = phase in ("edit", "edit-repeat", "clean-edit")
                assert result == (b"None\nSome(0)\nSome(0)\n" if edited else b"Some(0)\nNone\nSome(0)\n")
                outcomes.append({"arm": arm, "phase": phase, "typed": len(typed), "dirty": dirty,
                                 "kernel": dict(events), "generated": generated[phase], "probe": result.decode()})
            assert generated["first"] == generated["repeat"] == generated["repair"] == generated["cold"]
            assert generated["edit"] == generated["edit-repeat"] == generated["clean-edit"]
            assert {name for name in generated["edit"] if generated["edit"][name] != generated["cold"][name]} == {"generated_alias.rs"}
            assert not git("status", "--porcelain", "--untracked-files=no")
    (LOG / "unicode-terminal.json").write_text(json.dumps(outcomes, sort_keys=True, indent=2) + "\n")
    print("Verified the signed and merged Cargo with both native invocations and a clean behavioral oracle.", flush=True)


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
