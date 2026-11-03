"""Run both ordinary Cargo source histories with an authenticated copy of the existing candidate SDK."""

import argparse, hashlib, json, os, re, shutil, subprocess, tarfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    sdk = args.sdk.resolve()
    work = args.work.resolve()
    assert not work.exists() and shutil.disk_usage(work.parent).free > 15 * 2**30
    assert (
        int(
            re.search(
                r"^MemAvailable:\s+(\d+) kB", Path("/proc/meminfo").read_text(), re.M
            )[1]
        )
        * 1024
        > 8 * 2**30 + 100 * 2**20
    )
    with tarfile.open(Path(__file__).with_name("originals.tar.xz"), "r:xz") as tar:
        original = {m.name: tar.extractfile(m).read() for m in tar if m.isfile()}
    for n, sha in json.loads(original["factory-files.json"]).items():
        with (sdk / n).open("rb") as f:
            assert hashlib.file_digest(f, "sha256").hexdigest() == sha
    work.mkdir()
    (work / "toolchains").mkdir()
    (work / "toolchains/ohm").symlink_to(sdk, target_is_directory=True)
    proxy = Path(shutil.which("rustup")).parent
    for kind, error in [("constant", "E0308"), ("glob", "E0659")]:
        ws = work / kind
        ws.mkdir()
        names = ["origin", "facade", "consumer", "verdict"]
        (ws / "Cargo.toml").write_text(
            '[workspace]\nresolver="3"\nmembers=["origin","facade","consumer","verdict"]\n'
        )
        sources = [
            "",
            "pub use origin::selected;",
            "#[inline(never)] pub fn result() -> u8 { facade::selected!() }",
            'fn main() { println!("{}", consumer::result()); }',
        ]
        for i, (n, file) in enumerate(zip(names, sources)):
            p = ws / n
            (p / "src").mkdir(parents=True)
            dep = (
                f'[dependencies]\n{names[i-1]}={{path="../{names[i-1]}"}}\n'
                if i
                else ""
            )
            (p / "Cargo.toml").write_text(
                f'[package]\nname="{n}"\nversion="0.1.0"\nedition="2024"\n' + dep
            )
            (p / "src" / ("main.rs" if n == "verdict" else "lib.rs")).write_text(
                file + "\n"
            )
        for stage in (
            "original",
            "unchanged",
            "invalid",
            "clean-invalid",
            "repair",
            "clean-repair",
        ):
            content = original[f"{kind}/{stage}/src.rs"]
            file = ws / "origin/src/lib.rs"
            if file.read_bytes() != content:
                file.write_bytes(content)
            state = ws / (stage if stage.startswith("clean-") else "warm")
            env = {
                "PATH": str(proxy) + ":/usr/bin:/bin",
                "HOME": str(work),
                "RUSTUP_HOME": str(work),
                "RUSTUP_AUTO_INSTALL": "0",
                "CARGO_HOME": str(work / "cargo"),
                "CARGO_TARGET_DIR": str(state / "target"),
                "CARGO_BUILD_BUILD_DIR": str(state / "build"),
                "CARGO_INCREMENTAL": "1",
                "CARGO_BUILD_JOBS": "2",
                "CARGO_NET_OFFLINE": "true",
                "LC_ALL": "C",
            }
            run = subprocess.run(
                [
                    "cargo",
                    "+ohm",
                    "check",
                    "--offline",
                    "--message-format=json",
                    "-p",
                    "verdict",
                ],
                env=env,
                cwd=ws,
                capture_output=True,
                timeout=90,
            )
            events = [json.loads(row) for row in run.stdout.splitlines()]
            errors = [
                (r["message"]["code"] or {}).get("code")
                for r in events
                if r["reason"] == "compiler-message"
                and r["message"]["level"] == "error"
            ]
            assert (run.returncode, errors) == (
                (101, [error]) if "invalid" in stage else (0, [])
            ), (kind, stage, run.stderr, errors)
            if stage == "unchanged":
                assert all(
                    r["fresh"] for r in events if r["reason"] == "compiler-artifact"
                )
            print(kind, stage, run.returncode, errors)


if __name__ == "__main__":
    main()
