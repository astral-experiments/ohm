"""Recount the four original first edits. Run beside origin.json and warm.tar.xz using Python 3.11+."""
from collections import Counter
from contextlib import contextmanager
from fractions import Fraction
from hashlib import file_digest
import json
from pathlib import Path
import runpy
import shlex
import shutil
import tarfile
import tempfile


def sha(p):
    with p.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def read(p):
    return json.loads(p.read_bytes())


def recount(folder, label, parse):
    base = folder / label
    original, reduced = read(base / "opening.json"), read(base / "reduced.json")
    assert sha(base / "opening.json") == reduced["raw_opening"] and original["qualifier"] == sha(base / "qa/qualification.json")
    quality = read(base / "qa/qualification.json")
    assert quality["admitted"] and quality["terminal_compiled"] and not quality["problems"]
    assert not any(quality["first_b_vs_cold_b"]["different_header_counts"].values())
    assert original["protocol"] == sha(folder / "protocol.json") == reduced["protocol"] and original["rustc"] == reduced["rustc"] == quality["source"]["commit"]
    actual = read(base / "native-argv.json")
    assert sha(base / "native-argv.json") == original["native_argv"]
    assert Counter(map(tuple, actual)) == Counter(map(tuple, read(base / "guest-argv.json")))
    assert len(actual) == 8
    counts, commands = {}, {}
    for argv in actual:
        unit = argv[argv.index("--crate-name") + 1]
        rec = original["counts"][unit]
        raw = base / "raw" / unit
        assert sha(raw) == rec["sha256"] == reduced["measurements"][unit]["raw_sha256"]
        with raw.open() as stream:
            header = {}
            for line in stream:
                key, sep, val = line.partition(":")
                if sep and key in ("cmd", "pid"):
                    header[key] = val.strip()
                if len(header) == 2:
                    break
        assert header["cmd"] == rec["argv"] == " ".join(argv) and int(header["pid"]) == rec["pid"]
        metadata, flat, *_ = parse(raw)
        assert unit not in counts and metadata["Ir"] == sum(flat.values()) == rec["Ir"] == reduced["measurements"][unit]["Ir"]
        counts[unit], commands[unit] = metadata["Ir"], argv
    assert set(counts) == set(original["counts"]) and sum(counts.values()) == original["whole_rustc_Ir"] == reduced["sum"]
    assert counts["uv_client"] == original["terminal_Ir"] and len(counts) == 8
    for stage in ["cold-a", "unchanged-a", "first-b", "unchanged-b", "cold-b-samepath"]:
        src = base / "qa" / (stage + ".products.json")
        products = read(src)
        assert sha(src) == reduced["native_products"][stage]["original"] and products["cargo_artifacts"] == 486
        assert len(products["metadata"]) == 37
        if stage.startswith("unchanged-"):
            assert not products["dirty"]
        if stage == "first-b":
            assert {k for k, typ in products["dirty"] if typ == ["lib"]} == set(counts)
    for stage, state in [("linked-a","A"), ("native-warm-b","B"), ("native-cold-b","B")]:
        witness = read(base / "qa" / (stage + ".witness.json"))
        assert witness == quality["behaviors"][stage] and witness["source"] == state
    if label.startswith("candidate"):
        gate = read(base / "six/approved.json")
        assert sha(base / "six/approved.json") == reduced["six"]["sha256"]
        assert sha(base / "six/native-ready.json") == gate["native_ready"]
        assert gate["admitted"] and gate["all_warm_and_cold_match"] and gate["six_distinct_native_impls"] == 6
        assert len({a for a, b in gate["selected_slots"].values() if a == b}) == 6
        for ref in gate["verification_inputs"]:
            assert sha(folder / "six-inputs" / ref["sha256"]) == ref["sha256"]
    return counts, commands


@contextmanager
def unpack(directory, archive_name, origin_name):
    raw = directory / archive_name
    origin = read(directory / origin_name)
    assert sha(raw) == origin["archive"]["sha256"] and raw.stat().st_size == origin["archive"]["bytes"]
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        seen = set()
        with tarfile.open(raw) as tar:
            for entry in tar:
                path = Path(entry.name)
                assert entry.isfile() and not path.is_absolute() and ".." not in path.parts
                assert entry.name in origin["files"] and entry.name not in seen
                seen.add(entry.name)
                dest = folder / path
                dest.parent.mkdir(parents=True, exist_ok=True)
                with dest.open("xb") as output:
                    shutil.copyfileobj(tar.extractfile(entry), output)
                assert sha(dest) == origin["files"][entry.name]
        assert seen == set(origin["files"])
        library = folder / "tools/graph.py"
        assert sha(library) == "8acb671d5ac900cdd4bef3f554b49f84f90f45898870be879d7d78b6d3ed4d2d"
        yield folder, runpy.run_path(str(library))["read"]


def verify(directory):
    with unpack(directory, "warm.tar.xz", "origin.json") as (folder, parse):
        assert sha(folder / "protocol.json") == "b2801bb8a8f30b4facd5cc4c1a7b0b9142a7841906f17fd241629504a9273ab2"
        result = read(folder / "positive.json")
        assert result["order"] == ["parent-1", "candidate-1", "candidate-2", "parent-2"]
        rows = {label: recount(folder, label, parse) for label in result["order"]}
        for label in rows:
            assert rows[label][1] == rows["parent-1"][1]
            assert sha(folder / label / "reduced.json") == result["rows"][label]
        for ix, pair in enumerate(result["pairs"], 1):
            assert ix == pair["hold"]
            p, c = [rows[f"{role}-{ix}"][0] for role in ("parent", "candidate")]
            assert pair["by_unit"] == {k: [p[k], c[k]] for k in p} and pair["sum"] == [sum(p.values()), sum(c.values())]
            assert Fraction(c["uv_client"], p["uv_client"]) <= Fraction(9,10) and sum(c.values()) < sum(p.values())
            print(f"Hold {ix}, terminal {p['uv_client']:,} -> {c['uv_client']:,}, all eight {sum(p.values()):,} -> {sum(c.values()):,}")


def verify_cold(directory):
    with unpack(directory, "cold.tar.xz", "cold-origin.json") as (folder, parse):
        summary = read(folder / "cold.json")
        observations, commands = {}, set()
        for label, expected in summary["rows"].items():
            role, hold, state = label.split("-")
            base = folder / label
            assert sha(base / "reduced.json") == expected
            reduced = read(base / "reduced.json")
            rec, info = read(base / "accepted.json"), read(base / "inputs.json")
            assert sha(base / "accepted.json") == reduced["original"] and sha(base / "inputs.json") == rec["inputs"]
            assert (info["role"], info["hold"], info["state"]) == (role, int(hold), state)
            assert info["original_stderr"] == sha(base / "original.stderr")
            products = read(base / "products.json")
            assert products == info["enrollment"] and products["cargo_artifacts"] == 486 and len(products["metadata"]) == 37
            argv = read(base / "original-argv.json")
            assert len(argv) == 982 and argv[argv.index("--crate-name")+1] == "uv_client" and "-Zthreads=8" in argv and "-Zthreads=1" not in argv
            lines = []
            for line in (base / "original.stderr").open():
                if line.lstrip().startswith("Running `") and " --crate-name uv_client " in line:
                    fields = shlex.split(line.strip()[len("Running `"):-1])
                    if argv[0] in fields and fields[fields.index(argv[0]):] == argv:
                        lines.append(dict(x.split("=", 1) for x in fields[:fields.index(argv[0])]))
            exported, = lines
            assert len(exported) == 19 and exported["CARGO_CRATE_NAME"] == "uv_client"
            specs = []
            for mode in ("native", "guest"):
                spec = read(base / mode / "input.json")
                assert spec.pop("mode") == mode
                assert spec["argv"] == argv and spec["cargo_environment"] == exported
                deps = {argv[i+1].split("=", 1)[1] for i,word in enumerate(argv) if word == "--extern"}
                assert set(spec["dependencies"]) == deps and len(deps) == rec["direct_externs"] == 58
                assert rec["results"][mode] == read(base / mode / "worker.json")
                assert not any(read(base / mode / "metadata.json")["different_header_counts"].values())
                specs.append(spec)
            assert specs[0] == specs[1]
            commands.add(tuple(argv))
            obs = rec["results"]["guest"]
            assert sha(base / "raw") == obs["graph_sha256"] == reduced["graph"]
            header, flat, *_ = parse(base / "raw")
            assert header["cmd"] == " ".join(argv) and header["Ir"] == sum(flat.values()) == obs["Ir"] == reduced["Ir"]
            observations[role, int(hold), state] = obs["Ir"]
        assert len(commands) == 1 and len(observations) == 8
        for state in ("A", "B"):
            values = [[observations[role, hold, state] for role in ("parent", "candidate")] for hold in (1,2)]
            assert values == summary["pairs"][state] and not all(c*100 > p*102 for p,c in values)
            print(f"Cold {state}, candidate changes " + ", ".join(f"{100*(c/p-1):+.3f}%" for p,c in values))


if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    verify(here)
    verify_cold(here)
