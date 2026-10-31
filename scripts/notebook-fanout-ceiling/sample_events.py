"""Export perf's resolved instruction frames and sample identities without repeating symbol strings."""

import gzip
import json
import os

symbols = {}
stream = None
count = 0


def emit(row):
    stream.write(json.dumps(row, separators=(",", ":")) + "\n")


def symbol(dso, name):
    key = (dso, name)
    if key not in symbols:
        index = len(symbols)
        symbols[key] = index
        emit(["symbol", index, dso, name])
    return symbols[key]


def trace_begin():
    global stream
    stream = gzip.open(os.environ["OHM_SAMPLE_ROWS"], "xt", compresslevel=1)


def process_event(event):
    global count
    if event["ev_name"] != "instructions:u":
        raise ValueError(("unexpected sampling event", event["ev_name"]))
    s = event["sample"]
    chain = [
        [f["ip"], symbol(f.get("dso", ""), f.get("sym", {}).get("name", ""))]
        for f in event["callchain"]
    ]
    emit(
        [
            "sample",
            s["pid"],
            s["tid"],
            s["time"],
            s["ip"],
            s["period"],
            symbol(event.get("dso", ""), event.get("symbol", "")),
            chain,
        ]
    )
    count += 1


def trace_end():
    emit(["done", count, len(symbols)])
    stream.close()
