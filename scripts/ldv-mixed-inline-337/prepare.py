"""Recover the two measured drivers and their shared LLVM from the original factory archive."""
from pathlib import Path
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import uuid

archive = Path(sys.argv[1]).resolve(strict=True)
with archive.open("rb") as f:
    assert hashlib.file_digest(f, "sha256").hexdigest() == "11368598860f3621dda6d84e87df7b84acaf4b44920e6387ace3be412c78b45a"
driver = "librustc_driver-fa217dfcec654979.so"
llvm = "libLLVM.so.23.1-rust-1.99.0-beta"
objects = {
    "e47bfe74db67860c7ae4edeecd04d119fe12ece51e4361b251b0c29d7a053bc8": (143170416, [Path("sdk-P", driver)]),
    "cb6bd1e8074cfb4c092b270fa1450fcbf59941315615a5af48d537edeaf1933b": (143176120, [Path("sdk-C", driver)]),
    "43bac9749e539cd5988a4d5452b64582cf07ac9e7c059fde29c7bee76e106c51": (208144480, [Path("sdk-P", llvm), Path("sdk-C", llvm)]),
}
assert shutil.disk_usage(".").free > sum(n for n, _ in objects.values()) + 64 * 2**20
for role in "PC":
    Path("sdk-" + role).mkdir()
seen = set()
with subprocess.Popen(["unzip", "-p", str(archive), "matched-stage.tar.zst"], stdout=subprocess.PIPE) as zipped:
    with subprocess.Popen(["zstd", "-qdc"], stdin=zipped.stdout, stdout=subprocess.PIPE) as decoded:
        zipped.stdout.close()
        with tarfile.open(fileobj=decoded.stdout, mode="r|") as source:
            for member in source:
                digest = member.name.removeprefix("capsule/objects/")
                if digest not in objects:
                    continue
                size, paths = objects[digest]
                assert member.name == "capsule/objects/" + digest and digest not in seen
                assert member.isfile() and member.size == size
                partial = paths[0].with_suffix(".partial-" + uuid.uuid4().hex)
                with source.extractfile(member) as data, partial.open("xb") as file:
                    shutil.copyfileobj(data, file)
                with partial.open("rb") as file:
                    assert hashlib.file_digest(file, "sha256").hexdigest() == digest
                partial.rename(paths[0])
                for other in paths[1:]:
                    os.link(paths[0], other)
                seen.add(digest)
        # tar archives can have padding after their end marker.
        while decoded.stdout.read(65536):
            pass
        assert decoded.wait() == 0
    assert zipped.wait() == 0
assert seen == objects.keys()
