"""Distinguish a test's runtime executable path from a compile-time read of the executable."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

from objects import require


def run(folder, parent, *, extra=(), jobs=4, prebuild=False):
    folder.mkdir()
    work = folder / "source"
    for name in ("src", "tests"):
        (work / name).mkdir(parents=True)
    (work / "Cargo.toml").write_text(
        '[package]\nname="edge-tool"\nversion="0.1.0"\nedition="2021"\n[profile.dev]\ndebug=0\n'
    )
    (work / "src/lib.rs").write_text("pub fn stable() -> usize { 1 }\n")
    binary = work / "src/main.rs"

    def select(value):
        binary.write_text(
            'fn main(){println!("OHM_NATIVE_DIRECT_TOKEN=' + str(value) + '");}\n'
        )

    (work / "tests/path.rs").write_text("""
#[test] fn reads_new_executable() {
 let output=std::process::Command::new(env!("CARGO_BIN_EXE_edge-tool")).output().unwrap();
 assert!(output.status.success());
 assert_eq!(String::from_utf8(output.stdout).unwrap().trim(), format!("OHM_NATIVE_DIRECT_TOKEN={}", std::env::var("EXPECTED_EDGE").unwrap()));
}
""")
    (work / "tests/blob.rs").write_text("""
const BLOB: &[u8] = include_bytes!(env!("CARGO_BIN_EXE_edge-tool"));
#[test] fn reads_selected_executable_bytes() {
 let marker=b"OHM_NATIVE_DIRECT_TOKEN=";
 let seen:std::collections::BTreeSet<_>=BLOB.windows(marker.len()+1)
   .filter(|w| w.starts_with(marker)).map(|w| w[marker.len()])
   .filter(|q| *q==b'3' || *q==b'4').collect();
 let expected=std::env::var("EXPECTED_EDGE").unwrap();
 assert_eq!(seen, [expected.as_bytes()[0]].into_iter().collect());
}
""")
    e = parent | {
        "CARGO_HOME": str(folder / "cargo-home"),
        "CARGO_TARGET_DIR": str(folder / "target"),
        "CARGO_BUILD_BUILD_DIR": str(folder / "build"),
        "CARGO_NET_OFFLINE": "true",
    }
    result = {}

    def phase(label, value):
        cmd = [
            "cargo",
            "+ohm",
            *extra,
            "test",
            "--no-run",
            "--offline",
            f"-j{jobs}",
            "--message-format=json",
        ]
        p = subprocess.run(cmd, cwd=work, env=e, capture_output=True, check=False)
        (folder / (label + ".stdout")).write_bytes(p.stdout)
        (folder / (label + ".stderr")).write_bytes(p.stderr)
        if p.returncode:
            errors = [
                json.loads(line)["message"]["rendered"]
                for line in p.stdout.splitlines()
                if json.loads(line).get("reason") == "compiler-message"
                and json.loads(line)["message"]["level"] == "error"
            ]
            raise ValueError((label, errors, p.stderr.decode()[-1000:]))
        rows = [json.loads(v) for v in p.stdout.splitlines()]
        paths = {
            r["target"]["name"]: Path(r["executable"])
            for r in rows
            if r.get("executable") and r["target"]["kind"] == ["test"]
        }
        require(set(paths) == {"path", "blob"}, ("test inventory", label))
        cases = {}
        for name, path in paths.items():
            actual = subprocess.run(
                [path, "--nocapture", "--test-threads=1"],
                env=e | {"EXPECTED_EDGE": str(value)},
                cwd=work,
                capture_output=True,
                check=False,
            )
            cases[name] = {
                "exit": actual.returncode,
                "elf": hashlib.sha256(path.read_bytes()).hexdigest(),
                "stdout": actual.stdout.decode(),
                "stderr": actual.stderr.decode(),
            }
        tool = Path(e["CARGO_TARGET_DIR"]) / "debug/edge-tool"
        value_on_disk = subprocess.check_output([tool], env=e, text=True).strip()
        require(
            value_on_disk == "OHM_NATIVE_DIRECT_TOKEN=" + str(value),
            ("wrong external executable", label),
        )
        result[label] = {
            "verdicts": cases,
            "dirty": [
                [r["target"]["name"], r["target"]["kind"], r["profile"]["test"]]
                for r in rows
                if r.get("reason") == "compiler-artifact" and not r["fresh"]
            ],
            "external_executable_sha256": hashlib.sha256(tool.read_bytes()).hexdigest(),
            "external_output": value_on_disk,
        }
        for base in (Path(e["CARGO_TARGET_DIR"]), Path(e["CARGO_BUILD_BUILD_DIR"])):
            for dep in base.rglob("*.d"):
                t = dep.read_text(errors="replace")
                if "CARGO_BIN_EXE_edge-tool" in t and (
                    "/tests/path.rs" in t
                    or "tests/path.rs" in t
                    or "tests/blob.rs" in t
                ):
                    f = folder / (label + "-" + dep.name + ".txt")
                    if f.exists():
                        require(f.read_text() == t, "duplicate dep-info name")
                    else:
                        f.write_text(t)

    select(3)

    def build_binary(label):
        cmd = [
            "cargo",
            "+ohm",
            *extra,
            "build",
            "--bin",
            "edge-tool",
            "--offline",
            f"-j{jobs}",
        ]
        built = subprocess.run(cmd, cwd=work, env=e, capture_output=True, check=False)
        (folder / (label + "-bin.stderr")).write_bytes(built.stderr)
        require(
            built.returncode == 0,
            (label, "could not prebuild genuine executable", built.stderr),
        )

    if prebuild:
        build_binary("old")
    phase("old", 3)
    phase("old-settled", 3)
    select(4)
    phase("edit", 4)
    phase("next", 4)
    e |= {
        "CARGO_TARGET_DIR": str(folder / "empty-target"),
        "CARGO_BUILD_BUILD_DIR": str(folder / "empty-build"),
    }
    if prebuild:
        build_binary("empty")
    phase("empty", 4)
    require(
        all(v["verdicts"]["path"]["exit"] == 0 for v in result.values()),
        "runtime path did not follow real executable",
    )
    require(
        all(
            result[k]["verdicts"]["blob"]["exit"] == 0
            for k in ("old", "old-settled", "empty")
        ),
        "independent included executable controls",
    )
    (folder / "result.json").write_text(
        json.dumps(result, sort_keys=True, indent=2) + "\n"
    )
    return result


if __name__ == "__main__":
    import sys

    run(
        Path(sys.argv[1]),
        {
            k: os.environ[k]
            for k in ("HOME", "PATH", "USER", "LANG", "RUSTUP_HOME")
            if k in os.environ
        },
    )
