"""Rebuild either experimental control using the coordinator's pinned Wild builder."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.request

EXPECTED = {
    "upstream-profile": "1079dffdaee2bc9f81a8aebd800339fdbc3922c08c31cb319c7cc70cec2bb76b",
    "relocations": "06656bf54bbfad2ae2b669eceb79740c1456a8421dd160ae4aaeabc614d176ba",
}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("arm", choices=EXPECTED)
    ap.add_argument("coordinator", type=Path, help="checkout with the measured Wild packaging change")
    ap.add_argument("output", type=Path, help="new directory for the executable and licenses")
    args = ap.parse_args()
    manifest = json.loads((args.coordinator / "toolchains/1.99.0/15.json").read_text())
    wild = manifest["bundled_tools"]["wild"]
    source = wild["source"]
    with urllib.request.urlopen("https://codeload.github.com/wild-linker/wild/tar.gz/" + source["revision"],
                                timeout=120) as response:
        archive = response.read()
    assert hashlib.sha256(archive).hexdigest() == wild["sha256"]
    builder = (args.coordinator / "scripts/build-wild.sh").read_text()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.output.parent) as tmp:
        work = Path(tmp).resolve()
        if args.arm == "upstream-profile":
            assert builder.count("CARGO_PROFILE_DIST_LTO=thin ") == 1
            builder = builder.replace("CARGO_PROFILE_DIST_LTO=thin ", "")
        else:
            assert builder.count("cd source\n") == 1
            builder = builder.replace("cd source\n", "cd source\ngit apply --unidiff-zero ../relocations.patch\n")
            shutil.copyfile(Path(__file__).with_name("relocations.patch"), work / "relocations.patch")
        (work / "source.tar.gz").write_bytes(archive)
        (work / "build-wild.sh").write_text(builder)
        subprocess.run([
            "docker", "run", "--rm", "--platform=linux/amd64", "--user", f"{os.getuid()}:{os.getgid()}",
            "--mount", f"type=bind,src={work},dst=/work", "--workdir=/work", "--env", "CARGO_HOME=/work/cargo",
            "docker.io/library/rust@sha256:" + source["builder_sha256"], "sh", "build-wild.sh",
        ], check=True)
        staged = work / "wild"
        assert hashlib.sha256((staged / "wild").read_bytes()).hexdigest() == EXPECTED[args.arm]
        staged.rename(args.output)


if __name__ == "__main__":
    main()
