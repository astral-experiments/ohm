"""Reopen the unpaired historical-Ruff refusal and the kernel-built edit roster."""

from pathlib import Path
import gzip
import hashlib
import json
import re
import sys
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import external

DIGEST = "ca78e786bd6879745e04d7876ab3e20cad8d423d697047d4ea7cb517d8127156"
HASH = lambda b: hashlib.sha256(b).hexdigest()


def file_sha(p):
    with p.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def main():
    expected = json.loads((HERE / "receipt.json").read_bytes())
    included = HERE / "original-members.zip"
    assert file_sha(included) == expected["projection_sha256"]
    index = json.loads(gzip.decompress((HERE / "index.json.gz").read_bytes()))
    assert len(index) == expected["original_members"] and not any(n.startswith("P/") for n in index)
    if len(sys.argv) > 1:
        original = Path(sys.argv[1])
        assert len(sys.argv) == 2 and file_sha(original) == DIGEST
        with zipfile.ZipFile(original) as whole:
            assert sorted(index) == sorted(whole.namelist())
            for n, (size, h) in index.items():
                assert whole.getinfo(n).file_size == size
                with whole.open(n) as f:
                    assert hashlib.file_digest(f, "sha256").hexdigest() == h
    with zipfile.ZipFile(included) as z:

        def obj(n):
            return json.loads(z.read(n))

        assert all([len(z.read(n)), HASH(z.read(n))] == index[n] for n in z.namelist())
        w = obj("worker.json")
        assert (
            w["order"] == "CP"
            and w["phase"] == "pilot"
            and w["run"] == 41618130440
            and w["sha"] == "60d1cb9549b30396e7102048a17d700124b31cc4"
        )
        costs = {}
        for phase in ("buggy-cold", "buggy-idle1", "buggy-idle2", "edited", "fixed-idle1", "fixed-idle2"):
            s = obj("C/ordinary-" + phase + "/hardware.json")
            assert s["status"] == 0 and s["instructions"] > 0 and s["enabled"] == s["running"] > 0
            costs[phase] = s["instructions"]
        assert costs == expected["unpaired_C_instructions"]
        scope = obj("C/kit.json")
        exe = Path(scope["active"])
        (driver,) = [
            exe / k
            for k, v in scope["config"]["files"].items()
            if k.startswith("lib/librustc_driver-") and v == scope["driver"]
        ]
        roster = {}
        for n in z.namelist():
            if not re.fullmatch(r"C/kernel-edited-observer/trace\.\d+\.gz", n):
                continue
            body = gzip.decompress(z.read(n)).decode().splitlines()
            pid = int(n.split(".")[-2])
            argvs = []
            for l in body:
                if not (l.startswith('execve("') and l.endswith(") = 0")):
                    continue
                binary, data = l[8:].split('", [', 1)
                args, _ = json.JSONDecoder().raw_decode("[" + data)
                if (
                    binary not in {str(exe / "bin/rustc"), str(exe.parent / "rustup/toolchains/ohm/bin/rustc")}
                    or "--crate-name" not in args
                    or "--out-dir" not in args
                ):
                    continue
                assert any(
                    l.startswith("mmap(")
                    and "PROT_EXEC" in l
                    and "<" + str(driver) + ">" in l
                    and re.search(r" = 0x[0-9a-f]+$", l)
                    for l in body
                )
                argvs.append(args[args.index("--crate-name") + 1])
            if argvs:
                (v,) = argvs
                roster[pid] = v
        original_roster = obj("C/kernel-edited-observer/native-execs.json")["actual"]
        assert roster == {int(k): v["crate"] for k, v in original_roster.items()} and sorted(
            roster.values()
        ) == ["ruff_linter", "ty_python_semantic"]
        counts = {}
        for phase in ("local-cold-physical", "ordinary-buggy-cold", "kernel-buggy-cold", "native-buggy"):
            data = [json.loads(l) for l in z.read("C/" + phase + "/stdout").splitlines()]
            assert data[-1] == {"reason": "build-finished", "success": True}
            units = [r for r in data if r["reason"] == "compiler-artifact"]
            ext = [r for r in units if not r["package_id"].startswith("path+file://")]
            loc = [r for r in units if r["package_id"].startswith("path+file://")]
            absent = sorted(r["target"]["name"] for r in ext if not r["fresh"])
            counts[phase] = [len(units), len(ext), sum(not r["fresh"] for r in loc), absent]
        assert counts == expected["cold_units_external_dirty_local_dirty_external_names"]
        physical = json.loads(gzip.decompress(z.read("C/registry-prefix/external-members.json.gz")))
        hard = (HERE / "translated-native-marker.bin").read_bytes()
        assert len(hard) == 57 and hard[15:-5] == b"/dev/null/ohm-untracked-relink-inputs"
        matches = [
            k
            for k, v in physical.items()
            if k.endswith("/dep-lib-portable_atomic") and v[-2:] == [len(hard), HASH(hard)]
        ]
        (d,) = matches
        assert "/32f41f9e0ba0c147/" in d
        others = [
            v[-2:]
            for k, v in physical.items()
            if k != d and k.endswith(("/dep-lib-portable_atomic", "/dep-lib-salsa"))
        ]
        assert len(others) == 3 and len({tuple(x) for x in others}) == 1 and others[0][0] == 14
        from tempfile import TemporaryDirectory

        provenance = obj("prior-get-size-0.5.1-controls/verified.json")
        with TemporaryDirectory() as td:
            folder = Path(td)
            for name, entry in provenance.items():
                for f in ("stdout", "stderr", "command.json"):
                    (folder / f).write_bytes(
                        z.read("prior-get-size-0.5.1-controls/expansion-" + name + "/" + f)
                    )
                assert external.read_expansion(folder) == entry["result"]
        assert len({v["result"]["errors"][0][0] for v in provenance.values()}) == 3
        keys = {k.split("-", 1)[1] for k in provenance}
        assert len(keys) == 4 and all(
            provenance["P-" + k]["result"] == provenance["C-" + k]["result"] for k in keys
        )
        err = [json.loads(l) for l in z.read("C/invalid/stdout").splitlines()]
        (bad,) = [
            r["message"] for r in err if r["reason"] == "compiler-message" and r["message"]["level"] == "error"
        ]
        assert bad["code"]["code"] == "E0308" and any(
            s["is_primary"] and "OHM_INVALID_CHECK_SENTINEL" in str(s) for s in bad["spans"]
        )
    print(
        json.dumps(
            {
                "pairs": 0,
                "unpaired_C_edit": costs["edited"],
                "observed": sorted(roster.values()),
                "native_nonfresh": counts["native-buggy"][-1],
                "known_hard_marker": HASH(hard),
                "real_distinct_macro_verdicts": 3,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
