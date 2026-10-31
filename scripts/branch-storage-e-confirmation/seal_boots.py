"""Reopen already acquired integration originals in place; publish no partial exclusion set."""

from pathlib import Path
import argparse
import hashlib
import json
import sys
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import confirm_binding as r


def body(p):
    return json.loads(p.read_bytes())


def sha(p):
    with p.open("rb") as h:
        return hashlib.file_digest(h, "sha256").hexdigest()


def witness(pos, results, store):
    raw = results / f"receipt-{pos}.json"
    v = body(raw)
    a = v["archive"]
    check = r.check
    check(
        (v["run"], v["head"], v["job"], v["job_name"], v["position"], v["conclusion"])
        == (
            r.OLD_INTEGRATION,
            r.OLD_HEAD,
            r.FJOBS[pos],
            "Confirm F whole-Cargo integration " + pos,
            pos,
            "success",
        ),
        "different completed native integration receipt",
    )
    p = store / f"{r.OLD_INTEGRATION}-{a['id']}.zip"
    check(
        p.is_file()
        and not p.is_symlink()
        and 0 < p.stat().st_size == a["size_in_bytes"] < 2 << 30
        and a["digest"] == "sha256:" + sha(p),
        "missing or changed official native ZIP",
    )
    with zipfile.ZipFile(p) as z:
        check(
            len(z.namelist()) == len(set(z.namelist())) and "failure.txt" not in z.NameToInfo,
            "invalid prior terminal",
        )
        for n in ("enrollment.json", "complete.json", "host.json"):
            check(0 < z.getinfo(n).file_size < 1 << 20, "unbounded native boot identity")
        original = z.read("enrollment.json")
        e = json.loads(original)
        end = json.loads(z.read("complete.json"))
        host = json.loads(z.read("host.json"))
    check(
        (e["run"], e["head"], e["attempt"], e["position"]) == (v["run"], v["head"], 1, pos)
        and end["qualified"]
        and end["head"] == v["head"]
        and end["position"] == pos
        and host["raw_system"]["/proc/sys/kernel/random/boot_id"]
        == e["boot"]
        == v["boot"]
        == end["boot"],
        "enrollment, terminal and actual kernel boot differ",
    )
    check(
        v["worker_sha256"] == sha(results / f"worker-{pos}.json")
        and v["empty_native_sha256"] == sha(results / f"empty-native-{pos}.json"),
        "independent native controls unavailable",
    )
    return {
        "job": v["job"],
        "head": v["head"],
        "boot": v["boot"],
        "id": a["id"],
        "name": a["name"],
        "size": a["size_in_bytes"],
        "sha256": a["digest"][7:],
        "enrollment_sha256": hashlib.sha256(original).hexdigest(),
        "worker_receipt_sha256": sha(raw),
    }


def make(results, store):
    rows = {p: witness(p, results, store) for p in r.POS}
    old = {
        "run": r.OLD_INTEGRATION,
        "head": r.OLD_HEAD,
        "attempt": 1,
        "branch": r.OLD_REF,
        "hosts": rows,
    }
    boots = r.validated_prior(
        body(r.INPUTS / "previous-boots.json"), old, body(r.INPUTS / "pilots.json")
    )
    return old, sorted(boots)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("originals", type=Path)
    p.add_argument("readbacks", type=Path)
    p.add_argument("out", type=Path)
    args = p.parse_args()
    old, boots = make(args.readbacks, args.originals)
    args.out.mkdir(exist_ok=False)
    for file, data in [("integration-boots.json", old), ("excluded-boots.json", boots)]:
        # Only create two new files in a previously nonexistent directory after all 12 physical witnesses agree.
        with (args.out / file).open("x") as dst:
            json.dump(data, dst, sort_keys=True, indent=2)
            dst.write("\n")


if __name__ == "__main__":
    main()
