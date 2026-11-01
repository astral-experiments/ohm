"""Additional custody at the natural patched compiler boundary; never replace its command."""

import hashlib
import gzip
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "diesel-stage2-repeat")]
import observe as prior
import jobserver
import products
from escrow import facts, pack
from identity import PATCHED_B, Q, need, sha, write


def projection(rows):
    alias = {}
    result = {}
    for path, row in sorted(rows.items()):
        r = {k: row[k] for k in ("type", "mode", "target", "size", "sha256") if k in row}
        if row["type"] == "file":
            r["first_name"] = alias.setdefault((row["dev"], row["ino"]), path)
            r["mtime_ns"] = row["mtime_ns"]
        result[path] = r
    raw = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    return {
        "paths": len(rows),
        "files": sum(v["type"] == "file" for v in rows.values()),
        "unique_files": len(alias),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def clone_matches(source, copy, manifest=None):
    original, _ = facts(source)
    candidate, _ = facts(copy)
    need(original.keys() == candidate.keys(), "clone path roster changed")
    for name, row in original.items():
        if row["type"] == "file" and candidate[name]["mtime_ns"] != row["mtime_ns"]:
            p = copy / name
            os.utime(p, ns=(p.stat().st_atime_ns, row["mtime_ns"]))
    final, _ = facts(copy)
    actual = projection(final)
    need(actual == projection(original), "clone content, mtime or hardlink classes differ")
    if manifest is not None:
        with manifest.open("xb") as f, gzip.GzipFile(fileobj=f, mode="wb", mtime=0) as out:
            out.write(json.dumps(final, sort_keys=True, separators=(",", ":")).encode())
    return actual


def emitted(argv, stderr):
    events = [json.loads(ln) for ln in stderr.splitlines() if ln.startswith(b"{")]
    rows = [(r["emit"], r["artifact"]) for r in events if r.get("$message_type") == "artifact"]
    for kind, expected in zip(("link", "metadata"), products.outputs(argv), strict=True):
        need(rows.count((kind, str(expected))) == 1, "compiler did not report producing " + kind)


def observe(phase, wrapper, pid, code, argv):
    patched = sha(Path.cwd() / Q) == PATCHED_B
    root = Path(os.environ["OHM_DIESEL_WORK"])
    dest = root / "reports/archives/original"
    if patched and phase == "running":
        write(dest / "native-jobserver-fds.json", jobserver.process_list(pid))
    prior.observe(phase, wrapper, pid, code, argv)
    if not patched:
        return
    cwd = Path.cwd().resolve()
    nums = jobserver.numbers(os.environ)
    if phase == "before":
        desc = jobserver.describe(nums)
        held, extra = jobserver.exchange(root, "offer", nums)
        need(not extra and jobserver.identity(held) == jobserver.identity(desc), "wrong inherited pipe transferred")
        need(os.getppid() == wrapper, "jobserver observer did not run as the real Eprintln companion's child")
        write(
            dest / "natural-jobserver.json",
            {
                "descriptors": desc,
                "held_same_open_files": held,
                "wrapper_fds": jobserver.process_list(wrapper),
                "wrapper_pid": wrapper,
                "observer_pid": os.getpid(),
            },
        )
        slot = root / "before-patched-B"
        need(slot.is_dir() and not slot.is_symlink(), "missing untouched B-start snapshot")
        normalized = clone_matches(cwd, slot)
        archive = dest / "before-B-source-and-A-session.tar.gz"
        full = pack(cwd, archive)
        entries = json.loads(archive.with_suffix(".inventory.json").read_bytes())["entries"]
        write(
            dest / "seed.json",
            {
                "cwd": str(cwd),
                "normalized": normalized,
                "complete_archive": full,
                "incoming_products": products.incoming(argv, cwd, entries),
            },
        )
    if phase == "after" and code == 0:
        natural = products.save(argv, cwd, dest / "natural-B")
        p = Path(os.environ["OHM_DIESEL_RECORD"]) / "events" / str(wrapper)
        event = json.loads((p / "after.json").read_bytes())
        expected = {
            Path(name).name: value
            for name, value in zip(
                natural["paths"], (natural["archive"], natural["standalone_metadata"]), strict=True
            )
        }
        need(event["outputs"] == expected and event["pid"] == pid, "not the observed natural B compiler's outputs")
        emitted(argv, (p / "rustc.stderr").read_bytes())
        write(dest / "natural-after-jobserver.json", jobserver.describe(nums))


if __name__ == "__main__":
    observe(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), sys.argv[5:])
