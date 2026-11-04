"""Reopen each original measurement. Add --run-native to execute the retained Linux programs."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import statistics
import re
import struct
import subprocess
import tempfile
from zipfile import ZipFile

here = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("packet", type=Path, nargs="?", default=here / "originals.zip")
parser.add_argument("--run-native", action="store_true")
parser.add_argument("--extract-originals", type=Path)
parser.add_argument("--report", type=Path, help="Write counts rederived from the raw originals")
parser.add_argument("--gh-auto", type=Path, help="Also check each original artifact's digest on GitHub")
args = parser.parse_args()
assert __debug__
if args.extract_originals:
    args.extract_originals.mkdir(parents=True, exist_ok=False)

def sha(contents):
    return hashlib.sha256(contents).hexdigest()

with ZipFile(args.packet) as packet:
    assert set(packet.namelist()) == {"index.json", "bytes.bin"}
    index = json.loads(packet.read("index.json"))
    data = packet.read("bytes.bin")
chunks = {}
for checksum, (offset, length) in index["blobs"].items():
    chunk = memoryview(data)[offset:offset + length]
    assert len(chunk) == length and sha(chunk) == checksum
    chunks[checksum] = chunk

kit = here.parents[1]
registry = json.loads((here / "originals.json").read_bytes())
sources = json.loads((here / "sources.json").read_bytes())
transports = json.loads((kit / "transports.json").read_bytes())
registrations = {"pilot": (here / "pilot-registration.json").read_bytes(),
                 "confirm": (kit / "registration.json").read_bytes()}
reg = json.loads(registrations["confirm"])
patch = (here / "source.patch").read_bytes()
assert sha(patch) == sources["patch_sha256"]
paths = re.findall(rb"^diff --git a/(\S+) b/(\S+)\nindex ([a-f0-9]{40})\.\.([a-f0-9]{40}) 100644$", patch, re.M)
assert len(paths) == 5 and all(a == b for a, b, _, _ in paths)
assert {a.decode(): p.decode() for a, _, p, _ in paths} == sources["P"]["blobs"]
assert {a.decode(): c.decode() for a, _, _, c in paths} == sources["C"]["blobs"]
assert reg["parent"] == sources["P"]["commit"] == "6c2874a0b6a0bf3570f8959733b6f87907e5cce6"
assert reg["candidate"] == sources["C"]["commit"] == "65390392975bd2668748fd8bd8ebc52915772f41"
assert reg["parent_tree"] == sources["P"]["tree"] and reg["candidate_tree"] == sources["C"]["tree"]
assert sources["C"]["parents"] == [reg["parent"]]
qualification = {}
for arm in "PC":
    data = (here / f"qualification-{arm}.zip").read_bytes()
    factory = registry["factory"][arm]
    transport = transports[arm]
    assert (len(data), sha(data)) == (factory["qualification"]["bytes"], transport["qualification"][1])
    assert all(factory[k] == transport[k] for k in ("run", "qa", "job", "driver", "tar"))
    assert all([factory[k]["id"], factory[k]["sha256"]] == transport[k] for k in ("qualification", "sdk"))
    with ZipFile(io.BytesIO(data)) as q:
        assert q.testzip() is None and len(q.namelist()) == len(set(q.namelist())) == 6
        qualification[arm] = {n: q.read(n) for n in q.namelist()}
    q = qualification[arm]
    src = json.loads(q["source.json"])
    assert src == {"role": "candidate", "source": sources[arm]["commit"], "tree": sources[arm]["tree"],
                   "factory": factory["qa"], "run": str(factory["run"])}
    assert json.loads(q["sdk.json"])["driver"] == factory["driver"] and q["sdk-sha256"].decode().strip() == factory["tar"]
    probe = json.loads(q["probes/verdict.json"])
    assert probe == {"marked_arrays": 4, "native_old": "130571 28100353 2200189891844 false\n",
        "native_repaired": "130572 28100353 2200189891844 false\n",
        "native_empty": "130572 28100353 2200189891844 false\n",
        "invalid": {"message": "literal out of range for `u8`", "byte_start": 1852, "byte_end": 1855}}
assert qualification["P"]["bootstrap.json"] == qualification["C"]["bootstrap.json"]
bootstrap = json.loads(qualification["P"]["bootstrap.json"])
assert bootstrap[bootstrap.index("--stage") + 1] == "1" and "llvm.download-ci-llvm=true" in bootstrap
assert "rust.debug-assertions=false" in bootstrap and "rust.download-rustc=false" in bootstrap
assert all(sources[a]["driver_sha256"] == transports[a]["driver"] for a in "PC")
assert sources["P"]["driver_sha256"] != sources["C"]["driver_sha256"]
assert json.loads(qualification["P"]["sdk.json"])["release_cargo"] == json.loads(qualification["C"]["sdk.json"])["release_cargo"]
fixture = reg["cases"]["rand"]
assert fixture["old_stdout"] == fixture["new_stdout"]
aliases = (here / "NameAliases.txt").read_bytes()
assert sha(aliases) == fixture["name_aliases_sha"]
alias_rows = [(row.split(";")[1], int(row.split(";")[0], 16))
              for row in aliases.decode().splitlines() if row and not row.startswith("#")]
assert len(alias_rows) == 481
alias_rows.extend((name, 0xffffffff) for name in ("carriage_return", "Black_Star", "NO SUCH CODE POINT"))
stdin = ("\n".join(name for name, _ in alias_rows) + "\n").encode()

def verify_native_output(raw):
    assert len(raw) == fixture["native_bytes"] and sha(raw) == fixture["new_stdout"]
    pos = 0
    names = {}
    results = []
    while pos < len(raw):
        tag = raw[pos]
        pos += 1
        assert tag in (1, 2)
        if tag == 1:
            cp, = struct.unpack_from("<I", raw, pos)
            pos += 4
        length, = struct.unpack_from("<I", raw, pos)
        pos += 4
        name = raw[pos:pos + length].decode()
        pos += length
        got, = struct.unpack_from("<I", raw, pos)
        pos += 4
        if tag == 1:
            assert 0 <= cp <= 0x10ffff and got == cp and cp not in names
            names[cp] = name
        else:
            results.append((name, got))
    assert pos == len(raw) and len(names) == len(set(names.values())) == 153626
    assert results == alias_rows

def target_counter(z, prefix):
    images = {}
    found = []
    for line in z.read(prefix + "epochs.tsv").decode().splitlines():
        s = line.split()
        if s[0] == "I":
            index = int(s[1])
            argv = z.read(prefix + f"{index:05}.nul").split(b"\0")
            assert argv.pop() == b"" and int(argv[0]) == int(s[2])
            images[index] = (argv, s[-1])
        elif s[0] == "R":
            index, pid, instructions, enabled, running, status = map(int, s[1:])
            argv, origin = images[index]
            assert status == 0 and int(argv[0]) == pid and origin == "exec"
            assert enabled == running > 0 and instructions > 0
            if b"--crate-name" in argv and argv[argv.index(b"--crate-name") + 1] == b"unicode_names2":
                assert argv[3].endswith(b"/sdk/bin/rustc")
                assert b"crates/ruff_unicode_names2/src/lib.rs" in argv and b"-Zlink-only" not in argv
                found.append(instructions)
    target, = found
    return target

boots = set()
seen_native = set()
seen_streams = set()
def verify_job(z, head, label, enrolled, phase):
    read = lambda path: json.loads(z.read(path))
    host = read("host.json")
    assert host["head"] == head and host["case"] == "rand" and host["boot"] not in boots
    assert host["boot"] == enrolled["boot"] and host["boot"] not in sources["previous_bulk_boots"]
    assert host["registration_sha256"] == sha(registrations[phase]) == registry["studies"][phase]["registration_sha256"]
    assert host["transports_sha256"] == sha((kit / "transports.json").read_bytes())
    assert host["target_case"] == [fixture["old"], fixture["new"]]
    boots.add(host["boot"])
    block = label.split("-")[-1]
    assert host["order"] == enrolled["order"] == json.loads(registrations[phase])["orders"][block]
    assert read("cargo-inputs.json") == reg["archives"]
    assert len(reg["archives"]) == 502
    calibration = [read(f"calibrate-{kind}.json") for kind in ("single", "fork")]
    assert all(c["status"] == 0 and c["enabled"] == c["running"] > 0 for c in calibration)
    assert 1.99 < calibration[1]["instructions"] / calibration[0]["instructions"] < 2.01
    out = {"P": {}, "C": {}}
    summary = read("result.json")
    for arm, name in (("P", "parent"), ("C", "candidate")):
        assert all(z.read(f"sdk-{arm}/{n}") == raw for n, raw in qualification[arm].items())
        if phase == "confirm":
            ast = {}
            products = set()
            for stage in ("cold", "settled"):
                stem = f"{arm}/ordinary-ast/{stage}/"
                result = read(stem + "result.json")
                counter = read(stem + "hardware.json")
                arts = [json.loads(line) for line in z.read(stem + "stdout.jsonl").splitlines()]
                assert arts[-1] == {"reason": "build-finished", "success": True}
                arts = [a for a in arts if a["reason"] == "compiler-artifact"]
                assert len(arts) == result["units"] == 39
                assert sum(a["target"]["name"] == "ruff_python_ast" and a["target"]["kind"] == ["lib"] for a in arts) == 1
                dirty = sorted(a["target"]["name"] for a in arts if not a["fresh"])
                assert dirty == result["dirty"] == (reg["ordinary_ast"][arm]["cold_inventory"] if stage == "cold" else [])
                assert counter["status"] == 0 and counter["enabled"] == counter["running"] > 0
                assert counter["instructions"] == result["instructions"] > 0
                products.add(result["sha256"])
                ast[stage] = counter["instructions"]
            assert len(products) == 1
            out[arm]["ordinary_ast"] = ast
        for mode in ("check", "build"):
            counts = summary[arm][mode]
            path = f"{arm}/{mode}/"
            for stage, key in (("cold-old", "cold"), ("ordinary-edit", "whole_edit"),
                               ("unchanged", "unchanged"), ("observed-edit", "observed_whole"),
                               ("empty-new", "empty")):
                pmu = read(path + stage + "/hardware.json")
                assert pmu["status"] == 0 and pmu["enabled"] == pmu["running"] > 0
                assert pmu["instructions"] == counts[key] > 0
                stage_result = read(path + stage + "/result.json")
                assert pmu["instructions"] == stage_result["hardware"]
                command = stage_result["command"]
                assert command == ["cargo", "+ohm", mode, "-p", "ruff_unicode_names2", "--lib", "--locked",
                                   "--offline", "--message-format=json"]
                assert stage_result["commit"] == fixture["old" if stage == "cold-old" else "new"]
                messages = [json.loads(line) for line in z.read(path + stage + "/stdout.jsonl").splitlines()]
                assert messages[-1] == {"reason": "build-finished", "success": True}
                artifacts = [a for a in messages if a["reason"] == "compiler-artifact"]
                assert len(artifacts) == stage_result["unit_count"]
                assert sorted(a["target"]["name"] for a in artifacts if not a["fresh"]) == stage_result["dirty"]
            for stage, key in (("observed-edit", "target_rustc"), ("observed-empty-new", "empty_target_rustc")):
                assert target_counter(z, path + stage + "/execs/") == counts[key]
            stages = ["cold-old", "ordinary-edit", "unchanged", "observed-edit", "empty-new", "observed-empty-new"]
            if mode == "build":
                stages.append("repaired")
            v = [read(path + stage + "/result.json") for stage in stages]
            assert v[0]["unit_count"] == len(v[0]["dirty"]) == fixture["old_units"]
            assert v[1]["dirty"] == v[3]["dirty"] == fixture["edit_dirty"] and not v[2]["dirty"]
            assert v[4]["dirty"] == v[5]["dirty"] and len(v[4]["dirty"]) == fixture["new_units"]
            assert v[0]["generated"] == fixture["old_generated"] != fixture["new_generated"]
            assert all(item["generated"] == fixture["new_generated"] for item in v[1:])
            if mode == "check":
                assert len({item["product_sha256"] for item in v[1:]}) == 1
            else:
                assert v[0]["native"]["elf"] != v[1]["native"]["elf"]
                for stage, item in zip(stages, v):
                    elf = z.read(path + stage + "/reader")
                    output = z.read(path + stage + "/native.bin")
                    assert sha(elf) == item["native"]["elf"] and sha(output) == item["native"]["stdout"]
                    if sha(output) not in seen_streams:
                        verify_native_output(output)
                        seen_streams.add(sha(output))
                    if args.run_native and sha(elf) not in seen_native:
                        with tempfile.TemporaryDirectory() as tmp:
                            program = Path(tmp) / "reader"
                            program.write_bytes(elf)
                            program.chmod(0o700)
                            assert subprocess.check_output([program], input=stdin) == output
                    seen_native.add(sha(elf))
                assert all(item["native"] == v[1]["native"] for item in v[1:])
                assert all(item["members"]["verified_renames"] == v[1]["members"]["verified_renames"] for item in v[1:])
                assert len(v[1]["members"]["verified_renames"]) == 15
                errors = read(path + "invalid/error.json")
                assert errors == read(path + "invalid-again/error.json")
                overflow, = [e for e in errors if (e.get("code") or {}).get("code") == "overflowing_literals"]
                primary, = [span for span in overflow["spans"] if span["is_primary"]]
                assert primary["byte_start"] < primary["byte_end"] and "u8" in overflow["message"]
            out[arm][mode] = counts
    return out

def action(path):
    return json.loads(subprocess.check_output([args.gh_auto, "api", "repos/astral-experiments/ohm/actions/" + path]))

if args.gh_auto:
    for cohort in [*registry["studies"].values(), *registry["factory"].values()]:
        run = cohort["run"]
        head = cohort.get("head", cohort.get("qa"))
        r = action(f"runs/{run}")
        assert r["id"] == run and r["head_sha"] == head and r["run_attempt"] == 1
        assert r["event"] == "workflow_dispatch" and (r["status"], r["conclusion"]) == ("completed", "success")
        jobs = action(f"runs/{run}/attempts/1/jobs?per_page=100")["jobs"]
        if "records" in cohort:
            assert {j["id"] for j in jobs} == {v["job"] for v in cohort["records"]}
        else:
            jobs = [j for j in jobs if j["id"] == cohort["job"]]
            assert len(jobs) == 1 and jobs[0]["name"] == cohort["job_name"]
            for kind in ("qualification", "sdk"):
                ref = cohort[kind]
                asset = action(f"artifacts/{ref['id']}")
                assert asset["digest"] == "sha256:" + ref["sha256"] and asset["size_in_bytes"] == ref["bytes"]
                assert (asset["workflow_run"]["id"], asset["workflow_run"]["head_sha"]) == (run, head)
        assert all((j["conclusion"], j["head_sha"], j["run_attempt"]) == ("success", head, 1) for j in jobs)

assert len(index["runs"]) == 2
report = {}
for phase, study in zip(("pilot", "confirm"), index["runs"]):
    official = registry["studies"][phase]
    assert (study["run"], study["head"]) == (official["run"], official["head"])
    assert [{k: v for k, v in row.items() if k != "pieces"} for row in study["records"]] == official["records"]
    rows = {}
    for record in study["records"]:
        raw = b"".join(chunks[key] for key in record["pieces"])
        digest = sha(raw)
        assert len(raw) == record["original_bytes"] and digest == record["original_sha256"]
        if args.gh_auto:
            a = action(f"artifacts/{record['artifact']}")
            assert a["digest"] == "sha256:" + digest and a["workflow_run"]["id"] == study["run"]
            assert a["workflow_run"]["head_sha"] == study["head"]
        if args.extract_originals:
            (args.extract_originals / f"{study['run']}-{record['label']}.zip").write_bytes(raw)
        with ZipFile(io.BytesIO(raw)) as z:
            assert z.testzip() is None and len(z.namelist()) == len(set(z.namelist()))
            rows[record["label"]] = verify_job(z, study["head"], record["label"], record, phase)
    assert len(rows) == (2 if phase == "pilot" else 6)
    summaries = {}
    for mode, fields in [("check", ("target_rustc", "whole_edit", "empty_target_rustc", "cold", "empty", "unchanged")),
                         ("build", ("target_rustc", "whole_edit", "empty_target_rustc", "cold", "empty", "unchanged")),
                         ("ordinary_ast", ("cold", "settled") if phase == "confirm" else ())]:
        for field in fields:
            pairs = [(r["P"][mode][field], r["C"][mode][field]) for r in rows.values()]
            changes = [(p-c)/p for p,c in pairs]
            name = mode + "/" + field
            summaries[name] = dict(pairs=pairs, minimum=min(changes), median=statistics.median(changes), maximum=max(changes))
            print(study["run"], name, f"median {100*statistics.median(changes):.4f}% ({100*min(changes):.4f}%..{100*max(changes):.4f}%)")
            if field in ("cold", "unchanged", "settled"):
                cutoff = 2 if mode == "ordinary_ast" else 5
                assert not all(c-p > 10_000_000 and 100*(c-p) > cutoff*p for p,c in pairs), "Common-path veto on " + name
    key = summaries["check/target_rustc"]
    if phase == "pilot":
        assert all(20*(p-c) >= p for p,c in key["pairs"])
    else:
        assert key["minimum"] > 0 and key["median"] >= .05
    report[phase] = summaries
report["native_readers"] = sorted(seen_native)
report["native_streams"] = sorted(seen_streams)
assert len(boots) == len(sources["previous_bulk_boots"]) == 8
if args.report:
    args.report.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
print("Reopened eight original jobs,", len(seen_native), "distinct Linux ELFs,", len(seen_streams),
      "complete Unicode stream(s). The six-pair primary passed, exact two-sided sign p=0.03125.")
