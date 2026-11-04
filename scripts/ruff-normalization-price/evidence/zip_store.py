"""Reconstruct complete official ZIPs from one acquisition and standard zstd dictionary patches."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess as sp
import tempfile


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def checked(path, expected, size):
    if path.stat().st_size != size or sha(path) != expected:
        raise ValueError(f"file digest or length mismatch for {path}")


def write_once(path, data):
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"refusing to replace differing evidence at {path}")
    else:
        path.write_bytes(data)


def encode_json(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def materialize(store, row, out, base=None):
    relative = Path(row["payload"])
    assert not relative.is_absolute() and ".." not in relative.parts
    payload = store / relative
    checked(payload, row["encoded_sha256"], row["encoded_bytes"])
    with out.open("xb") as file:
        cmd = ["zstd", "-qdc", "--long=27"]
        if base is not None:
            cmd.append("--patch-from=" + str(base))
        sp.run([*cmd, payload], stdout=file, check=True)
    checked(out, row["sha256"], row["bytes"])


def pack(source, store, label):
    archive_dir = store / label
    archive_dir.mkdir(parents=True, exist_ok=True)
    official = (source / "official.json").read_bytes()
    assets = sorted(json.loads(official)["artifacts"], key=lambda a: a["id"])
    assert assets
    anchor_json = store / "anchor.json"
    with tempfile.TemporaryDirectory() as scratch:
        ref = Path(scratch) / "anchor.zip"
        if label == "pilot":
            anchor_id = assets[0]["id"]
            established = source / (str(anchor_id) + ".zip")
            checked(established, assets[0]["digest"].removeprefix("sha256:"), assets[0]["size_in_bytes"])
            shutil.copyfile(established, ref)
        else:
            anchor = json.loads(anchor_json.read_bytes())
            anchor_id = anchor["id"]
            materialize(store, anchor, ref)
        rows = []
        for a in assets:
            num = a["id"]
            old = source / (str(num) + ".zip")
            digest = a["digest"].removeprefix("sha256:")
            checked(old, digest, a["size_in_bytes"])
            payload = archive_dir / (str(num) + (".original.zst" if num == anchor_id else ".patch.zst"))
            with tempfile.NamedTemporaryFile() as temporary:
                cmd = ["zstd", "-q", "-10", "--long=26"]
                if num != anchor_id:
                    cmd.append("--patch-from=" + str(ref))
                sp.run([*cmd, "-c", old], stdout=temporary, check=True)
                temporary.seek(0)
                write_once(payload, temporary.read())
            row = dict(id=num, bytes=a["size_in_bytes"], sha256=digest, payload=str(payload.relative_to(store)),
                       encoded_sha256=sha(payload), encoded_bytes=payload.stat().st_size)
            if num == anchor_id:
                write_once(anchor_json, encode_json(row))
            rows.append(row)
    write_once(archive_dir/"official.json", official)
    write_once(archive_dir/"index.json", encode_json(rows))


def restore(store, label, destination):
    destination.mkdir(parents=True, exist_ok=True)
    directory = store / label
    official = (directory / "official.json").read_bytes()
    assets = {a["id"]: a for a in json.loads(official)["artifacts"]}
    rows = json.loads((directory / "index.json").read_bytes())
    assert len(rows) == len(assets) and {r["id"] for r in rows} == set(assets)
    anchor = json.loads((store/"anchor.json").read_bytes())
    with tempfile.TemporaryDirectory(dir=destination) as temp:
        base = Path(temp) / "anchor.zip"
        materialize(store, anchor, base)
        for row in rows:
            a = assets[row["id"]]
            assert a["digest"] == "sha256:" + row["sha256"] and a["size_in_bytes"] == row["bytes"]
            out = destination / (str(row["id"]) + ".zip")
            if out.exists():
                checked(out, row["sha256"], row["bytes"])
                continue
            pending = Path(temp) / (str(row["id"]) + ".pending")
            if row["id"] == anchor["id"]:
                assert row == anchor
                shutil.copyfile(base, pending)
            else:
                materialize(store, row, pending, base)
            checked(pending, row["sha256"], row["bytes"])
            pending.rename(out)
    write_once(destination / "official.json", official)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="action", required=True)
    a = sub.add_parser("pack")
    a.add_argument("source", type=Path)
    a.add_argument("store", type=Path)
    a.add_argument("label", choices=("pilot","confirmation"))
    b = sub.add_parser("restore")
    b.add_argument("store", type=Path)
    b.add_argument("label", choices=("pilot","confirmation"))
    b.add_argument("destination", type=Path)
    args = p.parse_args()
    if args.action == "pack":
        pack(args.source, args.store, args.label)
    else:
        restore(args.store, args.label, args.destination)


if __name__ == "__main__":
    main()
