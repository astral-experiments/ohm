"""Exercise each installed compiler and the original Ohm Cargo on genuine local files."""

import json
import os
from pathlib import Path
import shutil
import subprocess

from capsule import REG, HOST, need, save, sha


def execute(argv, cwd, env, code=0):
    p = subprocess.run(
        [str(x) for x in argv], cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=180
    )
    need(p.returncode == code, (argv, p.returncode, p.stderr[-1800:]))
    return p


def cargo_result(argv, cwd, env, code=0):
    p = execute(
        ["cargo", "+ohm", *argv, "--locked", "--offline", "-j2", "--message-format=json"], cwd, env, code
    )
    rows = list(map(json.loads, p.stdout.splitlines()))
    need(rows[-1] == {"reason": "build-finished", "success": code == 0}, "wrong original Cargo verdict")
    return rows


def smoke(root, manifest, base):
    pack = root / "reopened"
    proxy = Path(shutil.which("rustup", path=base["PATH"])).resolve(strict=True)
    proxies = root / "proxies"
    proxies.mkdir()
    for name in ("rustup", "cargo", "rustc", "rustdoc"):
        (proxies / name).symlink_to(proxy)
    alias = Path(base["RUSTUP_HOME"]) / "toolchains/ohm"
    alias.parent.mkdir(parents=True, exist_ok=True)
    all_rows = {}
    for label in ("normal", "defer"):
        target = Path(manifest["arms"][label]["root"])
        need(target.samefile(pack / label), "foreign installed compiler path")
        if alias.is_symlink():
            alias.unlink()
        alias.symlink_to(target, target_is_directory=True)
        work = root / ("native-" + label)
        (work / "src").mkdir(parents=True)
        env = {
            **base,
            "PATH": str(proxies) + os.pathsep + base["PATH"],
            "RUSTC": str(target / "bin/rustc"),
            "RUSTUP_TOOLCHAIN": "ohm",
            "CARGO_HOME": str(work / "cargo-home"),
            "CARGO_TARGET_DIR": str(work / "target"),
            "CARGO_BUILD_BUILD_DIR": str(work / "build"),
            "CARGO_NET_OFFLINE": "true",
            "LD_LIBRARY_PATH": str(target / "lib"),
        }
        env.pop("CARGO_INCREMENTAL", None)
        ver = {}
        for tool in ("rustc", "cargo", "rustdoc"):
            physical = (
                execute(["rustup", "which", "--toolchain", "ohm", tool], work, env).stdout.decode().strip()
            )
            need(Path(physical).samefile(target / "bin" / tool), ("wrong tool", tool, physical))
            ver[tool] = execute([tool, "+ohm", "-vV"], work, env).stdout.decode()
        need(
            REG["signed_cargo"]["revision"] in ver["cargo"]
            and "ohm-1.99.0-22" in ver["cargo"]
            and "host: " + HOST in ver["rustc"]
            and "LLVM version:" in ver["rustc"],
            "foreign compiler/Cargo",
        )
        source = work / "describe.rs"
        source.write_text("/// Verifies the matching documentation tool.\npub fn observed() -> u32 { 29 }\n")
        execute(["rustdoc", "+ohm", "--edition=2024", "--crate-name", "qa_doc", source,
                 "--out-dir", work / "docs"], work, env)
        html = work / "docs/qa_doc/fn.observed.html"
        need(b"Verifies the matching documentation tool" in html.read_bytes(), "rustdoc did not produce source documentation")
        libtrace = execute(["ldd", target / "bin/rustc"], work, env).stdout.decode()
        for family in ("librustc_driver", "libLLVM"):
            actual = [
                line.split("=>", 1)[1].split("(", 1)[0].strip()
                for line in libtrace.splitlines()
                if family in line and "=>" in line
            ]
            need(
                actual
                and all(
                    Path(p).resolve().is_relative_to(target)
                    and sha(Path(p))
                    == manifest["arms"][label]["files"][str(Path(p).resolve().relative_to(target))]
                    for p in actual
                ),
                ("foreign loaded library", family),
            )
        need(
            Path(
                execute(["rustc", "+ohm", "--print", "sysroot"], work, env).stdout.decode().strip()
            ).samefile(target),
            "wrong sysroot",
        )
        expand = work / "expand.rs"
        expand.write_text(
            'extern crate proc_macro; use proc_macro::TokenStream;\n#[proc_macro] pub fn answer(_: TokenStream)->TokenStream{"29u32".parse().unwrap()}\n'
        )
        execute(
            [
                "rustc",
                "+ohm",
                expand,
                "--crate-type=proc-macro",
                "--edition=2024",
                "-o",
                work / "libexpand.so",
            ],
            work,
            env,
        )
        native = work / "native.rs"
        native.write_text('fn main() { println!("{}", expand::answer!()); }\n')
        for level, assertions in ((0, "yes"), (1, "yes"), (1, "no"), (3, "no")):
            binary = work / ("direct-" + str(level) + "-" + assertions)
            execute(
                [
                    "rustc",
                    "+ohm",
                    native,
                    "--edition=2024",
                    "--extern",
                    "expand=" + str(work / "libexpand.so"),
                    "-Copt-level=" + str(level),
                    "-Cdebug-assertions=" + assertions,
                    "-o",
                    binary,
                ],
                work,
                env,
            )
            need(
                execute([binary], work, env).stdout == b"29\n", "generated machine code or proc macro failed"
            )
        (work / "Cargo.toml").write_text(
            '[package]\nname="ohm_stage_witness"\nversion="0.1.0"\nedition="2024"\n[profile.dev]\nopt-level=1\n'
        )
        (work / "Cargo.lock").write_text(
            'version = 4\n\n[[package]]\nname = "ohm_stage_witness"\nversion = "0.1.0"\n'
        )
        lib = work / "src/lib.rs"
        (work / "src/main.rs").write_text('fn main(){println!("{}",ohm_stage_witness::value());}\n')
        (work / "tests").mkdir()
        (work / "tests/native.rs").write_text(
            "#[test] fn compiled_value(){assert_eq!(ohm_stage_witness::value(),29);}\n"
        )
        lib.write_text("pub fn value()->u32 {17}\n")
        cargo_result(["check"], work, env)
        rows = []
        for value in (17, 29):
            lib.write_text(f"pub fn value()->u32 {{{value}}}\n")
            r = cargo_result(["build"], work, env)
            binaries = [Path(i["executable"]) for i in r if i.get("executable")]
            need(
                len(binaries) == 1
                and binaries[0].resolve().is_relative_to(work)
                and execute(binaries, work, env).stdout == f"{value}\n".encode(),
                "stale ordinary Cargo build",
            )
            rows.append([value, sha(binaries[0])])
        warm = cargo_result(["build"], work, env)
        need(
            all(r["fresh"] for r in warm if r["reason"] == "compiler-artifact"),
            "unchanged matched-Cargo smoke rebuilt",
        )
        invalid = "pub fn value()->u32 {false}\n"
        lib.write_text(invalid)
        bad = cargo_result(["test", "--test", "native", "--no-run"], work, env, 101)
        coded = [
            r["message"]
            for r in bad
            if r["reason"] == "compiler-message"
            and r["message"].get("code")
            and r["message"]["level"] == "error"
        ]
        need(
            len(coded) == 1
            and coded[0]["code"]["code"] == "E0308"
            and any(
                s["is_primary"] and any(t["text"] == invalid.strip() for t in s["text"])
                for s in coded[0]["spans"]
            ),
            "wrong original no-run error",
        )
        lib.write_text("pub fn value()->u32 {29}\n")
        r = cargo_result(["test", "--test", "native", "--no-run"], work, env)
        (harness,) = [
            Path(i["executable"]) for i in r if i.get("executable") and i["target"]["kind"] == ["test"]
        ]
        out = execute(
            [harness, "--exact", "compiled_value", "--format", "pretty", "--color", "never"], work, env
        ).stdout
        need(
            harness.resolve().is_relative_to(work)
            and b"test compiled_value ... ok" in out
            and b"1 passed; 0 failed" in out,
            "repaired test harness failed",
        )
        for n, key in manifest["arms"][label]["files"].items():
            need(sha(target / n) == key, ("smoke changed installed compiler", n))
        all_rows[label] = {
            "versions": ver,
            "loaded": libtrace,
            "cargo_values": rows,
            "repair_test": sha(harness),
            "qualified_codegen": [[0, True], [1, True], [1, False], [3, False]],
            "invalid": "E0308",
        }
    need(
        all_rows["normal"]["versions"] == all_rows["defer"]["versions"],
        "different version, host or LLVM in matched compilers",
    )
    save(root / "logs/smoke.json", {"rustup_proxy": sha(proxy), "arms": all_rows})
