#!/usr/bin/env python3
"""Build the #42 control using the same checked upstream source and pinned ThinLTO recipe."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.request

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "coordinator", type=Path, help="checkout with the coordinator packaging change"
    )
    parser.add_argument(
        "output", type=Path, help="new directory for the linker and licenses"
    )
    args = parser.parse_args()
    info = json.loads((args.coordinator / "toolchains/1.99.0/16.json").read_bytes())[
        "bundled_tools"
    ]["wild"]
    revision = info["source"]["revision"]
    assert revision == "e856d81f6683cad80b9fe0ebf1a0c3c403c6fe11"
    url = f"https://codeload.github.com/wild-linker/wild/tar.gz/{revision}"
    with urllib.request.urlopen(url, timeout=120) as request:
        archive = request.read()
    assert hashlib.sha256(archive).hexdigest() == info["sha256"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.output.parent) as d:
        work = Path(d).resolve()
        (work / "source.tar.gz").write_bytes(archive)
        shutil.copyfile(HERE / "middle.patch", work / "source.patch")
        shutil.copyfile(
            args.coordinator / "scripts/build-wild.sh", work / "build-wild.sh"
        )
        assert "git apply ../source.patch" in (work / "build-wild.sh").read_text()
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--platform=linux/amd64",
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "--mount",
                f"type=bind,src={work},dst=/work",
                "--workdir=/work",
                "--env",
                "CARGO_HOME=/work/cargo",
                "docker.io/library/rust@sha256:" + info["source"]["builder_sha256"],
                "sh",
                "build-wild.sh",
            ],
            check=True,
        )
        staged = work / "wild"
        assert (
            hashlib.sha256((staged / "wild").read_bytes()).hexdigest()
            == "bb681a7ee1a50349d97ebbd7ac315c94dac7fcff8db3ff2e0fa93c2261fab7de"
        )
        staged.rename(args.output)


if __name__ == "__main__":
    main()
