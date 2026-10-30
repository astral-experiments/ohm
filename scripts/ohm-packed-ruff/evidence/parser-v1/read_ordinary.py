"""Independently admit complete ordinary Ruff installations from the closed Actions archive."""
import base64
import gzip
import hashlib
import itertools
import json
from pathlib import Path
import random
import re
from statistics import median
import sys
import zipfile

PHASES = ("empty-A", "first-B", "return-A", "return-B", "unchanged-B",
          "dirty-B-as-A", "restored-B", "invalid", "recovery")
ARMS = ("Off", "Full", "Packed")
LIVE = ["ruff_python_ast", "ruff_python_parser"]
SALT = re.compile(r"([\w]+-[0-9a-f]{16}\.[a-z0-9]{25})\.[a-z0-9]{7}(\.rcgu\.o)")
EXPECTED_CARGO = ["cargo", "+ohm", "build", "-p", "ruff_python_parser", "--locked", "--offline",
                  "-j4", "--message-format=json"]


def sha(body):
    return hashlib.sha256(body).hexdigest()


def arch_members(lib):
    # Metadata links name each native member. Only their seven-character,
    # run-specific incremental suffix differs between independent clean compiles.
    original = lib["members"]
    normalized = {}
    substitutions = {}
    for name, row in original.items():
        stable = SALT.sub(r"\1.0000000\2", name, count=1)
        assert stable not in normalized
        normalized[stable] = tuple(row)
        if name != stable:
            assert row[0] == "elf"
            substitutions[name.encode()] = stable.encode()
    if "lib.rmeta-link" in original:
        raw = base64.b64decode(lib["raw_link_metadata"], validate=True)
        assert len(raw) == original["lib.rmeta-link"][1] and sha(raw) == original["lib.rmeta-link"][2]
        for old, new in substitutions.items():
            assert raw.count(old) == 1
            raw = raw.replace(old, new)
        normalized["lib.rmeta-link"] = ("link-index", len(raw), sha(raw))
    return normalized


def compare_archives(clean, observed):
    assert clean.keys() == observed.keys()
    divergences = {}
    for name, baseline in clean.items():
        actual = arch_members(observed[name])
        expected = arch_members(baseline)
        assert actual.keys() == expected.keys(), name
        different = sorted(n for n in actual if actual[n] != expected[n])
        assert set(different) <= {"lib.rmeta"}, (name, different)
        if different:
            divergences[name] = different
    return divergences


class Archive:
    def __init__(self, file):
        self.z = zipfile.ZipFile(file)
        names = self.z.namelist()
        assert len(set(names)) == len(names)
        assert all(not Path(n).is_absolute() and ".." not in Path(n).parts for n in names)

    def raw(self, path):
        return self.z.read(str(path))

    def record(self, path):
        path = str(path)
        body = self.raw(path)
        return json.loads(gzip.decompress(body) if path.endswith(".gz") else body)


def qualify_inputs(a, expected_head):
    assert a.raw("hosted-study-head.txt").decode().strip() == expected_head
    assert a.raw("storage-mode.txt").strip() in (b"runner-filesystem", b"private-ext4")
    enrolled = a.record("enrolled.json")
    assert enrolled["cargo_and_wild"]["bin/cargo"] == "abf43741c6c75f7fd4a3bcbf1db0cfc29824a07727bde4a3974b3ea44b379c1a"
    assert enrolled["cargo_and_wild"]["lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"] == "0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5"
    assert enrolled["release"] == "edb64a2ee39b2f2951614f98d53ec4e4197f55149ff794c911bd81bc7f870b15"
    p, c = a.record("P.json"), a.record("C.json")
    assert (p["commit"], c["commit"]) == ("b676a640c76193a0e241d2517a64e37e156659b9", "eb15cd3dc0ab0404f8ad18589569e05a70a4d401")
    assert (p["compiler_tree"], c["compiler_tree"]) == ("1df08b3c45a7e6fa3739a8e753132f707f97896a", "b8fa7ed926a6589fb8fd7e913b0eaadc36875611")
    assert all(p[k] == c[k] for k in ("stage0_rustc","stage0_cargo","stage0_source"))
    assert p["files"].keys() == c["files"].keys()
    changed = {n for n in p["files"] if p["files"][n] != c["files"][n]}
    assert set(enrolled["changes"]) == changed and any(n.startswith("lib/librustc_driver-") for n in changed)
    assert all(n.startswith("lib/librustc_driver-") or n == "bin/rustc" for n in changed)
    assert any("/lib/libproc_macro-" in n and n.endswith(".rlib") for n in p["files"])
    assert any("/lib/libtest-" in n and n.endswith(".rlib") for n in p["files"])
    locked = a.record("archives.json")
    assert len(locked) == 505 and all(re.fullmatch("[0-9a-f]{64}", val) for val in locked.values())
    n = a.record("native-guard/verified.json")
    assert [n[k]["result"] for k in ("first", "change", "repair", "clean")] == [17, 29, 29, 29]
    assert n["truncated"]["error"] and n["change"]["executable_sha256"] == n["repair"]["executable_sha256"] == n["clean"]["executable_sha256"]
    clean = {}
    for arm in ARMS:
        for key in ("A","B","B-as-A"):
            clean[arm,key] = a.record(f"references/{arm}-{key}.json.gz")
            key_dir = f"references/{arm}-{key}"
            assert a.record(key_dir + "/archive-index.json.gz") == clean[arm,key]["archives"]
            expected = 56 if key == "B" else 64
            assert clean[arm,key]["typed_size"] == expected
            assert a.raw(key_dir + "/read-native.stdout").decode().strip() == f"Expr={expected} valid=1 rejected"
    return clean


def installation(a, clean, path, arm, traced=False):
    all_steps = a.record(path + "/installation.json")
    assert set(all_steps) == set(PHASES)
    for phase in PHASES:
        prefix = path + "/" + phase + "/"
        raw = a.record(prefix + "cargo.json")
        diagnostic_stream = list(map(json.loads, a.raw(prefix + "cargo.stdout").splitlines()))
        invalid = phase == "invalid"
        assert diagnostic_stream[-1] == {"reason":"build-finished","success":not invalid}
        assert raw["exit"] == (101 if invalid else 0) and raw["wall_ns"] > 0
        if invalid:
            assert any(r.get("message",{}).get("code") and r["message"]["code"]["code"] == "E0308" and
                       any("ohm_branch_switch_invalid" in text["text"] for span in r["message"]["spans"] for text in span["text"])
                       for r in diagnostic_stream)
            continue
        step = a.record(prefix + "result.json")
        assert all_steps[phase] == step and all(raw[k] == step[k] for k in raw)
        assert step["compiler_Ir"] is None and step["counted"] is False
        structural = traced and phase in ("return-A","return-B","unchanged-B")
        assert step["traced"] == structural
        if structural:
            assert raw["argv"][-len(EXPECTED_CARGO):] == EXPECTED_CARGO
            roster = a.record(prefix + "native-execs.json.gz")
            ordered = sorted(p["crate"] for p in roster["rustcs"])
            assert ordered == ([] if phase == "unchanged-B" else LIVE) and roster["wild"] == 0 and roster["real_cargo"] == 1
            for proc in roster["rustcs"]:
                assert "-Zohm-check-relink-inputs" in proc["argv"] and ("-Zohm-branch-cache=yes" in proc["argv"]) == (arm != "Off")
        else:
            assert raw["argv"] == EXPECTED_CARGO
        dirty = sorted(r["target"]["name"] for r in diagnostic_stream if r["reason"]=="compiler-artifact" and not r["fresh"])
        assert dirty == step["dirty"]
        if phase in ("return-A","return-B","dirty-B-as-A","restored-B"):
            assert dirty == LIVE
        if phase == "unchanged-B":
            assert not dirty
        key = "B-as-A" if phase == "dirty-B-as-A" else "A" if phase in ("empty-A","return-A") else "B"
        golden = clean[arm,key]
        expected = golden["typed_size"]
        assert step["executable"] == golden["reader_sha256"] and step["expr"] == expected
        assert a.raw(prefix + "read-native.stdout").decode().strip() == f"Expr={expected} valid=1 rejected"
        assert a.record(prefix + f"layout-{expected}.json")["exit"] == 0
        contrary = 120 - expected
        assert a.record(prefix + f"layout-{contrary}.json")["exit"] == 1
        assert any(x.get("code") and x["code"]["code"] == "E0308" for x in map(json.loads,a.raw(prefix+f"layout-{contrary}.stderr").splitlines()))
        diff = compare_archives(golden["archives"],a.record(prefix+"archive-index.json.gz"))
        assert diff == step["metadata_differences"]
        disk = a.record(prefix+"allocated.json")
        assert len(disk["du"])==2 and sum(int(l.split()[0]) for l in disk["du"]) == disk["target_and_build_bytes"] == step["allocated"]
        if phase in ("first-B","return-A","return-B","unchanged-B"):
            assert (step["packed_objects"] > 0) == (arm == "Packed")
        samples = a.record(prefix + "samples.json.gz")
        if not traced and step["storage_mode"]=="runner-filesystem":
            assert samples == [] and step["peak_fs"] is None
        elif samples:
            assert step["peak_fs"]==max((v for _,_,v in samples if v is not None),default=None)
    return all_steps


def cohort(a, clean, stage):
    orders = [list(ARMS),list(reversed(ARMS))]
    if stage == "confirm":
        orders = list(map(list,itertools.permutations(ARMS))) * 2
        random.Random(0x28335020).shuffle(orders)
    assert a.record(stage + "/plan.json") == {"orders": orders, "command": EXPECTED_CARGO, "phases": list(PHASES)}
    groups=[]
    for idx, order in enumerate(orders,1):
        groups.append({arm:installation(a,clean,f"{stage}/triplet-{idx:02}-{arm}",arm) for arm in order})
    evals={}; ok=True
    for phase in ("return-A","return-B"):
        ratios = [g["Off"][phase]["wall_ns"]/g["Packed"][phase]["wall_ns"] for g in groups]
        lower = sorted(ratios)[2 if stage=="confirm" else 0]
        evals[phase]={"individual":ratios,"median":median(ratios),"lower":lower}
        ok &= lower>2
    saved={p:[g["Full"][p]["allocated"]-g["Packed"][p]["allocated"] for g in groups] for p in ("first-B","return-A","return-B")}
    ok &= all(min(s)>0 for s in saved.values())
    hosted = a.record(stage + "/result.json")
    assert hosted["performance"]==evals and hosted["storage_saved_bytes"]==saved and hosted["admitted"]==ok
    extra={}
    for name,phases in {"first switch":("first-B",),"first switch plus return":("first-B","return-A"),
                        "first dirty edit":("dirty-B-as-A",),"restore edit":("restored-B",)}.items():
        extra[name]={arm:[sum(g[arm][p]["wall_ns"] for p in phases) for g in groups] for arm in ARMS}
    disk={phase:{arm:[g[arm][phase]["allocated"] for g in groups] for arm in ARMS} for phase in PHASES if phase!="invalid"}
    return {"over_two_and_smaller":ok,"returns":evals,"saved_bytes":saved,"whole_bytes":disk,"secondary_ns":extra}


def main():
    raw, expected, head, dest = sys.argv[1:]
    with open(raw,"rb") as f:
        assert hashlib.file_digest(f,"sha256").hexdigest()==expected
    a=Archive(raw)
    clean=qualify_inputs(a,head)
    for arm in ARMS:
        installation(a,clean,"mechanism-"+arm,arm,traced=True)
    result={"head":head,"input_archive":expected,"screen":cohort(a,clean,"screen")}
    if result["screen"]["over_two_and_smaller"]:
        result["confirm"]=cohort(a,clean,"confirm")
    with Path(dest).open("x") as f:
        json.dump(result,f,indent=2,sort_keys=True)
        f.write("\n")


if __name__=="__main__":
    main()
