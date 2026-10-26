"""Export one complete native-validated historical cohort and its process records."""

import argparse
import collections
import contextlib
import csv
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["build", "test"])
    parser.add_argument("results", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--replicate", type=int, choices=[0, 1], default=0)
    parser.add_argument("--elapsed", action="store_true")
    args = parser.parse_args()
    prefix = (
        args.mode
        + ("-native" if args.elapsed else "")
        + ("-replication" if args.replicate else "")
    )
    plan_name = args.mode + (
        "-elapsed-replication-plan.json" if args.replicate else "-plan.json"
    )
    plan = json.loads((HERE / plan_name).read_bytes())
    sources = json.loads((HERE / "source-oracles.json").read_bytes())[args.mode]
    native = json.loads((HERE / "native-oracles.json").read_bytes())[args.mode]
    directory = args.results / (
        ("wall-" if args.elapsed else "ir-") + str(args.replicate)
    )
    rows = [
        json.loads(line)
        for line in (directory / "observations.jsonl").read_text().splitlines()
    ]
    assert len(rows) == 3 * len(plan["blocks"]) == 36
    args.output.mkdir(exist_ok=True, parents=True)
    measurements = (
        ["elapsed_ns", "child_cpu_seconds"]
        if args.elapsed
        else ["cargo", "rustc", "clang", "wild", "total"]
    )
    fields = [
        "mode",
        "block",
        "position",
        "edit",
        "arm",
        "units",
        "executables",
        *measurements,
        "source_sha256",
        "outputs_sha256",
    ]
    with (
        (args.output / (prefix + ".csv")).open("w", newline="") as raw,
        (
            contextlib.nullcontext()
            if args.elapsed
            else (args.output / (prefix + "-processes.jsonl")).open("w")
        ) as processes,
    ):
        writer = csv.DictWriter(raw, fieldnames=fields, lineterminator="\n")
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
            if args.elapsed:
                timing = json.loads((tag / "time.json").read_bytes())
                assert (
                    timing == {key: r[key] for key in measurements}
                    and timing["elapsed_ns"] > 0
                )
                writer.writerow(
                    {
                        "mode": args.mode,
                        "source_sha256": source["sha256"],
                        **{
                            k: r[k]
                            for k in fields
                            if k not in {"mode", "source_sha256"}
                        },
                    }
                )
                continue
            details = json.loads((tag / "processes.json").read_bytes())
            assert details["counts"] == r["counts"] and details["total"] == r["total"]
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
