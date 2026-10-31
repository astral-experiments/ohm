"""Offline replay of original native events and prospective rejection controls."""
import copy
import gzip
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("RUNNER_TEMP", "/home/runner/work/_temp")
import bindings as b
import kernel_contact as contact
import kernel_events as events


def exercise(path, package):
    b.need(str(b.RUNNER) == "/home/runner/work/_temp", "use the original hosted logical paths")
    history, images, reader = events.readers(package)
    seal, audit, root = contact.spec()
    replay = contact.original(path, seal, audit)
    refused = []
    def reject(name, fn):
        try:
            fn()
        except (ValueError, KeyError, RuntimeError):
            refused.append(name)
        else:
            raise ValueError("accepted " + name)

    reject("unbound contact", lambda: contact.spec({**seal, "complete_sha256": None}))
    reject("wrong official head", lambda: contact.spec({**seal, "head": "0" * 40}))
    reject("missing second readback", lambda: contact.spec(root_raw=b"null"))
    reject("missing first readback", lambda: contact.spec(audit_raw=b"null"))
    reject("wrong contact boot", lambda: contact.spec({**seal, "boot": next(iter(contact.PREVIOUS.values()))}))
    for name, boot in {**contact.PREVIOUS, "cold": audit["boot"]}.items():
        reject(name, lambda: contact.fresh_boot(boot, audit))
    left = {"position": "01", "head": "1" * 40, "run": 2, "attempt": 1, "boot": "f5474f87-ab69-4dc5-aa34-b2ef7c247e6c",
            "kernel_contact": contact.enrollment(seal)}
    right = {**left, "position": "02", "boot": "b2534ae5-5f58-4366-87fd-e277a1c1225d"}
    contact.pair(left, right, audit)
    reject("same two worker boots", lambda: contact.pair(left, {**right, "boot": left["boot"]}, audit))
    reject("unmatched attempt", lambda: contact.pair(left, {**right, "attempt": 2}, audit))
    reject("unmatched cold positive in a pair", lambda: contact.pair(left, {**right, "kernel_contact": {}}, audit))
    with zipfile.ZipFile(path) as z, tempfile.NamedTemporaryFile(dir="/dev/shm") as tmp:
        def get(name):
            return json.loads(z.read(name))
        ledger = Path(tmp.name)
        with z.open("observed/cold-A/kernel.tsv.gz") as member, gzip.GzipFile(fileobj=member) as src:
            shutil.copyfileobj(src, tmp)
        tmp.flush()
        catalog = get("observed/catalog.json")
        enrolled, manifest = get("observed/arm.json"), get("sdk/manifest.json")
        driver = enrolled["files"][manifest["driver"]]
        env = enrolled["env"]
        events.check_source("Koff", env, enrolled, manifest, driver)
        reject("wrong active source role on invalid or success", lambda: events.check_source("Foff", env, enrolled, manifest, driver))
        reject("substituted driver", lambda: events.check_source("Koff", env, enrolled, manifest, ["f" * 64, *driver[1:]]))
        altered = copy.deepcopy(manifest)
        altered["roles"]["K"]["compiler"] = "f" * 40
        reject("spoofed compiler tree", lambda: events.check_source("Koff", env, enrolled, altered, driver))
        reject("untrusted dynamic search", lambda: events.check_source("Koff", {**env, "LD_LIBRARY_PATH": "/tmp"},
                                                                       enrolled, manifest, driver))
        closed = reader.read(ledger, expected_code=0, expected_sha=audit["positive_ledger_sha256"])
        command = get("enrollment.json")["command"]
        native = events.project(ledger, closed, catalog, "Koff", images, command)
        original = json.loads(gzip.decompress(z.read("observed/cold-A/native-execs.json.gz")))
        b.need(native == original, "different real source-qualified exec, argv, image or causal owner")
        gold = json.loads(events.GOLD.read_bytes())
        shape = events.phase_shape(native, "cold-A", history)
        b.need(gold["off"]["cold-A"] == shape, "new classifier disagrees with original physical cold")
        reject("actual success reinterpreted as Cargo 101", lambda: reader.read(ledger, expected_code=101))
        reject("different Cargo entrypoint", lambda: events.project(ledger, closed, catalog, "Koff", images, command[:-1]))
        reject("wrong source grade in real rustc argv", lambda: events.project(ledger, closed, catalog, "Kon", images, command))
        bad = copy.deepcopy(catalog)
        bad["cargo"]["identity"][2] += 100000000
        reject("unknown actual Cargo", lambda: events.project(ledger, closed, bad, "Koff", images, command))
        bad["cargo"] = catalog["cargo"]
        bad["rustc"]["identity"][0] = "f" * 64
        reject("same path/inode wrong file SHA", lambda: events.project(ledger, closed, bad, "Koff", images, command))
        modified = {**closed, "sha256": "f" * 64}
        reject("disconnected ancestry ledger", lambda: events.project(ledger, modified, catalog, "Koff", images, command))
    return {"original": seal["artifact"], "unscored": True, "boot": root["boot"], "historical_cold": shape,
            "reopened": replay["positive_ledger"], "all_classified_rows_identical": True, "refusals": refused}


if __name__ == "__main__":
    result = exercise(Path(sys.argv[1]), Path(sys.argv[2]).resolve(strict=True))
    if len(sys.argv) == 4:
        b.save(Path(sys.argv[3]), result)
    print("Reopened original source-qualified Koff cold with all physical/causal rows; rejected", len(result["refusals"]), "mutations.")
