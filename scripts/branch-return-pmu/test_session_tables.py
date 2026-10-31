"""Exercise the structural owner check, including wrong producers and corrupt zlib streams."""

import argparse
import hashlib
import json
import os
import shutil
import sys
import tarfile
import tempfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from session_tables import finalized, owner, raw_header

VERSION = "1.99.0-dev"
SESSION = "s-123-abc-987"
HEADER = raw_header(VERSION)
PAYLOAD = HEADER + b"owned table" * 120_000
PAYLOAD_SIZE = len(PAYLOAD)
GRAPH = "ohm-packed-dep-graph.bin"
QUERY = "ohm-packed-query-cache.bin"


def encoded(tag=b"G", version=1, aliases=3, size=PAYLOAD_SIZE, prefix=b"s-123-abc", data=PAYLOAD):
    return zlib.compress(
        bytes([version]) + tag + bytes([aliases]) + size.to_bytes(8, "little") + prefix + b"\0" + data,
        level=1,
    )


def rejects(name, action):
    try:
        action()
    except (OSError, ValueError, zlib.error):
        return name
    raise AssertionError("accepted " + name)


def controls():
    blocked = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        work = root / "work"
        base = work / "target/inc"
        producer = base / "branch_tables-0000000000001"
        s = producer / SESSION
        s.mkdir(parents=True)
        (s / "work-products.bin").write_bytes(HEADER + b"native work-product index")
        (s / "0123456789abcdef.o").write_bytes(b"one native work product")
        (s / "dep-graph.bin").write_bytes(PAYLOAD)
        (s / "query-cache.bin").write_bytes(PAYLOAD)
        os.link(s / "dep-graph.bin", s / "ohm-build-dep-graph.bin")
        assert finalized(s, VERSION)["representation"] == "raw"
        (s / "ohm-build-dep-graph.bin").unlink()
        (s / "ohm-build-dep-graph.bin").write_bytes(PAYLOAD)
        blocked.append(rejects("foreign raw stage alias", lambda: finalized(s, VERSION)))
        for name in ("ohm-build-dep-graph.bin", "dep-graph.bin", "query-cache.bin"):
            (s / name).unlink()
        (s / GRAPH).write_bytes(encoded())
        blocked.append(rejects("missing packed partner", lambda: finalized(s, VERSION)))
        (s / QUERY).write_bytes(encoded(tag=b"Q"))
        valid = finalized(s, VERSION)
        assert valid["representation"] == "packed" and valid["graph_bytes"] == len(PAYLOAD)
        (s / "dep-graph.bin").write_bytes(PAYLOAD)
        blocked.append(rejects("hybrid packed and raw", lambda: finalized(s, VERSION)))
        (s / "dep-graph.bin").unlink()
        mutations = {
            "wrong table type": encoded(tag=b"Q"),
            "unknown stream version": encoded(version=2),
            "missing primary alias": encoded(aliases=2),
            "unknown aliases": encoded(aliases=9),
            "wrong session prefix": encoded(prefix=b"s-999-other"),
            "wrong source length": encoded(size=len(PAYLOAD) + 1),
            "wrong raw header": encoded(data=b"XXXX" + PAYLOAD[4:]),
            "foreign compiler build": encoded(data=PAYLOAD.replace(VERSION.encode(), b"1.98.0-dev", 1)),
            "truncated zlib": encoded()[:-1],
            "damaged zlib checksum": encoded()[:-1] + bytes([encoded()[-1] ^ 1]),
            "two streams": encoded() + encoded(),
            "trailing garbage": encoded() + b"x",
        }
        for label, body in mutations.items():
            (s / GRAPH).write_bytes(body)
            blocked.append(rejects(label, lambda: finalized(s, VERSION)))
        (s / GRAPH).write_bytes(encoded())
        obj = s / "0123456789abcdef.o"
        obj.unlink()
        blocked.append(rejects("missing physical native work product", lambda: finalized(s, VERSION)))
        obj.symlink_to(s / GRAPH)
        blocked.append(rejects("symlinked native work product", lambda: finalized(s, VERSION)))
        obj.unlink()
        obj.write_bytes(b"one native work product")
        products = s / "work-products.bin"
        products.unlink()
        blocked.append(rejects("missing work products", lambda: finalized(s, VERSION)))
        products.write_bytes(raw_header("1.98.0-dev") + b"old index")
        blocked.append(rejects("foreign work-product producer", lambda: finalized(s, VERSION)))
        products.unlink()
        products.symlink_to(s / GRAPH)
        blocked.append(rejects("symlinked work products", lambda: finalized(s, VERSION)))

        # The input argv names an emitted rmeta. Another session with the same apparent crate
        # or the same file contents cannot satisfy the physical ownership check.
        out = work / "target/out"
        out.mkdir()
        product = out / "libbranch_tables-a.rmeta"
        product.write_bytes(b"emitted metadata")
        row = {
            "pid": 1,
            "crate": "branch_tables",
            "argv": [
                "--crate-type",
                "lib",
                "--out-dir",
                str(out),
                "-C",
                "extra-filename=-a",
            ],
        }
        os.link(product, s / "metadata.rmeta")
        other = base / "branch_tables-0000000000002" / SESSION
        other.mkdir(parents=True)
        shutil.copyfile(product, other / "metadata.rmeta")
        assert owner(row, base, work)[0] == producer
        (other / "metadata.rmeta").unlink()
        os.link(product, other / "metadata.rmeta")
        blocked.append(rejects("ambiguous rmeta producer", lambda: owner(row, base, work)))
        (s / "metadata.rmeta").unlink()
        (other / "metadata.rmeta").unlink()
        shutil.copyfile(product, other / "metadata.rmeta")
        blocked.append(rejects("byte-identical foreign producer", lambda: owner(row, base, work)))
    return blocked


def native(directory):
    """Reopen the small physically retained tables from the two actual qualified compilers."""
    summary = {}
    for role in ("F", "K"):
        for phase in ("cold", "return"):
            source = directory / (role + "-" + phase)
            captured = json.loads((source / "products.json").read_bytes())
            (lib,) = [r for r in captured["rows"] if r["proof"]["crate_type"] == "lib"]
            expected = {r["path"]: {k: v for k, v in r.items() if k != "path"} for r in lib["sessions"]}
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                with tarfile.open(source / "physical-tables.tar.gz", "r:gz") as t:
                    for m in t:
                        p = Path(m.name)
                        assert (
                            len(p.parts) == 2
                            and p.parts[0] in expected
                            and m.isreg()
                            and 0 < m.size <= 8 << 20
                        )
                        out = root / p
                        out.parent.mkdir(exist_ok=True)
                        with t.extractfile(m) as f, out.open("xb") as sink:
                            shutil.copyfileobj(f, sink)
                for s, recorded in expected.items():
                    assert finalized(root / s, VERSION) == recorded
                rejections = []
                if phase == "return":
                    one, two = [root / n for n in expected]
                    graph = one / GRAPH
                    data = graph.read_bytes()
                    graph.write_bytes((two / GRAPH).read_bytes())
                    rejections.append(
                        rejects("other real session graph", lambda one=one: finalized(one, VERSION))
                    )
                    graph.write_bytes((one / QUERY).read_bytes())
                    rejections.append(
                        rejects(
                            "actual query in graph slot",
                            lambda one=one: finalized(one, VERSION),
                        )
                    )
                    graph.write_bytes(data[:-1])
                    rejections.append(
                        rejects(
                            "truncated actual zlib trailer",
                            lambda one=one: finalized(one, VERSION),
                        )
                    )
                    graph.write_bytes(data + b"x")
                    rejections.append(
                        rejects(
                            "trailing actual zlib bytes",
                            lambda one=one: finalized(one, VERSION),
                        )
                    )
                    graph.write_bytes(data)
                    assert finalized(one, VERSION) == expected[one.name]
                summary[role + "-" + phase] = {
                    "tables": sum(len(v["tables"]) for v in expected.values()),
                    "refused": rejections,
                    "sha256": hashlib.sha256(
                        (source / "physical-tables.tar.gz").read_bytes()
                    ).hexdigest(),
                }
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native", type=Path)
    args = parser.parse_args()
    result = {"rejected": controls()}
    if args.native:
        result["native"] = native(args.native)
    print(json.dumps(result, sort_keys=True, indent=2))
