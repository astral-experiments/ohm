"""Reopen the signed and research storage scans with their corresponding canonical outputs."""

import gzip
import hashlib
import json
import sys
from pathlib import Path
from zipfile import ZipFile


SOURCES = [
    ("23", "941425ee53b9993f2337cf7d6a8f031ac2420e86e708751a0d3208b2af852713"),
    ("24", "6df78409d5903049c988e3f4219f823e0e1e50f0d643ea4919c42b8238bb34ae"),
]


def reopen(path, release, digest):
    with path.open("rb") as f:
        assert hashlib.file_digest(f, "sha256").hexdigest() == digest
    with ZipFile(path) as z:

        def j(n):
            return json.loads(gzip.decompress(z.read(n)))

        stages = {}
        for tag in ("P-warm1", "P-empty-new", "C-warm1", "C-empty-new"):
            scan = j(tag + "-retained-generations.json.gz")
            receipt = j(tag + "-receipt.json.gz")
            paths = scan["canonical"]
            assert len(paths) == 50 and paths.keys() == receipt["published"].keys()
            assert len({tuple(v[:2]) for v in paths.values()}) == 50
            for k, (dev, ino, size, blocks, links) in paths.items():
                assert (
                    dev >= 0
                    and ino > 0
                    and links == 1
                    and blocks >= 0
                    and blocks % 512 == 0
                    and size > 0
                )
                assert size == receipt["output_sizes"][k]
            assert scan["other_same_image"] == receipt["same_bytes_elsewhere"] == []
            stages[tag] = {
                "canonical": paths,
                "full_output_SHA256": receipt["published"],
                "duplicate_complete_images_in_shared_build_and_target": [],
            }
        transient = {}
        for name in (
            "old",
            "edit",
            "warm1",
            "ordinary-repeat-old",
            "ordinary-repeat-edit",
            "empty-new",
        ):
            tag = "C-" + name
            row = j(tag + "-receipt.json.gz")
            transient[tag] = {
                "anonymous_receipt_bytes": row["metadata_bytes"],
                "sum_preexisting_output_allocated_bytes_held_during_separate_writes": row[
                    "held_allocated"
                ],
                "native_input_bytes_loaded": row["native_bytes_consumed"],
            }
        return {
            "release": release,
            "original_sha256": digest,
            "physical_output_scans": stages,
            "actual_source_storage": transient,
        }


if __name__ == "__main__":
    print(
        json.dumps(
            {
                rel: reopen(Path(path), rel, digest)
                for path, (rel, digest) in zip(sys.argv[1:], SOURCES, strict=True)
            },
            indent=2,
            sort_keys=True,
        )
    )
