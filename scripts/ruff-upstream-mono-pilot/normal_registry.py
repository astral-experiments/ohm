"""Verify the signed Ohm registry placement for these exact 274 Ruff dependency archives."""
import gzip
import hashlib
import json
import os
from pathlib import Path

EXPECTED = "1543d3b84184059d74c9a48c65375d85d16013a357fd4f92316544876d545be1"
# The signed -22 ordinary B transcript is artifact 13105414337, member
# plain-1/B/cargo.stdout.gz, SHA-256 1a80df21870c25c32b18cf759d80a982ba22017da8a48471b695030064285763.


def capture(rows, state, physical):
    products, files = [], []
    for row in rows:
        if row["reason"] != "compiler-artifact" or not row["package_id"].startswith("registry+"):
            continue
        for name in row["filenames"]:
            file = Path(name)
            if file.suffix != ".rlib":
                continue
            bucket, root = ("registries", "build") if "registries" in file.parts else ("workspaces", "target")
            relative = file.relative_to(state / root)
            if relative.parts.count(bucket) != 1:
                raise ValueError("ambiguous registry owner: " + name)
            products.append([row["package_id"], row["target"]["name"], row["target"]["kind"],
                             row["features"], row["profile"]["test"], bucket])
            record = {"path": str(file), "owner": bucket}
            if physical:
                with file.open("rb") as f:
                    stat = os.fstat(f.fileno())
                    if f.read(8) != b"!<arch>\n" or not file.resolve(strict=True).is_relative_to((state / root).resolve(strict=True)):
                        raise ValueError("not the physical Cargo archive: " + name)
                    record["identity"] = [stat.st_dev, stat.st_ino, stat.st_size]
            files.append(record)
    canonical = json.dumps(sorted(products), separators=(",", ":")).encode()
    return {"sha256": hashlib.sha256(canonical).hexdigest(), "products": len(products),
            "shared": sum(x[-1] == "registries" for x in products), "files": sorted(files, key=lambda r: r["path"])}


def require(receipt):
    if (receipt["sha256"], receipt["products"], receipt["shared"]) != (EXPECTED, 274, 239):
        raise ValueError("different placement of the signed Ruff registry dependencies")


def reopen(root):
    result = {}
    state = Path(json.loads((root / "environment.json").read_bytes())["CARGO_TARGET_DIR"]).parent
    for rev in "AB":
        for role in "PC":
            name = f"clean-{rev}-{role}"
            folder = root / name
            rows = [json.loads(l) for l in gzip.decompress((folder / "cargo.stdout.gz").read_bytes()).splitlines()]
            raw = capture(rows, state, False)
            observed = json.loads((folder / "registry.json").read_bytes())
            require(raw)
            for file in observed["files"]:
                dev, inode, size = file.pop("identity")
                if min(dev, inode, size) <= 0:
                    raise ValueError("missing original physical Cargo archive")
            if observed != raw:
                raise ValueError("placement differs from raw Cargo events")
            result[name] = raw["sha256"]
    return result
