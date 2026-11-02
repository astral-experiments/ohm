"""Join the signed -22 work-products table to each recorded donor by its complete filename."""

import gzip
import hashlib
import json
from pathlib import Path
import struct
import sys


def require(test, reason):
    if not test:
        raise ValueError(reason)


def recorded_products(data, physical):
    trailer = b"rust-end-file"
    require(
        data.startswith(b"RSIC\x0a\x00") and data.endswith(trailer),
        "wrong work-products format",
    )
    end = len(data) - len(trailer)
    cursor = 7 + data[6]
    require(
        cursor < end and data[7:cursor].endswith(b"(ohm-1.99.0-22)"),
        "different producer",
    )

    def take(size):
        nonlocal cursor
        require(size <= end - cursor, "truncated work-products table")
        result = data[cursor : cursor + size]
        cursor += size
        return result

    def length():
        result = 0
        for shift in range(0, 35, 7):
            byte = take(1)[0]
            result |= (byte & 127) << shift
            if byte < 128:
                require(
                    (shift == 0 or byte != 0) and result <= end,
                    "invalid encoded length",
                )
                return result
        raise ValueError("oversized encoded length")

    def name():
        value = take(length()).decode("utf-8")
        require(take(1) == b"\xc1", "invalid rustc string terminator")
        return value

    entries = {}
    for _ in range(length()):
        key = take(16)
        cgu = name()
        saved = {}
        for _ in range(length()):
            kind, saved_name = name(), name()
            require(
                kind not in saved
                and saved_name not in ("", ".", "..")
                and Path(saved_name).name == saved_name,
                "invalid saved filename or duplicate output kind",
            )
            # The compiler rejects a product when any declared saved file is missing.
            saved[kind] = dict(name=saved_name, physical=physical.get(saved_name))
        require(key.hex() not in entries, "duplicate work-product identity")
        entries[key.hex()] = dict(
            cgu=cgu,
            words=struct.unpack("<QQ", key),
            saved=saved,
            all_present=all(value["physical"] is not None for value in saved.values()),
        )
    require(cursor == end, "unconsumed work-products bytes")
    return entries


def read_history(out, lanes=("ordinary-observed", "diagnostic")):
    result = {}
    for lane in lanes:
        for phase, moment in (("B", "after"), ("A", "before"), ("A", "after")):
            record = json.loads(
                (out / lane / phase / ("green-inputs-" + moment + ".json")).read_bytes()
            )
            for session in record["sessions"]:
                files = {row["name"]: row for row in session["files"]}
                w = files["work-products.bin"]
                source = out / "green-originals" / (w["sha256"] + ".gz")
                with gzip.open(source, "rb") as f:
                    data = f.read((512 << 20) + 1)
                require(
                    len(data) == w["stat"][2]
                    and hashlib.sha256(data).hexdigest() == w["sha256"],
                    "incorrect work-product bytes",
                )
                result.setdefault(lane, {}).setdefault(phase + "-" + moment, {})[
                    session["path"]
                ] = recorded_products(data, files)
    return result


if __name__ == "__main__":
    json.dump(
        read_history(Path(sys.argv[1])),
        sys.stdout,
        sort_keys=True,
        separators=(",", ":"),
    )
    print()
