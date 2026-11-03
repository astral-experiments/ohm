"""Reopen the hosted archive and rerun the same native and statistical checks."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile


HERE = Path(__file__).resolve().parent


def sha(path):
    with path.open("rb") as data:
        return hashlib.file_digest(data, "sha256").hexdigest()


def main():
    receipt = json.loads((HERE / "verification.json").read_bytes())
    archive = HERE / "hosted-original.zip.zst"
    reader = HERE.parents[1] / "uv-check-22536/read_original.py"
    assert sha(archive) == receipt["compressed_sha256"]
    assert sha(reader) == receipt["reader_sha256"]
    with tempfile.TemporaryDirectory() as temp:
        outer = Path(temp) / "hosted.zip"
        with outer.open("xb") as data:
            subprocess.run(["zstd", "-qdc", archive], stdout=data, check=True)
        assert sha(outer) == receipt["github_artifact_sha256"]
        inner = Path(temp) / "original.zip"
        with zipfile.ZipFile(outer) as service:
            assert set(service.namelist()) == {"original.zip", "verified.json"}
            with service.open("original.zip") as data, inner.open("xb") as out:
                shutil.copyfileobj(data, out)
            assert json.loads(service.read("verified.json"))["sha256"] == receipt["inner_sha256"]
        assert sha(inner) == receipt["inner_sha256"]
        raw = subprocess.check_output([sys.executable, "-ISB", reader, inner, receipt["inner_sha256"]])
        assert hashlib.sha256(raw).hexdigest() == receipt["original_reader_stdout_sha256"]
        result = json.loads(raw)
        assert result["accepted"] and result["original"]["complete_pairs"] == 8
        assert result["independent_score_sha256"] == receipt["independent_score_sha256"]
    print(raw.decode(), end="")


if __name__ == "__main__":
    main()
