"""Reopen the native Apple process records, optionally cross-checking the hosted ZIPs."""
import argparse
import collections
import gzip
import hashlib
import json
from pathlib import Path
import tarfile
import zipfile

HERE = Path(__file__).resolve().parent


def sha(data):
    return hashlib.sha256(data).hexdigest()


def options(argv, flag):
    result = []
    for index, arg in enumerate(argv):
        if arg == flag:
            result.append(argv[index + 1])
        elif arg.startswith(flag) and len(arg) > len(flag):
            result.append(arg[len(flag):])
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archives", type=Path, help="directory of original ZIPs named by Actions artifact ID")
    args = parser.parse_args()
    for line in (HERE / "SHA256SUMS").read_text().splitlines():
        expected, name = line.split("  ", 1)
        assert sha((HERE / name).read_bytes()) == expected, name
    index = json.loads((HERE / "index.json").read_bytes())
    totals = {}
    with tarfile.open(HERE / "exec-traces.tar.xz", "r:xz") as tar:
        members = {m.name for m in tar.getmembers()}
        wanted = {e["packet_member"] for case in index for e in case["traces"]}
        assert members == wanted
        for case in index:
            subjects = collections.Counter()
            retained = collections.Counter()
            roles = set()
            original = None
            if args.archives:
                src = args.archives / (str(case["artifact"]) + ".zip")
                with src.open("rb") as source:
                    assert hashlib.file_digest(source, "sha256").hexdigest() == case["archive_sha256"]
                original = zipfile.ZipFile(src)
                assert {n for n in original.namelist() if n.endswith("/edit/exec.json.gz")} == {t["original_member"] for t in case["traces"]}
            for trace in case["traces"]:
                buf = tar.extractfile(trace["packet_member"]).read()
                assert sha(buf) == trace["original_native_events_sha256"]
                if original:
                    assert gzip.decompress(original.read(trace["original_member"])) == buf
                observed = collections.Counter()
                roles.add(trace["role"])
                for event in json.loads(buf):
                    argv = event["argv"]
                    if not event["path"].endswith("/native/bin/rustc") or "--crate-name" not in argv:
                        continue
                    if not any(v == "--emit" or v.startswith("--emit=") for v in argv):
                        continue
                    name = argv[argv.index("--crate-name") + 1]
                    if "link-only" in options(argv, "-Z"):
                        continue
                    if not any((v.startswith("crates/") or "/ruff/crates/" in v) and v.endswith(".rs") for v in argv):
                        continue
                    observed[name] += 1
                    retained[name] += any(v.startswith("incremental=") for v in options(argv, "-C"))
                assert set(case["required_crates"]) <= set(observed), (case["label"], observed)
                subjects.update(observed)
            if original:
                original.close()
            assert roles == {"P", "C"} and sum(retained.values()) == 0
            totals[case["label"]] = {"first_edits": len(case["traces"]), "local_rustcs": sum(subjects.values()),
                                     "incremental": sum(retained.values()), "subjects": dict(sorted(subjects.items()))}
    expected = json.loads((HERE / "counts.json").read_bytes())
    assert totals == expected
    for name, counts in totals.items():
        print(name, counts["first_edits"], "edits,", counts["local_rustcs"], "local rustcs,", counts["incremental"], "incremental")


if __name__ == "__main__":
    main()
