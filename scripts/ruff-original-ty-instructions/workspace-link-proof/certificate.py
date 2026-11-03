"""Compare one real full Wild invocation with a previous one, retaining per-field reasons to refuse."""

from pathlib import Path
from collections import defaultdict
import json, re
import bound_roster


def projections(data, spec):
    proof, args = bound_roster.receive(data, spec)
    rows = defaultdict(list)
    for line in data.splitlines():
        fields = line.split("\t")
        rows[fields[0]].append(fields[1:])

    def ints(tag):
        return [list(map(int, x)) for x in rows[tag]]

    predicted = ints("PROJECTED-GROUP")
    actual = ints("ACTUAL-GROUP")
    assert (
        predicted == actual
        and predicted
        and all(len(p) == 2 and p[0] > 0 and p[1] >= 0 for p in predicted)
    )
    (gr,) = rows["GROUPINPUT"]
    assert len(gr) == 5 and re.fullmatch(r"[0-9a-f]{64}", gr[4])
    assert len(actual) == int(gr[3]) and sum(p[1] for p in actual) == int(gr[0])
    (typed,) = rows["TYPED"]
    assert len(typed) == 7 and sum(p[0] for p in actual) == int(typed[0])
    (domain,) = rows["DOMAINS"]
    (admit,) = rows["ADMISSION"]
    assert len(admit) == 2 and admit[0] in ("true", "false")
    assert (
        len(rows["EMITTED"]) == len(rows["VERIFIED"]) == 1
        and not rows["FRESH-PUBLISH"]
        and not rows["ACCEPT"]
    )
    dev, ino, n, digest, path = rows["EMITTED"][0]
    assert (
        args[19] == path
        and int(dev) >= 0
        and int(ino) > 0
        and int(n) > 0
        and re.fullmatch(r"[a-f0-9]{64}", digest)
    )
    existing = None
    if rows["EXISTING"]:
        assert not rows["EXISTING-REFUSED"]
        (record,) = rows["EXISTING"]
        d, i, links, size, b3 = record
        assert (
            int(links) == 1
            and 1 << 20 <= int(size) <= 250 << 20
            and re.fullmatch(r"[a-f0-9]{64}", b3)
        )
        existing = {"dev": int(d), "ino": int(i), "bytes": int(size), "b3": b3}
    else:
        assert len(rows["EXISTING-REFUSED"]) == 1
    return {
        "proof_key": proof["key"],
        "parts": proof["parts"],
        "context": proof["context"],
        "bytes": proof["bytes"],
        "inputs": proof["inputs"],
        "requests": proof["requests"],
        "missed_searches": proof["denied_lookups"],
        "group_count": len(actual),
        "members": sum(p[0] for p in actual),
        "symbols": int(gr[0]),
        "groups_digest": gr[4],
        "typed_admitted": domain == ["true", "true", "1"]
        and admit[0] == "true"
        and re.fullmatch(r"[0-9a-f]{64}", admit[1]) is not None,
        "image_b3": admit[1],
        "existing": existing,
        "existing_refused": rows["EXISTING-REFUSED"],
        "emitted": {
            "dev": int(dev),
            "ino": int(ino),
            "bytes": int(n),
            "b3": digest,
            "path": path,
        },
    }


def classify(donor, current, signed_sha):
    reasons = []
    if not donor or not current:
        return ["missing-native-invocation"]
    if not donor.get("qualified") or not current.get("qualified"):
        return ["native-input-proof-refused"]
    if not donor["typed_admitted"] or not current["typed_admitted"]:
        reasons.append("typed-admission")
    if donor["proof_key"] != current["proof_key"]:
        changed = [
            "input-" + k
            for k in donor["parts"]
            if donor["parts"][k] != current["parts"][k]
        ]
        reasons += changed or ["inconsistent-input-summary"]
    if current["existing"] != {
        k: donor["emitted"][k] for k in ("dev", "ino", "bytes", "b3")
    }:
        reasons.append("prior-canonical-bytes-or-generation")
    if (
        donor["published_sha256"] != current["published_sha256"]
        or donor["emitted"]["b3"] != current["emitted"]["b3"]
    ):
        reasons.append("different-native-bytes")
    if current["published_sha256"] != signed_sha:
        reasons.append("different-independent-signed-clean-bytes")
    return reasons
