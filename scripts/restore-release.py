"""Recover one verified distribution from a previous protected release build."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile


def digest(path):
    checksum = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def restore(directory):
    repo = os.environ["GITHUB_REPOSITORY"]
    revision = os.environ["RETRY_REVISION"]
    run = int(os.environ["RETRY_RUN"])
    target = os.environ["OHM_TARGET"]
    name = os.environ["OHM_TOOLCHAIN"]
    prefix = f"{name}-{target}"
    api = f"repos/{repo}/actions"

    listing = subprocess.check_output(["gh", "api", f"{api}/runs/{run}/artifacts"])
    (artifact,) = [a for a in json.loads(listing)["artifacts"] if a["name"] == prefix]
    origin = artifact["workflow_run"]
    if origin["id"] != run or origin["head_sha"] != revision or artifact["expired"]:
        raise ValueError(f"Unexpected source for {prefix}")

    bundle = directory / "artifact.zip"
    with bundle.open("wb") as file:
        subprocess.run(
            ["gh", "api", f"{api}/artifacts/{artifact['id']}/zip"],
            stdout=file, check=True,
        )
    if artifact["digest"] != "sha256:" + digest(bundle):
        raise ValueError(f"Artifact digest mismatch for {prefix}")

    proof = f"{prefix}-provenance.json"
    files = [f"{prefix}.tar.gz", proof]
    with zipfile.ZipFile(bundle) as archive:
        names = files + [f"{file}.sha256" for file in files]
        if sorted(archive.namelist()) != sorted(names):
            raise ValueError(f"Unexpected contents of {prefix}")
        for file in names:
            with archive.open(file) as src, (directory / file).open("xb") as dst:
                shutil.copyfileobj(src, dst)

    for file in files:
        checksum = (directory / f"{file}.sha256").read_text()
        if checksum != f"{digest(directory / file)}  {file}\n":
            raise ValueError(f"Checksum mismatch for {file}")

    path = os.environ["MANIFEST_PATH"]
    manifest = json.loads(Path(path).read_bytes())
    sources = {key: {"revision": value["revision"]} for key, value in manifest["sources"].items()}
    if llvm := os.environ["LLVM_REVISION"]:
        sources["llvm"] = {"revision": llvm}
    expected = {
        "schema_version": 1,
        "toolchain": name,
        "target": target,
        "coordinator": {"repository": repo, "revision": revision},
        "manifest": {"path": path, "sha256": digest(Path(path))},
        "sources": sources,
        "bundled_tools": manifest.get("bundled_tools", {}) if target == "x86_64-unknown-linux-gnu" else {},
    }
    if json.loads((directory / proof).read_bytes()) != expected:
        raise ValueError(f"Provenance mismatch for {prefix}")
    print(f"Restored {prefix} from release build {run} at {revision}")


if __name__ == "__main__":
    directory = Path(tempfile.mkdtemp(dir=os.environ["RUNNER_TEMP"]))
    restore(directory)
    with open(os.environ["GITHUB_OUTPUT"], "a") as file:
        print(f"directory={directory}", file=file)
