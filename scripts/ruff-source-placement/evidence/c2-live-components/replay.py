"""Reproduce the two real LLVM producer identities on the original #28106 before-O1 buffers."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from verify import require, sha


def replay(args):
    corpus = json.loads((HERE / "corpus.json").read_bytes())
    with args.originals.open("rb") as data:
        require(hashlib.file_digest(data, "sha256").hexdigest() == corpus["signed_originals_zip"], "different immutable input ZIP")
    selected = sorted(corpus["CGUs"]) if args.all_units else [k for k in corpus["CGUs"] if k.endswith(args.unit)]
    require(len(selected) == (21 if args.all_units else 1), "unbound unit")
    with zipfile.ZipFile(args.originals) as z:
        for key in selected:
            for role in ("old", "new"):
                expected = corpus["CGUs"][key][role]
                data = gzip.decompress(z.read("cgu-originals/" + expected["input"] + ".gz"))
                require(sha(data) == expected["input"], "different before-O1 source")
                fd = os.memfd_create("ordinary-signed-input")
                try:
                    with os.fdopen(os.dup(fd), "wb") as f:
                        f.write(data)
                    os.lseek(fd, 0, os.SEEK_SET)
                    invocation = [args.tools / "live", args.tools / "product.so", str(fd), key, "policy"]
                    proc = subprocess.run(invocation, capture_output=True, check=True, pass_fds=[fd])
                    name, mode, module_key, size = proc.stdout.decode().strip().split()
                    require((name, mode, module_key, int(size)) == (key, "policy", expected["key"], corpus["wire_lengths"][role][key]),
                            "genuine continuous optimizer changed its source-bound result")
                finally:
                    os.close(fd)
    print(len(selected)*2, "actual live post-O1 product keys and lengths reproduced")


if __name__ == "__main__":
    opts = argparse.ArgumentParser()
    opts.add_argument("--originals", required=True, type=Path)
    opts.add_argument("--tools", required=True, type=Path)
    g = opts.add_mutually_exclusive_group(required=True)
    g.add_argument("--unit")
    g.add_argument("--all-units", action="store_true")
    replay(opts.parse_args())
