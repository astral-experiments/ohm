"""Exercise byte-distinct CTFE literals with equal intern-table hash and a real cyclic static graph."""

import argparse, gzip, hashlib, json, os, re, shutil, subprocess, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def digest(b):
    return hashlib.sha256(b).hexdigest()


def main():
    arg = argparse.ArgumentParser(description=__doc__)
    arg.add_argument("--sdk", type=Path, required=True)
    arg.add_argument("--out", type=Path, required=True)
    a = arg.parse_args()
    r = a.out
    r.mkdir()
    sdk = a.sdk.resolve(strict=True)
    (driver,) = (sdk / "lib").glob("librustc_driver-*.so")
    assert shutil.disk_usage(r).free > 4 * (1 << 30) + 100 * (1 << 20)
    with tempfile.TemporaryDirectory(dir=r, prefix="trial-") as t:
        w = Path(t)
        project = w / "source"
        (project / "src").mkdir(parents=True)
        reg = w / "cargo-home"
        reg.mkdir()
        rup = w / "rustup"
        (rup / "toolchains").mkdir(parents=True)
        (rup / "toolchains/ohm").symlink_to(sdk)
        build = w / "build"
        target = w / "target"
        (reg / "config.toml").write_text("[build]\nbuild-dir = " + json.dumps(str(build)) + "\n")
        (project / "Cargo.toml").write_text(
            '[package]\nname="leaf"\nversion="0.0.1"\nedition="2024"\n[workspace]\n[profile.dev]\nopt-level=1\n'
        )
        (project / "src/lib.rs").write_text(
            'pub struct Node {pub next: &\\x27static Node, pub tag: u8}\npub static ONE:Node=Node{next:&TWO,tag:17};\npub static TWO:Node=Node{next:&ONE,tag:17};\npub const BYTES:&[u8;257]=include_bytes!("literal.bin");\n#[inline] pub fn middle()->u8{BYTES[128]}\n'.replace(
                "\\x27", "'"
            )
        )
        (project / "src/main.rs").write_text(
            'fn main(){assert!(std::ptr::eq(leaf::ONE.next,&leaf::TWO));assert!(std::ptr::eq(leaf::TWO.next,&leaf::ONE));assert!(!std::ptr::eq(&leaf::ONE,&leaf::TWO));assert_eq!(leaf::BYTES[128],leaf::middle());println!("{} {}",leaf::middle(),leaf::ONE.tag);}\n'
        )
        env = {
            "PATH": str(Path(shutil.which("rustup")).parent) + ":/usr/local/bin:/usr/bin:/bin",
            "HOME": str(w),
            "RUSTUP_HOME": str(rup),
            "RUSTUP_AUTO_INSTALL": "0",
            "CARGO_HOME": str(reg),
            "CARGO_TARGET_DIR": str(target),
            "CARGO_NET_OFFLINE": "true",
            "LC_ALL": "C",
            "LD_LIBRARY_PATH": str(sdk / "lib"),
        }
        calls = []

        def cmd(args):
            z = subprocess.run(args, cwd=project, env=env, capture_output=True, timeout=60)
            calls.append(
                {
                    "argv": list(map(str, args)),
                    "status": z.returncode,
                    "stdout": z.stdout.decode(errors="replace"),
                    "stderr": z.stderr.decode(errors="replace"),
                }
            )
            (r / "commands.jsonl.gz").write_bytes(
                gzip.compress(("\n".join(json.dumps(v) for v in calls) + "\n").encode(), mtime=0)
            )
            assert z.returncode == 0, (args, z.stderr[-1100:])
            return z.stdout

        def tool(name):
            return [str(Path(shutil.which("rustup")).parent / name), "+ohm"]

        assert Path(cmd(tool("rustc") + ["--print", "sysroot"]).decode().strip()).samefile(sdk)
        cmd(tool("cargo") + ["generate-lockfile", "--offline"])
        result = {}
        for phase, x in [
            ("first-A", 17),
            ("edit-B", 29),
            ("return-A", 17),
            ("return-B", 29),
            ("return-A2", 17),
            ("return-B2", 29),
            ("unchanged-B", 29),
            ("empty-B", 29),
        ]:
            if phase == "empty-B":
                for s in (target, build):
                    shutil.rmtree(s)
            input = bytes([61]) * 128 + bytes([x]) + bytes([97]) * 128
            literal = project / "src/literal.bin"
            if not literal.exists() or literal.read_bytes() != input:
                literal.write_bytes(input)
            stdout = cmd(tool("cargo") + ["build", "--locked", "--offline", "-j2", "--message-format=json"])
            (r / (phase + ".jsonl.gz")).write_bytes(gzip.compress(stdout, mtime=0))
            units = [
                v for l in stdout.splitlines() if (v := json.loads(l))["reason"] == "compiler-artifact"
            ]
            assert len(units) == 2 and all(u["fresh"] == (phase == "unchanged-B") for u in units)
            libs = [u for u in units if u["target"]["kind"] == ["lib"]]
            assert len(libs) == 1
            (rlib,) = [Path(f) for f in libs[0]["filenames"] if f.endswith(".rlib")]
            listing = cmd(tool("rustc") + ["-Zls=public_hash", rlib])
            (public,) = re.findall(rb"Public hash:\s*([0-9a-f]{32})", listing)
            (binary,) = [Path(u["executable"]) for u in units if u.get("executable")]
            verdict = cmd([binary])
            assert verdict == f"{x} 17\n".encode()
            result[phase] = {
                "byte": x,
                "input_sha": digest(input),
                "public_hash": public.decode(),
                "elf": digest(binary.read_bytes()),
                "verdict": verdict.decode(),
                "fresh": units[0]["fresh"],
            }
        for x in [17, 29]:
            assert len({z["public_hash"] for z in result.values() if z["byte"] == x}) == 1
        assert result["edit-B"]["public_hash"] != result["first-A"]["public_hash"]
        assert result["edit-B"]["elf"] == result["empty-B"]["elf"]
        info = {
            "driver": digest(driver.read_bytes()),
            "source": {f.name: digest(f.read_bytes()) for f in (project / "src").glob("*.rs")},
            "phases": result,
        }
        (r / "result.json").write_text(json.dumps(info, indent=2) + "\n")
        print(info["driver"], result["empty-B"]["verdict"].strip(), len(result))


if __name__ == "__main__":
    main()
