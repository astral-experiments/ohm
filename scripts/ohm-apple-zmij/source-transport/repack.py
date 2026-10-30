"""Regenerate the pinned QA bundle from a checkout containing the candidate's objects."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def main(repository, output):
    source = json.loads(Path(__file__).with_name("source.json").read_text())
    base = source["public_revision"]
    candidate = source["candidate_revision"]
    header = (
        f"# v2 git bundle\n-{base} rust-lang/rust 1.99.0\n"
        f"{candidate} {source['ref']}\n\n"
    )
    with output.open("xb") as stream:
        stream.write(header.encode())
        stream.flush()
        subprocess.run(
            ["git", "-C", repository, "-c", "pack.threads=1", "-c", "pack.allowPackReuse=false",
             "-c", "pack.compression=6", "pack-objects", "--revs", "--thin", "--no-sparse",
             "--delta-base-offset", "--no-reuse-object", "--no-reuse-delta", "--window=10",
             "--depth=50", "--stdout"],
            input=f"{candidate}\n^{base}\n".encode(), stdout=stream, check=True,
        )
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    if digest != source["bundle_sha256"]:
        raise SystemExit(f"Bundle bytes differ from the packet: {digest}")
    print(digest)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: repack.py COMPILER-CHECKOUT NEW-BUNDLE-FILE")
    main(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
