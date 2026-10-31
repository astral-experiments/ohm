"""Raw Cargo, ELF and storage formats shared with the independently qualified wrapped study."""

from collections import defaultdict
from pathlib import Path
import gzip, json, re, statistics, sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import signed_readers as h

J = h.read


def calibration(blobs):
    rows = []
    for k, (mode, rep) in enumerate(
        (("0", 1), ("1", 1), ("2", 1), ("2", 2), ("exec", 1), ("thread", 1), ("thread", 2))
    ):
        counts = [h.hw(J(blobs[f"calibration/{k}-{j}.json"])) for j in range(4)]
        delta = statistics.median(counts[1::2]) - statistics.median(counts[::2])
        needle = 160_000_000 * rep
        assert abs(delta / needle - 1) < 0.02
        rows.append([mode, rep, counts, delta, needle])
    assert rows == J(blobs["calibration/verified.json"])
    return rows


def codegen(args):
    d = {}
    for i, t in enumerate(args):
        if t == "-C":
            v = args[i + 1]
        elif t.startswith("-C") and len(t) > 2:
            v = t[2:]
        else:
            continue
        k, _, val = v.partition("=")
        d[k] = val
    name = d.get("opt-level", "0")
    debug = d.get("debug-assertions", "on" if name == "0" else "off")
    return name, debug, d.get("overflow-checks", debug)


def unit_profiles(doc):
    profiles = defaultdict(list)
    for u in doc["units"]:
        role = [
            u["pkg_id"],
            u["target"]["name"],
            u["target"]["kind"],
            u["mode"],
            u["features"],
            u.get("platform"),
        ]
        profiles[json.dumps(role, separators=(",", ":"))].append(u["profile"])
    assert len(doc["units"]) == 338 and all(0 <= i < 338 for i in doc["roots"])
    return {k: sorted(v, key=lambda p: json.dumps(p, sort_keys=True)) for k, v in profiles.items()}


def physical_role(a):
    crate = a[a.index("--crate-name") + 1]
    source = next((t for t in a if t.endswith(".rs") and not t.startswith("-")), None)
    emit = next(t for t in a if t.startswith("--emit="))
    if source is None:
        assert (
            re.fullmatch("autocfg_[0-9a-f]{16}_0", crate)
            and "/memoffset/" in a[a.index("--out-dir") + 1]
            and "-" in a
            and emit == "--emit=llvm-ir"
        )
        crate, source = "memoffset::autocfg", "<memoffset stdin>"
    features = sorted(
        a[j + 1] for j, t in enumerate(a) if t == "--cfg" and a[j + 1].startswith("feature=")
    )
    return json.dumps(
        [
            crate,
            source,
            emit,
            features,
            "--test" in a,
            any(x in ("-Zlink-only", "link-only") for x in a),
        ],
        separators=(",", ":"),
    )


def region(rows):
    allblocks = {}
    region = defaultdict(set)
    for name, dev, ino, mode, blocks, size, nlinks in rows:
        key = dev, ino
        assert allblocks.setdefault(key, blocks) == blocks
        parts = Path(name).parts
        location = "/".join(parts[:3]) if len(parts) >= 3 and parts[1] == "debug" else "other"
        region[key].add(location)
    allocated = defaultdict(int)
    for key, locations in region.items():
        allocated[
            next(iter(locations)) if len(locations) == 1 else "cross-area aliases, counted once"
        ] += (allblocks[key] * 512)
    return dict(allocated)


def source_images(bs, where, kept):
    root = J(bs[where + "/neutral-generator.json"])
    data = gzip.decompress(bs["retained-ELF/" + root["sha256"] + ".gz"])
    assert (
        h.sha(data) == root["sha256"]
        and data[:6] == b"\x7fELF\x02\x01"
        and data[18:20] == b">\x00"
        and len(data) == root["bytes"]
    )
    kept.add(root["sha256"])
    lib = J(bs[where + "/held-generator-rlib.json"])
    body = gzip.decompress(bs["bridge-rlibs/" + lib["sha256"] + ".gz"])
    assert h.sha(body) == lib["sha256"] and body[:8] == b"!<arch>\n" and len(body) == lib["bytes"]
    return root, lib


def linked(bs, pair, case, which):
    base = "linked-" + pair + "/opt" + str(which) + "/"
    docs = J(bs["linked-" + pair + "/input.json"])
    assert docs["hunk"] == "bfedc614b7670b8766576b64afd426c292f8c2ce" and docs["argv"] == [
        "cargo",
        "+ohm",
        "build",
        "-p",
        "ruff_unicode_names2",
        "--lib",
        "--locked",
        "--offline",
        "-j4",
        "--message-format=json",
    ]
    results = {}
    readers = {}
    bodies = []
    for label in (
        "cold",
        "neutral-unchanged",
        "historical-hunk",
        "first-unchanged",
        "traced-repeat",
        "independent-empty",
    ):
        w = base + label
        v = J(bs[w + "/build.json"])
        rows = [J(l) for l in gzip.decompress(bs[w + "/stdout.gz"]).splitlines()]
        assert rows[-1] == {"reason": "build-finished", "success": True} and not any(
            r.get("message", {}).get("level") == "error" for r in rows
        )
        assert v["reader"] == "Some(0)\nSome(0)\nSome(65)\nSome(9731)\n"
        assert v["dirty"] == [
            r["target"]["name"]
            for r in rows
            if r["reason"] == "compiler-artifact" and not r["fresh"]
        ]
        for n, k in v["generated"].items():
            assert h.sha(gzip.decompress(bs["generated/" + k + ".gz"])) == k
        bodies.append(v["generated"])
        for elf in (v["generator"], v["reader_elf"]):
            bits = gzip.decompress(bs["retained-ELF/" + elf["sha256"] + ".gz"])
            assert bits[:6] == b"\x7fELF\x02\x01" and h.sha(bits) == elf["sha256"]
        readers[label] = v["reader_elf"]["sha256"]
        rec = {
            "source": v["source"],
            "dirty": v["dirty"],
            "generator_elf": v["generator"]["sha256"],
        }
        if v["mode"] == "score":
            rec["instructions"] = h.hw(J(bs[w + "/whole.json"]))
            rec["allocated_B"] = h.disk(bs, w, v["storage"])
            rec["regions"] = region(J(gzip.decompress(bs[w + "/allocated-ledger.gz"])))
            assert sum(rec["regions"].values()) == rec["allocated_B"]
        else:
            assert any(p[1] == v["physical_generator"][0][1] for p in v["wild"])
            rec["rustcs"] = v["physical_rustcs"]
            rec["wild"] = len(v["wild"])
        results[label] = rec
    assert (
        readers["first-unchanged"] == readers["independent-empty"]
        and all(x == bodies[0] for x in bodies)
        and results["historical-hunk"]["source"] != results["cold"]["source"]
        and "unicode_names2_generator" in results["historical-hunk"]["dirty"]
    )
    return results
