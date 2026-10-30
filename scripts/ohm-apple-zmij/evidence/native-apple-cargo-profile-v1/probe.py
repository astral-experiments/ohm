"""Exercise the signed Cargo build entry point with only the CI variables varied."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

CARGO = "2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c"


def main():
    args = argparse.ArgumentParser()
    args.add_argument("--rustup-home", type=Path)
    args.add_argument("--out", type=Path)
    options = args.parse_args()
    env = {key: os.environ[key] for key in ("HOME", "PATH", "TMPDIR") if key in os.environ}
    if options.rustup_home:
        env["RUSTUP_HOME"] = str(options.rustup_home.resolve(strict=True))
    version = subprocess.check_output(["cargo", "+ohm", "-Vv"], env=env, text=True)
    assert "commit-hash: " + CARGO in version, version
    controls = {}
    with tempfile.TemporaryDirectory(prefix="ohm-local-profile-") as directory:
        root = Path(directory)
        source = root / "project"
        (source / "src").mkdir(parents=True)
        (source / "Cargo.toml").write_text('[package]\nname="ohm_profile_probe"\nversion="0.1.0"\nedition="2024"\n[workspace]\n')
        (source / "src/main.rs").write_text('fn main() { println!("13"); }\n')
        for name, flags in (("plain", {}), ("CI", {"CI": "true"}), ("TF_BUILD", {"TF_BUILD": "1"}), ("empty-CI", {"CI": ""})):
            work = root / name
            scope = env | flags | {"CARGO_HOME": str(work / "cargo-home"), "CARGO_TARGET_DIR": str(work / "target"),
                                   "CARGO_BUILD_BUILD_DIR": str(work / "shared"), "CARGO_NET_OFFLINE": "true", "LC_ALL": "C"}
            run = subprocess.run(["cargo", "+ohm", "build", "--offline", "-vv"], cwd=source, env=scope,
                                 text=True, capture_output=True, check=True)
            command, = [l.strip() for l in run.stderr.splitlines() if "Running `" in l and "--crate-name ohm_profile_probe" in l]
            argv = shlex.split(command.split("`", 1)[1].removesuffix("`"))
            values = [argv[i+1] for i,v in enumerate(argv[:-1]) if v=="-C"] + [v[2:] for v in argv if v.startswith("-C") and v!="-C"]
            incremental = [v.removeprefix("incremental=") for v in values if v.startswith("incremental=")]
            stores = [(p, p.with_name("dep-graph.bin")) for p in work.rglob("work-products.bin") if p.parent.parent.name.startswith("ohm_profile_probe-")]
            assert len(incremental) == len(stores) == int(name == "plain"), (name, incremental, stores)
            assert all(p.is_relative_to(Path(incremental[0])) and g.stat().st_size and p.stat().st_size for p,g in stores)
            assert subprocess.check_output([work / "target/debug/ohm_profile_probe"], text=True) == "13\n"
            controls[name] = {"environment": flags, "command": [v.replace(str(root), "$ROOT") for v in argv[argv.index("--crate-name")-1:]],
                              "work_products": [p.relative_to(work).as_posix() for p,g in stores],
                              "graphs": [g.relative_to(work).as_posix() for p,g in stores]}
            print(name, len(incremental), "incremental arguments,", len(stores), "completed sessions")
    if options.out:
        with options.out.open("x") as out:
            json.dump({"cargo": CARGO, "arms": controls}, out, indent=2)
            out.write("\n")


if __name__ == "__main__":
    main()
