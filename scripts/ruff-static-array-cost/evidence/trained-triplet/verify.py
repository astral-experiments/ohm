"""Independently replay the registered three-compiler decisions from the exact original ZIPs."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
from zipfile import ZipFile

import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from bits import expand, restore


def sha(data):
    return hashlib.sha256(data).hexdigest()


class UnicodeOracle:
    def __init__(self, alias_file, expected, run_native):
        aliases = alias_file.read_bytes()
        assert sha(aliases) == expected["name_aliases_sha"]
        self.queries = [(row.split(";")[1],int(row.split(";")[0],16)) for row in aliases.decode().splitlines() if row and not row.startswith("#")]
        assert len(self.queries) == 481
        self.queries.extend((n, 0xffffffff) for n in ("carriage_return", "Black_Star", "NO SUCH CODE POINT"))
        self.run_native = run_native
        self.streams = set()
        self.elfs = set()

    def __call__(self, elf, stream):
        key = sha(stream)
        if key not in self.streams:
            position = 0
            names, points, answers = set(), set(), []
            while position < len(stream):
                tag = stream[position]
                position += 1
                assert tag in (1, 2)
                if tag == 1:
                    point, = struct.unpack_from("<I", stream, position)
                    position += 4
                length, = struct.unpack_from("<I", stream, position)
                position += 4
                name = stream[position:position+length].decode("utf-8")
                position += length
                actual, = struct.unpack_from("<I", stream, position)
                position += 4
                if tag == 1:
                    assert actual == point <= 0x10ffff and point not in points and name not in names
                    points.add(point)
                    names.add(name)
                else:
                    answers.append((name,actual))
            assert position == len(stream) and len(points) == len(names) == 153626 and answers == self.queries
            self.streams.add(key)
        key = sha(elf)
        if self.run_native and key not in self.elfs:
            with tempfile.TemporaryDirectory() as scratch:
                executable = Path(scratch)/"reader"
                executable.write_bytes(elf)
                executable.chmod(0o700)
                stdin = ("\n".join(q for q,_ in self.queries)+"\n").encode()
                run = subprocess.run([executable], input=stdin, capture_output=True, check=True)
                assert not run.stderr and run.stdout == stream
        self.elfs.add(key)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--kit", type=Path, default=Path(__file__).resolve().parents[2])
    p.add_argument("--extracted", type=Path, help="Keep the exact reconstructed raw ZIPs in this directory")
    p.add_argument("--report", type=Path)
    p.add_argument("--run-native", action="store_true")
    args = p.parse_args()
    here = Path(__file__).resolve().parent
    kit = args.kit.resolve()
    sys.path.insert(0, str(kit))
    import receive_triplet, triplet
    registry_raw = (here/"originals.json").read_bytes()
    registry = json.loads(registry_raw)
    for name, digest in registry["common_files"].items():
        assert sha((kit/name).read_bytes()) == digest, name
    transports = json.loads((here/"transports.json").read_bytes())
    rows_by_run = {}
    seen_boots = set()
    with tempfile.TemporaryDirectory() as scratch, ZipFile(here/"originals.zip") as packet:
        assert set(packet.namelist()) == {"index.json","bytes.bin"} and packet.testzip() is None
        index = json.loads(packet.read("index.json"))
        assert index["registry"] == sha(registry_raw)
        parts = {(o["run"],o["block"]):o["pieces"] for o in index["records"]}
        expected_parts = {(s["run"],block) for s in registry["studies"] for block in s["originals"]}
        assert len(parts) == len(index["records"]) == len(expected_parts) and set(parts) == expected_parts
        with tempfile.TemporaryFile(dir=scratch) as slabs, packet.open("bytes.bin") as contents:
            shutil.copyfileobj(contents, slabs, 1024*1024)
            size = slabs.tell()
            cursor = 0
            bases = {row[3] for row in index["blobs"].values() if row[3] is not None}
            decoded = set()
            def read_piece(digest):
                if digest in decoded:
                    data = (Path(scratch)/digest).read_bytes()
                    assert sha(data) == digest
                    return data
                offset, n, expected, base, form = index["blobs"][digest]
                assert 0 < n <= expected < 32*1024*1024 and 0 <= offset <= size-n
                slabs.seek(offset)
                data = slabs.read(n)
                if base is not None:
                    ref = Path(scratch)/base
                    assert ref.is_file() and index["blobs"][base][3] is None
                    assert form in ("bytes","bits")
                    if form == "bits":
                        bit_ref = Path(scratch)/(base+".bits")
                        if not bit_ref.exists():
                            bit_ref.write_bytes(expand(ref.read_bytes()))
                        ref = bit_ref
                    data = subprocess.check_output(["zstd","-q","-d","--patch-from="+str(ref),"-c","-"], input=data, stderr=subprocess.DEVNULL)
                    if form == "bits":
                        data = restore(data,expected)
                else:
                    assert form is None
                assert len(data) == expected and sha(data) == digest
                return data
            for digest,(offset,n,length,base,form) in sorted(index["blobs"].items(),key=lambda row:row[1][0]):
                assert offset == cursor and len(digest) == 64
                value = read_piece(digest)
                if base is not None or digest in bases:
                    (Path(scratch)/digest).write_bytes(value)
                    decoded.add(digest)
                cursor += n
            assert size == cursor
            for study in registry["studies"]:
                phase = study["phase"]
                reg_raw = (here/(phase+"-registration.json")).read_bytes()
                assert sha(reg_raw) == study["registration_sha256"]
                reg = json.loads(reg_raw)
                assert reg["orders"] == (triplet.PILOTS if phase=="pilot" else triplet.CONFIRM)
                assert set(study["originals"]) == set(reg["orders"])
                previous = {b for boots in reg["prior_boots_by_run"].values() for b in boots}
                ruff = reg["cases"]["rand"]
                oracle = UnicodeOracle(kit/"NameAliases.txt",ruff,args.run_native)
                jobs = {}
                for block,record in sorted(study["originals"].items()):
                    spec = (study["run"],block)
                    target = (args.extracted or Path(scratch))/str(study["run"])/(block+".zip")
                    target.parent.mkdir(exist_ok=True,parents=True)
                    h = hashlib.sha256()
                    with target.open("wb") as output:
                        for key in parts[spec]:
                            data = read_piece(key)
                            output.write(data)
                            h.update(data)
                    assert h.hexdigest() == record["sha256"] and target.stat().st_size == record["bytes"]
                    with ZipFile(target) as raw:
                        assert raw.testzip() is None and len(raw.namelist()) == len(set(raw.namelist()))
                        host = json.loads(raw.read("host.json"))
                        assert host["head"] == study["head"] and host["case"] == "rand"
                        assert host["registration_sha256"] == study["registration_sha256"]
                        assert host["transports_sha256"] == sha((here/"transports.json").read_bytes())
                        assert host["target_case"] == [ruff["old"],ruff["new"]]
                        assert host["order"] == reg["orders"][block] and host["boot"] not in seen_boots|previous
                        seen_boots.add(host["boot"])
                        jobs[block] = receive_triplet.open_job(raw,reg,transports,ruff,host,oracle)
                    if args.extracted is None:
                        target.unlink()
                decision = triplet.judge(jobs)
                if phase == "confirm":
                    assert next(iter(rows_by_run.values()))["decision"]["admit_six"]
                rows_by_run[str(study["run"])] = {"decision":decision,
                    "rows":{b:{k:r[k] for k in ("boot","order","results","storage")} for b,r in jobs.items()},
                    "native_streams":sorted(oracle.streams),"native_readers":sorted(oracle.elfs)}
    report = json.dumps(rows_by_run,sort_keys=True,indent=2)+"\n"
    if args.report:
        args.report.write_text(report)
    print("Originals, source, counters, storage, complete Cargo products and Unicode behavior passed:",
          ", ".join(rows_by_run))


if __name__=="__main__":
    assert __debug__
    main()
