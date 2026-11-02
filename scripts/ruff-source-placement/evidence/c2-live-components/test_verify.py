"""Self-consistently refresh the checksum after each corruption. The independent raw/semantic guard must still reject it."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from verify import verify


def mutate(which, data):
    row = next(iter(data["CGUs"].values()))
    if which == "source":
        data["source_TU_SHA256"] = data["signed_originals_zip"]
    elif which == "counter":
        data["profiles"]["policy"][0]["count"] += 1
    elif which == "phase":
        data["profiles"]["policy"][0]["input_sha"] = row["new"]["O1"]
    elif which == "wire":
        data["wire_lengths"]["old"][min(data["CGUs"])] += 1
    elif which == "allocsize":
        data["source_controls"]["definition-only"]["32"]["key"] = data["source_controls"]["definition-only"]["16"]["key"]
    elif which == "loop":
        data["loop_metadata_controls"]["observable-loop-position-6"]["post"] = "accepted"
    else:
        raise AssertionError(which)


def main():
    original = json.loads((HERE / "corpus.json").read_bytes())
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        for name in (HERE / "SHA256SUMS").read_text().splitlines():
            f = name.split("  ")[1]
            if f not in ("corpus.json", "SHA256SUMS"):
                (d / f).symlink_to(HERE / f)
        for case in ("source", "counter", "phase", "wire", "allocsize", "loop"):
            candidate = copy.deepcopy(original)
            mutate(case, candidate)
            (d / "corpus.json").write_text(json.dumps(candidate))
            (d / "SHA256SUMS").write_text("".join(
                hashlib.sha256(f.read_bytes()).hexdigest() + "  " + f.name + "\n"
                for f in sorted(d.iterdir()) if f.name != "SHA256SUMS"))
            try:
                verify(d)
            except ValueError:
                continue
            raise AssertionError("unexpected acceptance of " + case)
    print("six independent producer, physical-profile, allocation and metadata corruption checks passed")


if __name__ == "__main__":
    main()
