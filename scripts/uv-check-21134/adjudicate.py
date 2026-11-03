"""Reopen every native result from both hardware runs before reading either set of prices."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common
import custody
import media
import oracle
import score


def signed_sdk(role, path, g_lock):
    f_lock = media.FLOCK
    rows = (f_lock["raw"]["F"] if role == "F" else g_lock["G"]["raw"]) | {
        "bin/cargo": f_lock["signed_cargo_row"]
    }
    expected = f_lock["effective_hashes"]["F"] if role == "F" else g_lock["G_effective"]
    entries = list(path.rglob("*"))
    common.require(not any(p.is_symlink() for p in entries), "unexpected SDK symlink")
    actual = {str(p.relative_to(path)): common.sha(p) for p in entries if p.is_file()}
    common.require(actual == {name: row["sha256"] for name, row in rows.items()}
                   and common.canonical(actual) == expected, "offline SDK differs from the measured role")
    return path.resolve()


def reopen_visit(files, where, role, compiler, store, dec, reader, scratch):
    # These are the only service members opened in this stage. None contains a timing or counter.
    opening = where == f"panel/opening-{role}"
    observed = files.get(where + "/native-observed.json")
    warm = files.get(where + "/first-B/products.json")
    fresh = files.get(where + ("/fresh-B" if opening else "/independent-cold-B") + "/products.json")
    record = observed["typed" if opening else "full_typed"]
    common.require(observed["role"] == role, "observed role")
    for name, a in warm["rmeta"].items():
        b = fresh["rmeta"][name]
        if a == b:
            continue
        for size, digest in (a, b):
            common.require(re.fullmatch("[a-f0-9]{64}", digest) and 0 < size <= 64 << 20, "native image identity")
            dest = store / (digest + ".gz")
            if not dest.exists():
                compressed = files.raw("blobs/" + dest.name)
                data = gzip.decompress(compressed)
                common.require(len(data) == size and hashlib.sha256(data).hexdigest() == digest, "raw native image")
                dest.write_bytes(compressed)
    oracle.RUSTC = compiler / "bin/rustc"
    oracle.ENV = dict(common.ENV, LD_LIBRARY_PATH=str(compiler / "lib"))
    exact = oracle.compare_native(warm, fresh, store, dec, reader, scratch, role)
    score.check_native(exact, warm, fresh, role)
    # Bind the new reversible byte proofs to the original worker's nine typed checks and actual rustc headers.
    physical = dict(exact, nonliteral={k: dict(row, exact_wire=None) for k, row in exact["nonliteral"].items()})
    common.require(json.loads(json.dumps(physical)) == record, "offline decoding differs from the observed native fields")
    return exact


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk-F", dest="sdk_f", required=True, type=Path)
    parser.add_argument("--sdk-G", dest="sdk_g", required=True, type=Path)
    parser.add_argument("--head", required=True)
    parser.add_argument("--proof-dir", required=True, type=Path)
    parser.add_argument("--native-only", action="store_true")
    parser.add_argument("folders", type=Path, nargs="+")
    args = parser.parse_args()
    common.require(1 <= len(args.folders) <= 2 and (len(args.folders) == 2 or args.native_only),
                   "unblinding requires both original hardware runs")
    lock_file = common.HERE / "G-qualified-lock.json"
    g_lock = common.read(lock_file)
    media.authorize(g_lock)
    sdks = {r: signed_sdk(r, path, g_lock) for r, path in (("F", args.sdk_f), ("G", args.sdk_g))}
    expected_series = ["marginal.initial", "marginal.repeat"]
    receipts = [custody.check(folder, args.head, common.sha(lock_file), series)
                for folder, series in zip(args.folders, expected_series)]
    if len(receipts) == 2:
        a, b = receipts
        common.require(a["boot"] != b["boot"] and a["runner_id"] != b["runner_id"]
                       and a["run"] != b["run"] and a["head"] == b["head"] == args.head, "hardware placements")
    args.proof_dir.mkdir()
    sources = {p.name: common.sha(p) for p in sorted(common.HERE.glob("*.py"))}
    common.save(args.proof_dir / "enrolled.json", {"head": args.head, "receipts": receipts, "readers": sources})
    archives = [score.Files(folder / "original.zip") for folder in args.folders]
    proofs = [{} for _ in archives]
    with tempfile.TemporaryDirectory() as tmp:
        temp = Path(tmp)
        store = temp / "blobs"
        store.mkdir()
        dec, reader = oracle.toolkit(temp / "native-kit", store)
        # Finish all F inputs on both hosts before beginning the G inputs.
        for role in ("F", "G"):
            visits = [f"panel/opening-{role}"] + [f"panel/{i}-{role}" for i in range(1, 9)]
            for archive, proof, receipt in zip(archives, proofs, receipts, strict=True):
                for visit in visits:
                    exact = reopen_visit(archive, visit, role, sdks[role], store, dec, reader, temp / "headers")
                    proof[visit] = exact
                    common.save(args.proof_dir / str(receipt["run"]) / (visit + ".json"), exact)
    common.save(args.proof_dir / "native-complete.json",
                {str(row["run"]): common.canonical(p) for row, p in zip(receipts, proofs, strict=True)})
    if args.native_only:
        print("All native comparisons passed", [len(p) for p in proofs])
        return
    results = [score.replay(folder / "original.zip", proof) for folder, proof in zip(args.folders, proofs, strict=True)]
    common.save(args.proof_dir / "replication.json", {"runs": results, "replicated": score.jointly(*results)})
    print(args.proof_dir / "replication.json")


if __name__ == "__main__":
    main()
