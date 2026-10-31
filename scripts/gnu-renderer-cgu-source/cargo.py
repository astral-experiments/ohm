"""Provision one physically authenticated #301 Cargo; both paths must return the same complete ELF."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from source import digest, need

COMMIT = "c18e91b514b2c4e4966c9ab03232c804af3e1b57"
HASH = "9fb29f6abecad05acb6015990615c5fbb435a5907543f0bd33cf88cada4f5826"
TREE = "bf643fa158734642bfee4a2aa8eff4d98bd8a09c"
SOURCE_RECIPE = "1e3b37ac28ed11a638d3ba2093b54d83ca10ce14"
ORIGINAL_READER = "17981f5b807be81496282dd5a58e579e71586962"


def setup(root, mode, reader):
    dest = root / "cargo"
    dest.mkdir()
    pin = {"archive": ORIGINAL_READER, "source": SOURCE_RECIPE}[mode]
    need(
        subprocess.check_output(["git", "-C", reader, "rev-parse", "HEAD"], text=True).strip() == pin,
        "different Cargo recipe",
    )
    if mode == "archive":
        sys.path.insert(0, str(reader / "scripts/gnu-example-ceiling"))
        import kit

        rec = kit.acquire_cargo(dest)
        need(rec["source"] == COMMIT and rec["source_tree"] == TREE, "wrong Cargo provenance")
    else:
        temp = Path(os.environ["RUNNER_TEMP"])
        builder = temp / "ohm-aarch64-linux-zmij"
        product = temp / "gnu-cargo293-build"
        need(not builder.exists() and not product.exists(), "historical source paths in use")
        script = reader / "scripts/ohm-gnu-syscall/source-rebuild"
        env = dict(os.environ, GITHUB_ENV=str(dest / "historical-env"))
        subprocess.run(["bash", script / "prepare.sh"], env=env, cwd=reader, check=True)
        for line in (dest / "historical-env").read_text().splitlines():
            key, value = line.split("=", 1)
            env[key] = value
        need(Path(env["QA_ROOT"]) == builder, "original builder path changed")
        subprocess.run(
            [sys.executable, "-IB", script / "rebuild.py", "rustc", "builder"],
            env=env,
            cwd=reader,
            check=True,
        )
        (product / "receipts").mkdir(parents=True)
        subprocess.run(
            [sys.executable, "-IB", script / "rebuild.py", "cargo", builder],
            env=dict(env, QA_ROOT=str(product)),
            cwd=reader,
            check=True,
        )
        rec = json.loads((product / "receipts/physical-cargo.json").read_text())
        need(
            rec["source"]["source"] == COMMIT
            and rec["source"]["tree"] == TREE
            and rec["rebuilt"] == HASH,
            "wrong freshly rebuilt Cargo",
        )
        shutil.copy2(product / "product/cargo", dest / "cargo-301")
        shutil.copy2(product / "product/product.json", dest / "cargo-product.json")
        # Large historical build dirs remain isolated; free only these private completed targets.
        for path in (builder, product):
            need(path.parent == temp and not path.is_symlink(), "unsafe temporary Cargo path")
            shutil.rmtree(path)
    binary = dest / "cargo-301"
    need(
        binary.stat().st_size == 50945080 and digest(binary.read_bytes()) == HASH,
        "Cargo executable differs",
    )
    version = subprocess.check_output([binary, "-Vv"], text=True)
    need(COMMIT in version, "Cargo does not report #301")
    (root / "receipts/cargo.json").write_text(
        json.dumps(
            {
                "mode": mode,
                "recipe": pin,
                "commit": COMMIT,
                "sha256": HASH,
                "version": version,
                "provenance": rec,
            },
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    setup(Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]).resolve())
