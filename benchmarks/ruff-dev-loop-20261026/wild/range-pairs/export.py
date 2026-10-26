"""Export one complete native-validated historical cohort and its process records."""

import argparse
import collections
import csv
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
COLUMNS = [
    "mode",
    "block",
    "position",
    "edit",
    "arm",
    "units",
    "executables",
    "cargo",
    "rustc",
    "clang",
    "wild",
    "total",
    "source_sha256",
    "outputs_sha256",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["build", "test"])
    parser.add_argument("results", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    plan = json.loads((HERE / (args.mode + "-plan.json")).read_bytes())
    sources = json.loads((HERE / "source-oracles.json").read_bytes())[args.mode]
    native = json.loads((HERE / "native-oracles.json").read_bytes())[args.mode]
    directory = args.results / "ir-0"
    rows = [
        json.loads(line)
        for line in (directory / "observations.jsonl").read_text().splitlines()
    ]
    assert len(rows) == 3 * len(plan["blocks"]) == 36
    args.output.mkdir(exist_ok=True, parents=True)
    with (
        (args.output / (args.mode + ".csv")).open("w", newline="") as raw,
        (args.output / (args.mode + "-processes.jsonl")).open("w") as processes,
    ):
        writer = csv.DictWriter(raw, fieldnames=COLUMNS)
        writer.writeheader()
        for i, r in enumerate(rows):
            block, pos = divmod(i, 3)
            assert [r["block"], r["position"], r["arm"], r["edit"]] == [
                block,
                pos,
                plan["blocks"][block]["arms"][pos],
                plan["blocks"][block]["edit"],
            ]
            source = sources[r["edit"]]
            reference = native[r["edit"]]
            tag = directory / f"{block:02d}-{pos}"
            details = json.loads((tag / "processes.json").read_bytes())
            assert details["counts"] == r["counts"] and details["total"] == r["total"]
            assert (
                r["dirty"] == reference["dirty_names"]
                and r["units"] == reference["units"]
                and r["executables"] == len(reference["executables"])
            )
            own = json.loads((tag / "result.json").read_bytes())
            recorded = json.loads(
                (
                    args.results / ("native-control-" + r["edit"]) / "result.json"
                ).read_bytes()
            )
            assert (
                own["graph"] == recorded["graph"]
                and own["outputs"] == recorded["outputs"]
            )
            assert (
                r["outputs_sha256"]
                == hashlib.sha256(
                    json.dumps(
                        sorted((k, v["sha256"]) for k, v in own["outputs"].items()),
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest()
            )
            counts = collections.Counter()
            guest_counts = collections.Counter()
            for p in details["processes"]:
                counts[p["role"]] += p["ir"]
                guest_counts[p["role"]] += 1
                record = {
                    **p,
                    **{key: r[key] for key in ["block", "position", "edit", "arm"]},
                }
                record["image"] = Path(record["image"]).name
                if "driver" in record:
                    record["driver"] = Path(record["driver"]).name
                print(
                    json.dumps(record, separators=(",", ":"), sort_keys=True),
                    file=processes,
                )
            assert (
                counts == r["counts"]
                and guest_counts == reference["processes"]
                and sum(counts.values()) == r["total"]
            )
            output = {
                key: r[key]
                for key in [
                    "block",
                    "position",
                    "edit",
                    "arm",
                    "units",
                    "executables",
                    "total",
                    "outputs_sha256",
                ]
            }
            writer.writerow(
                {
                    "mode": args.mode,
                    **output,
                    **counts,
                    "source_sha256": source["sha256"],
                }
            )


if __name__ == "__main__":
    main()
