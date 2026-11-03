"""Exercise the native admission and hardware-reader checks on mutated copies of real receipts."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import review_compact as review


def run(qa, origin):
    receipt = json.loads((origin / "published.json").read_bytes())
    stage = receipt["stage"]
    prefix = "placement-stock-"
    if stage == "native":
        checks = [
            ("admission-verified-1", ["new_gate", "eligible"], False),
            ("admission-verified-2", ["raw", "id"], 0),
            ("original-migration-reopened", ["results", "C3b-to-Stock4", "remaining_hits"], 15),
            ("original-migration-reopened", ["results", "Stock4-to-C3b", "prior_and_foreign_seals"], False),
            ("original-migration-reopened", ["counter_samples"], 1),
            ("admission-verified-1", ["new_gate", "physical_reverse"], []),
        ]
    else:
        checks = [
            ("survey-verified-1", ["counts", "option", "Stock4", "new", "instructions"], 197),
            ("survey-verified-1", ["counts", "option", "C3b", "new", "running"], 0),
            ("survey-verified-2", ["source", "Stock4"], "0" * 40),
            ("survey-verified-2", ["raw", "job"], 0),
            ("survey-verified-1", ["assignment", "roles"], ["C3b", "P", "Stock4"]),
        ]
    for basename, fields, replacement in checks:
        with TemporaryDirectory() as t:
            d = Path(t)
            for file in (*origin.glob("*.zip"), origin / "published.json"):
                shutil.copyfile(file, d / file.name)
            zipname = prefix + basename
            path = d / (zipname + ".zip")
            datum = review.document(path)
            parent = datum
            for field in fields[:-1]:
                parent = parent[field]
            assert parent[fields[-1]] != replacement
            parent[fields[-1]] = replacement
            with ZipFile(path, "w", ZIP_DEFLATED) as z:
                z.writestr("reopened.json", review.dump(datum))
            changed = json.loads((d / "published.json").read_bytes())
            binding = changed["receipts"][zipname]
            binding["size_in_bytes"] = path.stat().st_size
            binding["digest"] = "sha256:" + sha256(path.read_bytes()).hexdigest()
            if basename == "original-migration-reopened":
                changed["external_reader"]["archive"] = binding
            (d / "published.json").write_bytes(review.dump(changed))
            try:
                review.check(qa, d, stage, receipt["run"], receipt["qa"], False)
            except (ValueError, RuntimeError, AssertionError):
                continue
            raise AssertionError(f"accepted deliberate edit {basename} {fields}")
    print(f"{len(checks)} real {stage} corruption controls rejected")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("qa_dir", type=Path)
    p.add_argument("projection", type=Path)
    a = p.parse_args()
    run(a.qa_dir.resolve(), a.projection.resolve())
