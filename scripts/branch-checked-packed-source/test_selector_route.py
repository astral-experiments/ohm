"""Replay the actual two hosted selectors through the nested Python command."""
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
VERIFIER = HERE.parent / "branch-first-session-e-source/selector_record.py"
OLD = "c9a6a212d38d778ed0e9d2c7057a9dedb179fff2"
NEW = "393b4b05a4bfa3f531a36023846f86236a6b71a9"
ORIGINALS = {
    "41227867294": (13053235847, "dedb5a559ec6d0ecfd0a1e9b9f93ca439b068856ea2cde6b71742eb44d00b5b0", OLD),
    "41242405382": (13058410373, "dab9035aec0bd8b1f4a04ba45c6667b45c648fdc203dbccfea5e6220216d774b", NEW),
}


def verify(folder, source, ok, refusal=None):
    argv = [sys.executable, "-IB", VERIFIER, folder]
    if source is not None:
        argv.extend(("--source", source))
    result = subprocess.run(argv, capture_output=True, text=True)
    assert (result.returncode == 0) == ok, (argv, result.stderr)
    if refusal:
        assert refusal in result.stderr, result.stderr


def main():
    raw = (HERE / "inputs/selector-official.json.gz").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "8083a548b594638bc99330178a16135dd4e7276a81356b679ed200616b1b0a31"
    records = json.loads(gzip.decompress(raw))
    assert set(records) == set(ORIGINALS)
    for run, (artifact, archive, subject) in ORIGINALS.items():
        row = records[run]
        assert (row["artifact_id"], row["zip_sha256"]) == (artifact, archive)
        assert json.loads(row["selector"]["result.json"])["source"] == subject
        assert (row["log"] == "") == (subject == OLD)
        command = row["command"]
        assert command["output_sha256"] == hashlib.sha256(row["log"].encode()).hexdigest()
        assert command["returncode"] == (0 if subject == OLD else 1)
        assert command["argv"][6:] == ([] if subject == OLD else ["--source", NEW])
        if subject == NEW:
            assert "ValueError: different E" in row["log"] and "selector_record.py" in row["log"]
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for name, body in row["selector"].items():
                assert Path(name).name == name
                (folder / name).write_bytes(body.encode())
            for requested in (None, OLD, NEW):
                ok = (requested or OLD) == subject
                verify(folder, requested, ok, None if ok else "different E")
            verify(folder, "0" * 40, False, "invalid choice")
            name = folder / "E-run.stdout"
            orig = name.read_bytes()
            name.write_bytes(orig.replace(b"3 8 2\n", b"3 8 0\n"))
            verify(folder, subject, False, "actual native differs")
    print("Two official selectors; 3 accepts and 7 source or truth-table refusals")


if __name__ == "__main__":
    main()
