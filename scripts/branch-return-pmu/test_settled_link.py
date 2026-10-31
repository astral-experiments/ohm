"""Reopen the three unscored native originals and exercise failure cases without running Cargo."""

import argparse
import copy
import gzip
import hashlib
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bindings as b
import link_diagnostic as diagnostic
import settled_link as s


def read(z, name):
    data = z.read(name)
    return json.loads(gzip.decompress(data) if name.endswith(".gz") else data)


def messages(z, name):
    return list(map(json.loads, gzip.decompress(z.read(name)).splitlines()))


def reject(fn, *args):
    try:
        fn(*args)
    except (ValueError, KeyError, FileNotFoundError):
        return
    raise AssertionError("accepted invalid evidence: " + fn.__name__)


def previous(z, arm):
    pre = "structural/" + arm + "/"
    load = lambda p: read(z, pre + p)
    cold = load("cold-A/native-execs.json.gz")
    rows = messages(z, pre + "unchanged-B/cargo.stdout.gz")
    actual = load("unchanged-B/native-execs.json.gz")
    chain = s.crop(cold, rows)
    visit = s.link(actual, chain)
    s.sole_bin(load("unchanged-B/roster.json.gz")["dirty"])
    counts = {
        k: len(load(k + "/roster.json.gz")["dirty"])
        for k in ("cold-A", "first-B", "return-A", "return-B", "unchanged-B")
    }
    assert list(counts.values()) == [375, 20, 20, 20, 1]
    for phase in ("first-B", "return-A", "return-B"):
        assert json.loads(z.read(pre + phase + "/visit.json"))["dirty_digest"] == s.SWITCH_DIRTY
    ledger = load("unchanged-B/path-inodes.json.gz")
    owner = Path(visit["output"]).relative_to(s.WORK).as_posix()
    leaf = Path(chain["zmij"]["out"]).parent.relative_to(s.WORK).as_posix()
    assert (
        ledger[owner] == ledger["target/debug/ruff"]
        and ledger[leaf + "/fingerprint/dep-lib-zmij"][-1] == 97
    )
    assert ledger[Path(visit["recipe"]).relative_to(s.WORK).as_posix()][-1] > 12
    assert load("unchanged-B/native.json.gz") == read(z, "clean/" + arm + "/B/native.json.gz")
    assert load("unchanged-B/watched-git-files.json") == load("return-B/watched-git-files.json")
    assert "failure.txt" in z.namelist() and not any(
        n.endswith("/clock.json") and n.startswith("measured/") for n in z.namelist()
    )
    return {
        "arm": arm,
        "counts": counts,
        "programs": visit,
        "cold": {k: v["pid"] for k, v in chain.items()},
    }


def exercise(z, cold, rows, actual, chain, raw, encoded, out):
    # Complete path and inode checks run on a tiny private tree. Only the stored trace,
    # original Make rules and translated record are evidence about the real hosted Ruff.
    original = str(s.WORK.parent)
    here = str(out)

    def remap(obj):
        return json.loads(json.dumps(obj).replace(original, here))

    def put(path, data):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    with (
        patch.object(s, "WORK", out / "work"),
        patch.object(s, "SDK", out / "home/.rustup/toolchains/ohm"),
    ):
        chain, cold, rows, actual = [remap(x) for x in (chain, cold, rows, actual)]
        leaf = chain["zmij"]
        recipe = Path(chain["ruff"]["out"]) / "ruff.rlink"
        content = b"rustlink\0\0\0\x01fixture"
        put(recipe, content)
        native = put(recipe.with_suffix(""), b"small synthetic output")
        returned = Path(chain["ruff"]["executable"])
        returned.parent.mkdir(parents=True, exist_ok=True)
        os.link(native, returned)
        for k in ("source", "rmeta", "rlib"):
            put(leaf[k], k.encode())
        put(Path(leaf["source"]).with_name("traits.rs"), b"traits")
        put(leaf["depfile"], raw.replace(original.encode(), here.encode()))
        e = put(Path(leaf["out"]).parent / "fingerprint/dep-lib-zmij", encoded)
        for phase in ("cold-A", "return-B", "unchanged-B"):
            folder = out / "proof" / phase
            folder.mkdir(parents=True)
            if phase == "cold-A":
                put(folder / "native-execs.json.gz", gzip.compress(json.dumps(cold).encode()))
            s.collect(folder, phase, cold if phase == "cold-A" else actual, rows, returned)
        before = out / "proof/return-B/settled-ruff.rlink.gz"
        assert gzip.decompress(before.read_bytes()) == content
        val = s.read(out / "proof/unchanged-B/settled-origin.json")
        assert (
            val["output_identity"] == val["returned_identity"]
            and val["emitter"]["files"]["encoded"]["sha256"] == hashlib.sha256(encoded).hexdigest()
        )

        git = out / "ruff" / ".git"
        ref = "refs/heads/ruff-b"
        put(git / "HEAD", ("ref: " + ref + "\n").encode())
        tip = put(git / ref, b"test\n")
        watch = {}
        for key in ("HEAD", ref):
            entry = s.physical(git / key)
            dev, ino, _, _, mt, ct = entry["identity"]
            watch[key] = {
                "device": dev,
                "inode": ino,
                "mtime_ns": mt,
                "ctime_ns": ct,
                "sha256": entry["sha256"],
            }
        for phase in ("return-B", "unchanged-B"):
            put(out / "proof" / phase / "watched-git-files.json", json.dumps(watch).encode())
        s.watched_after(out / "proof/unchanged-B", git.parent)
        mt = tip.stat().st_mtime_ns
        os.utime(tip, ns=(mt - 123456789, mt - 123456789))
        reject(s.watched_after, out / "proof/unchanged-B", git.parent)

        def changed(what, new, path):
            p = put(path, new)
            dest = out / "proof" / what
            dest.mkdir()
            reject(s.collect, dest, "unchanged-B", actual, rows, returned)
            return p

        changed("bad-recipe", b"rustlink\0\0\0\x02wrong", recipe)
        put(recipe, content)
        changed("bad-marker", encoded[:-1], e)


def main(args):
    sealed = diagnostic.spec(json.loads(diagnostic.FILE.read_bytes()))
    audit = json.loads(diagnostic.AUDIT.read_bytes())
    complete = diagnostic.archive(args.diagnostic, sealed)
    reject(diagnostic.spec, None)
    for key, value in (
        ("head", "0" * 40),
        ("run", 0),
        ("independent", "0" * 64),
        ("complete_sha256", "0" * 64),
    ):
        reject(diagnostic.spec, sealed | {key: value})
    reject(diagnostic.archive, args.diagnostic, sealed | {"complete_sha256": "0" * 64})
    with zipfile.ZipFile(args.diagnostic) as z:
        cold = read(z, "history/cold-A/native-execs.json.gz")
        rows = messages(z, "history/unchanged-B/cargo.stdout.gz")
        gen = read(z, "history/unchanged-B/native.json")
        chain = s.crop(cold, rows)
        actual = s.link(gen, chain)
        leaf = chain["zmij"]
        origin = read(z, "blocking-records/origins.json")[audit["chain"]["marker"]]
        assert (
            actual["linked_zmij"] == audit["chain"]["archive"]
            and actual["recipe"] == audit["chain"]["recipe"]
        )
        assert [chain[n]["pid"] for n in ("ruff", "serde_json", "zmij")] == audit["chain"][
            "full_pids"
        ]

        def object_(h):
            body = gzip.decompress(z.read("blocking-records/objects/" + h + ".gz"))
            assert hashlib.sha256(body).hexdigest() == h
            return body

        encoded = object_(origin["sha256"])
        raw = object_(s.one(origin["raw"], "zmij raw")["sha256"])
        s.marker(encoded)
        s.make_rules(raw, leaf)
        for i in range(97):
            for bit in range(8):
                damaged = bytearray(encoded)
                damaged[i] ^= 1 << bit
                reject(s.marker, bytes(damaged))
        reject(s.marker, encoded[:-1])
        reject(s.marker, encoded + b"\0")
        for old, replacement in (
            (b"/src/traits.rs", b"/src/foreign.rs"),
            (s.MARK.encode(), b"ignored"),
            (b".rlib: ", b".rlib-o: "),
        ):
            reject(s.make_rules, raw.replace(old, replacement, 1), leaf)
        reject(s.make_rules, raw + b"unexpected:\n", leaf)
        reject(s.sole_bin, [])
        reject(
            s.sole_bin, [{"name": "ruff", "id": s.BINARY, "kind": ["lib"], "crate_types": ["lib"]}]
        )
        for group, label, after in (
            ("rustcs", "mode", "full"),
            ("rustcs", "exe", "/other/rustc"),
            ("wild_processes", "exe", "/other/ld"),
        ):
            mutated = copy.deepcopy(gen)
            mutated[group][0][label] = after
            reject(s.link, mutated, chain)
        for group, token in (
            ("rustcs", actual["recipe"]),
            ("wild_processes", actual["output"]),
            ("wild_processes", actual["linked_zmij"]),
        ):
            mutated = copy.deepcopy(gen)
            v = mutated[group][0]["argv"]
            v[v.index(token)] = token + ".foreign"
            reject(s.link, mutated, chain)
        for group in ("rustcs", "wild_processes"):
            mutated = copy.deepcopy(gen)
            mutated[group].append(mutated[group][0])
            reject(s.link, mutated, chain)
        for crate, operand in (
            ("ruff", "serde_json=" + chain["serde_json"]["rlib"]),
            ("serde_json", "zmij=" + leaf["rmeta"]),
        ):
            changed = copy.deepcopy(cold)
            row = next(r for r in changed["rustcs"] if r["pid"] == chain[crate]["pid"])
            i = row["argv"].index(operand)
            row["argv"][i] += ".foreign"
            reject(s.crop, changed, rows)
        with tempfile.TemporaryDirectory() as tmp:
            exercise(z, cold, rows, gen, chain, raw, encoded, Path(tmp))
        print(
            json.dumps(
                {
                    "official": sealed,
                    "encoded": origin["sha256"],
                    "raw": origin["raw"][0]["sha256"],
                    "changed_runtime": complete["provider_results"]["valid"]["runtime"],
                    "actual": actual,
                    "single_bit_corruptions_rejected": 776,
                },
                sort_keys=True,
            )
        )
    expected = {
        "Foff": "09a83406fc1d9d011c573dc88784b3fdbca1edaa927b553f5d0356601baf1586",
        "Koff": "aeef5d5226815f3d5cd8a11210a1f2265ee1291214e5e885eddee1dc2c3cbb65",
    }
    for arm, p in zip(("Foff", "Koff"), args.off, strict=True):
        assert b.sha(p) == expected[arm]
        with zipfile.ZipFile(p) as z:
            print(json.dumps(previous(z, arm), sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diagnostic", type=Path, required=True)
    parser.add_argument("--off", type=Path, nargs=2, required=True, metavar=("F_OFF", "K_OFF"))
    main(parser.parse_args())
