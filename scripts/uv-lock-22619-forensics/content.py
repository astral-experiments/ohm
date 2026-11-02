"""Preserve native compiler products by their original bytes, with deterministic compressed storage."""
import gzip
import hashlib
import json
import re
from pathlib import Path


def digest(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, why):
    if not condition:
        raise ValueError(why)


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, sort_keys=True, indent=2) + "\n")


def relative(root, candidate):
    require(candidate.is_file() and not candidate.is_symlink() and
            candidate.resolve(strict=True).is_relative_to(root.resolve(strict=True)), ("unscoped regular file", str(candidate)))
    return candidate.relative_to(root).as_posix()


class Store:
    def __init__(self, out, budget):
        self.out, self.budget = Path(out), budget
        self.items = {}
        self.total = 0
        self.difference_cache = {}

    def put(self, data):
        key = digest(data)
        if key in self.items:
            return self.items[key]
        name = Path("objects") / key[:2] / (key + ".gz")
        compressed = gzip.compress(data, compresslevel=1, mtime=0)
        require(self.total + len(compressed) <= self.budget, "product archive exceeds reserved admitted budget")
        path = self.out / name
        path.parent.mkdir(exist_ok=True, parents=True)
        with path.open("xb") as f:
            f.write(compressed)
        item = {"bytes": len(data), "sha256": key, "object": name.as_posix(), "compressed_sha256": digest(compressed)}
        self.items[key] = item
        self.total += len(compressed)
        return item

    def read(self, item):
        compressed = (self.out / item["object"]).read_bytes()
        require(digest(compressed) == item["compressed_sha256"], "stored compressed bytes changed")
        data = gzip.decompress(compressed)
        require(len(data) == item["bytes"] and digest(data) == item["sha256"], "stored native bytes changed")
        return data


def material(target, expected, observed, store, limit):
    rows, sides, errors = {}, {}, []
    target = Path(target)
    # Include newly declared workspace files as well as the independently registered 51.
    for name in sorted(set(expected) | set(observed)):
        try:
            p = target / name
            require(not Path(name).is_absolute() and ".." not in Path(name).parts and
                    relative(target, p) == name and name.endswith(".rmeta"), ("unexpected product", name))
            require(p.stat().st_size <= limit, "rmeta exceeds registered bound")
            rows[name] = store.put(p.read_bytes())
        except (OSError, ValueError) as error:
            errors.append([name, str(error)])
    for p in sorted(target.glob("debug/build/*/*/fingerprint/*.public-api-hash")):
        try:
            name = relative(target, p)
            require(p.stat().st_size < 512, ("oversize sidecar", name))
            data = p.read_bytes()
            item = store.put(data)
            sides[name] = {"raw": item}
            value = json.loads(data)
            require(isinstance(value, dict) and value["version"] == 1 and
                    re.fullmatch(r"[0-9a-f]{32}", value["value"]), ("sidecar schema", name))
            sides[name]["public_hash"] = value["value"]
        except (OSError, ValueError, KeyError, TypeError) as error:
            errors.append([str(p), str(error)])
    present = {k: [v["bytes"], v["sha256"]] for k, v in rows.items()}
    return {"rmeta": rows, "sidecars": sides, "errors": errors, "frozen_paths_equal": set(rows) == set(expected),
            "typed_declared_paths_equal": set(observed) == set(expected) if observed else None,
            "typed_declared_bytes_equal": present == observed if observed else None}


def distances(left, right):
    overlap = min(len(left), len(right))
    count = spans = 0
    first = last = None
    previous = -2
    for i, (a, b) in enumerate(zip(left, right)):
        if a == b:
            continue
        if first is None:
            first = i
        if i != previous + 1:
            spans += 1
        previous = last = i
        count += 1
    tail = abs(len(left) - len(right))
    if tail:
        if overlap != previous + 1:
            spans += 1
        if first is None:
            first = overlap
        last = max(len(left), len(right)) - 1
    return {"different_bytes": count + tail, "runs": spans, "first": first, "last": last}


def compare(left, right, store):
    a, b = left["rmeta"], right["rmeta"]
    products = {}
    for name in sorted(a.keys() | b.keys()):
        x, y = a.get(name), b.get(name)
        if not x or not y:
            products[name] = {"equal": False, "missing": "left" if not x else "right"}
            continue
        same = x["sha256"] == y["sha256"]
        row = {"equal": same, "sizes": [x["bytes"], y["bytes"]], "sha256": [x["sha256"], y["sha256"]]}
        if not same:
            pair = tuple(sorted((x["sha256"], y["sha256"])))
            if pair not in store.difference_cache:
                store.difference_cache[pair] = distances(store.read(x), store.read(y))
            row["difference"] = store.difference_cache[pair]
        prefix = str(Path(name).parent.parent / "fingerprint") + "/"
        keys = sorted(k for k in left["sidecars"].keys() | right["sidecars"].keys() if k.startswith(prefix))
        row["public_sidecars"] = {k: [left["sidecars"].get(k, {}).get("public_hash"),
                                      right["sidecars"].get(k, {}).get("public_hash")] for k in keys}
        products[name] = row
    side = lambda c: {n: v["raw"]["sha256"] for n, v in c["sidecars"].items()}
    ls, rs = side(left), side(right)
    changed = sorted(k for k in ls.keys() | rs.keys() if ls.get(k) != rs.get(k))
    return {"full_rmeta_byte_equality": len(products) == 51 and all(v["equal"] for v in products.values()),
            "both_have_all_51": left["frozen_paths_equal"] and right["frozen_paths_equal"],
            "sidecar_sets_equal": ls.keys() == rs.keys(), "sidecar_raw_differences": changed,
            "products": products}
