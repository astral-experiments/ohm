"""Reopen the five actual macro images, ordered native diagnostics and locked source."""
import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import historical_macro_controls

ORIGINAL = HERE.parent / "evidence-empty-pilot-41627091024"
hash_bytes = lambda b: hashlib.sha256(b).hexdigest()


def check(ruff):
    with tempfile.TemporaryDirectory() as td:
        temporary = Path(td)
        source_out = temporary / "src"
        subprocess.run([sys.executable, "-IB", HERE / "verify-locked-sources.py",
                        ruff, HERE / "packages", source_out], check=True)
        assert (source_out / "verified.json").read_bytes() == (HERE / "locked-sources.json").read_bytes()
        assert hash_bytes((ORIGINAL / "verified.json").read_bytes()) == "baa6defc2243a30649bed41ebb84e975ed2ed296baffc430544df95fd844e8df"
        original = json.loads((ORIGINAL / "verified.json").read_bytes())
        assert (original["accepted"], original["scored_pairs"], original["confirmation_workers"]) == (False, 0, 0)
        images = historical_macro_controls.materialize()
        with zipfile.ZipFile(ORIGINAL / "original-records.zip") as z:
            prior = json.loads(z.read("prior-get-size-0.5.1-controls/verified.json"))
        invocations = [v["result"] for v in prior.values()]
        invocations += [v for phases in original["ordered"].values() for v in phases.values()]
        recorded = {v["macro"] for v in invocations}
        missing, = recorded - images.keys()
        current = ORIGINAL / "members" / (missing + ".external.zst")
        images[missing] = subprocess.check_output(["zstd", "-qdc", current])
        assert len(recorded) == 5 and set(images) == recorded
        macro_dir = temporary / "elf"
        macro_dir.mkdir()
        for identity, raw in images.items():
            assert len(raw) == 3204376 and hash_bytes(raw) == identity
            (macro_dir / (identity + ".so")).write_bytes(raw)
        actual = temporary / "variants.json"
        subprocess.run([sys.executable, "-IB", HERE / "elf-variants.py", macro_dir, actual], check=True)
        assert actual.read_bytes() == (HERE / "elf-variants.json").read_bytes()
        physical = json.loads(actual.read_bytes())
        for identity, row in physical.items():
            changes = row["changed_text_owners"]
            if changes:
                assert len(changes) == 1 and "StructFieldAttribute as attribute_derive" in next(iter(changes))
                assert sum(changes.values()) == row["changed_section_bytes"][".text"]
        expected = [["`ignore` conflicts with mutually exclusive `size`", 3],
                    ["`size` conflicts with mutually exclusive `size_fn`", 5],
                    ["`ignore` conflicts with mutually exclusive `size_fn`", 7]]
        classes = {}
        for v in invocations:
            assert v["expanded"] == "858c08e42ca3fc6c4a9d79592fcf4e7be4b068c302807c95a7b4314a28f544bf"
            assert v["errors"][1:] == expected
            message, line = v["errors"][0]
            assert line == 1 and message in {m for m, _ in expected}
            assert classes.setdefault(v["macro"], message) == message
        assert len(set(classes.values())) == 3
        return {"complete_elfs":len(images),"genuine_original_observations":len(invocations),
                "triple_by_elf":classes,"unambiguous_original_pairs":expected,
                "accepted_score":original["scored_pairs"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("ruff_git", type=Path)
    args = parser.parse_args()
    print(json.dumps(check(args.ruff_git), sort_keys=True, indent=2))
