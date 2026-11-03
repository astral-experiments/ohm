"""Recompute the six paired effects, optionally checking the original ZIPs and native bytes."""
import argparse
import hashlib
import gzip
import types
import json
import math
import statistics
import subprocess
from pathlib import Path
from threading import Thread
import shutil
import zipfile

HERE = Path(__file__).resolve().parent
PHASES = ("old", "edit", "first", "warm0", "warm1", "warm2", "clean")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def sha_file(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def native_hash(z, name):
    # The worker records physical ELF/archives as independently addressable zstd members.
    with z.open(name) as inp, subprocess.Popen(["zstd", "-dcq"], stdin=subprocess.PIPE, stdout=subprocess.PIPE) as p:
        def feed():
            with p.stdin:
                shutil.copyfileobj(inp, p.stdin)
        t = Thread(target=feed)
        t.start()
        result = hashlib.file_digest(p.stdout, "sha256").hexdigest()
        t.join()
        assert p.wait() == 0
        return result


def compiler_decoder(spec):
    rule = spec['confirmation']['storage']
    base = 'scripts/ruff-module-16149/'
    def blob(name, key):
        ref = rule['decoder_revision'] + ':' + base + name
        data = subprocess.check_output(['git', '-C', HERE, 'show', ref])
        assert sha(data) == rule[key]
        return data
    module = types.ModuleType('salsa_scope_rdr')
    source = blob('scope_rdr.py', 'decoder_sha256')
    exec(compile(source, 'salsa_scope_rdr.py', 'exec'), module.__dict__)
    schema = json.loads(gzip.decompress(blob('schema.json.gz', 'schema_sha256')))
    return lambda raw: module.decode(raw,schema['symbols'],schema['tables'],'salsa','rustc 1.99.0-dev (Ohm metadata 3)',edition='2021')


def original_metadata(z, pair, spec, decode):
    rule = spec['confirmation']['storage']
    other = {}
    for role in 'PC':
        reference = None
        for phase in ('old','warm2','clean'):
            prefix = role+'-'+phase+'/'
            sample = pair['salsa_metadata'][role][phase]
            info = json.loads(z.read(prefix+'result.json'))['salsa_storage']
            ledger = json.loads(gzip.decompress(z.read(prefix+'stored-files.json.gz')))
            assert len({(dev,ino) for nm,dev,ino,size,alloc in ledger}) == len(ledger)
            native = [row for row in ledger if row[0].endswith('.rmeta')]
            row, = [r for r in native if Path(r[0]).name == rule['name']]
            assert row[0] == sample['path'] == info['path'] and row[3] == sample['bytes']
            assert row[3] in (rule['parent_warm_sizes'] if (role,phase)==('P','warm2') else [rule['cold_size']])
            assert row[4] == sample['allocated'] == rule['allocated']
            raw = gzip.decompress(z.read(sample['raw']+'.salsa-rmeta.gz'))
            assert len(raw) == row[3] and sha(raw) == sample['raw'] == info['raw']
            head, *tables = decode(raw)
            assert head.pop('full') == sample['raw'] and head == sample['semantic'] == info['root']
            identities = {k:sha(json.dumps(v,sort_keys=True,separators=(',',':')).encode()) for k,v in zip(('definitions','RDR','expansions','dependencies'),tables)}
            assert identities == sample['tables'] == info['tables']
            if reference is None: reference = head,identities
            assert reference == (head,identities)
            rest = sorted([Path(path).name,size] for path,dev,ino,size,blocks in native if path != row[0])
            assert rest == info['other_metadata'] and len(rest) == 215
            if phase=='warm2':other[role]=rest
    assert other['P'] == other['C']
    assert pair['salsa_metadata']['C']['old']['raw'] == pair['salsa_metadata']['C']['warm2']['raw']


def check_original(pair, spec, path, decode):
    asset = pair["artifact"]
    assert path.stat().st_size == asset["size_in_bytes"] and "sha256:" + sha_file(path) == asset["digest"]
    with zipfile.ZipFile(path) as z:
        original_metadata(z,pair,spec,decode)
        j = lambda name: json.loads(z.read(name))
        entry = j("enrollment.json")
        assert [entry[k] for k in ("rank", "order", "boot", "runner")] == [pair[k] for k in ("rank", "order", "boot", "runner")]
        assert entry["head"] == spec["head"] and entry["run"] == str(spec["run"])
        assert sha(z.read("decision.json")) == pair["gate_sha256"] and all(j("decision.json")["gates"].values())
        for role in "PC":
            assert pair["clocks"][role] == {p: j(f"{role}-{p}/whole.json") for p in PHASES}
            for p in ("old", "edit", "first", "warm0", "warm1", "warm2", "repair", "clean", "census-cold", "census-edit", "census-warm"):
                row = j(f"{role}-{p}/result.json")
                state = "old" if p in ("old", "census-cold") else "new"
                assert row["elf"] == pair["elf"][state] and (row["harness"]["inventory"], row["harness"]["count"], row["harness"]["name"]) == (pair["inventory"], 2454, spec["confirmation"]["named"])
                assert b"1 passed; 0 failed;" in z.read(f"{role}-{p}/named.stdout")
            assert j(role+"-withheld/result.json")["verdict"]["code"] == 101
            failed = z.read(role+"-withheld/named.stdout")
            assert b"RUF009_attrs.py:144:20" in failed and b"RUF009_attrs.py:134:37" in failed and b"0 passed; 1 failed;" in failed
            assert j(role+"-invalid/result.json")["status"] == 101 and b"E0308" in z.read(role+"-invalid/stderr")
            for s in ("edit", "warm"):
                rows = j(f"{role}-census-{s}/result.json")["roster"]
                actual = []
                wild = 0
                for row in rows:
                    raw = z.read(f"{role}-census-{s}/tasks/" + row["argv"])
                    assert sha(raw) == row["sha256"]
                    fields = raw.split(b"\0"); argv = [s.decode() for s in fields[4:-1]]
                    if row["role"] == "rustc" and row["mode"] != "config":
                        actual.append(argv[argv.index("--crate-name")+1])
                    wild += row["role"] == "wild"
                expected = ["portable_atomic", "ruff_db", "ruff_linter", "salsa"] if role == "P" else ["ruff_linter"] if s == "edit" else []
                assert sorted(actual) == expected and wild == bool(expected)
        assert sha(z.read(pair["inventory"]+".test-names")) == pair["inventory"]
        raw = {n:Path(n).name.split(".")[0] for n in z.namelist() if n.endswith(".native.zst") or n.startswith("native-operands/") and n.endswith(".zst")}
        assert len(raw) == pair["physical_inputs"]
        for name, want in raw.items():
            assert native_hash(z, name) == want, name


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archives", type=Path, help="Directory with 0/original.zip through 5/original.zip")
    args = parser.parse_args()
    report = json.loads((HERE / "pairs.json").read_bytes())
    decoder = compiler_decoder(report) if args.archives else None
    pairs = report["pairs"]
    assert len(pairs) == 6 and [(p["rank"],p["order"]) for p in pairs] == list(enumerate(["PC","CP"]*3))
    assert all(len({p[key] for p in pairs}) == 6 for key in ("boot","runner_id","runner","job"))
    assert len({p["artifact"]["id"] for p in pairs}) == 6
    for p in pairs:
        assert p["elf"] == report["confirmation"]["sources"] and p["inventory"] == report["confirmation"]["inventory"]
        for clocks in p["clocks"].values():
            for q in clocks.values(): assert q["enabled"] == q["running"] > 0 and q["status"] == 0 and q["instructions"] > 0
        if args.archives: check_original(p, report, args.archives / str(p["rank"]) / "original.zip", decoder)
        print(p["rank"], p["order"], p["clocks"]["P"]["first"]["instructions"], p["clocks"]["C"]["first"]["instructions"])
    for label in PHASES:
        pc = [(p["clocks"]["P"][label]["instructions"],p["clocks"]["C"][label]["instructions"]) for p in pairs]
        diff = [(a-b)/a for a,b in pc]; n = sum(x!=0 for x in diff)
        k = min(sum(x>0 for x in diff),sum(x<0 for x in diff))
        pval = min(1.0,2*sum(math.comb(n,i) for i in range(k+1))/2**n)
        stored = report["stats"][label]
        assert abs(100*statistics.median(diff)-stored["median_percent"]) < 1e-10
        assert all(abs(a-b)<1e-10 for a,b in zip([100*min(diff),100*max(diff)],stored["median_interval_96_875_percent"]))
        assert pval == stored["two_sided_exact_sign_p"]
        print(f"{label:6} {statistics.median(diff)*100:+.4f}% [{min(diff)*100:+.4f}, {max(diff)*100:+.4f}], sign p={pval:g}")
    assert all(p["clocks"]["C"]["first"]["instructions"] <= 0.8*p["clocks"]["P"]["first"]["instructions"] for p in pairs)


if __name__ == "__main__":
    main()
