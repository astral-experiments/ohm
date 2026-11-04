"""Verify physical compiler roles, Rust metadata, kernel images and complete linked programs for #26372."""
from collections import Counter
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile

here = Path(__file__).resolve().parent
sys.path.insert(0, str(here.parent / "evidence-signed-allocation-identity/helpers"))
import extract_alloc as alloc
import reverse_graph as metadata

EDITS = ["03f787e51e94999977b9a5a32b0153d82d7e2142", "fa4a7bca2db70229710892c97b26ea6fb046cfc4"]
ORIGINALS = {"P": [13285899382, 130029833, "9635045953fb86bcc2f53b83238b7ac5f3a946ca1bd7dffa8909c4ebe7fced18"],
             "C": [13285864758, 129272748, "4f2fb3d9e6acbaf7f282643005de116ffb56e8ff8ca909944d555903d52bfa0f"]}
SDK = json.loads((here / "compiler-transports.json").read_bytes())
SOURCE = json.loads((here / "compiler-sources.json").read_bytes())
RUSTC = "/home/runner/work/_temp/ohm-clap-cli/dist/sdk/bin/rustc"

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

class Original:
    def __init__(self, archive, role, retained):
        self.z = archive
        self.role = role
        self.retained = retained
        self.reopened_elf = {}
        self.native_inode = set()

    def read(self, name, keep=True):
        assert self.z.getinfo(name).file_size < 16 * 2**20, name
        raw = self.z.read(name)
        path = self.role + "/" + name
        if keep and self.retained is not None and path not in self.retained.NameToInfo:
            member = zipfile.ZipInfo(path, (1980, 1, 1, 0, 0, 0))
            member.compress_type = zipfile.ZIP_DEFLATED
            self.retained.writestr(member, raw)
        return raw

    def record(self, name, keep=True):
        return json.loads(self.read(name, keep))

    def executables(self, prefix, status=0, keep=True):
        lines = self.read(prefix + "/kernel/epochs.tsv", keep).splitlines()
        terminal, = [l.split() for l in lines if l.startswith(b"W ")]
        assert int(terminal[-1]) == status
        rows = []
        for line in lines:
            fields = line.split()
            if fields[0] != b"I" or fields[5] != b"exec":
                continue
            image = prefix + "/kernel/" + f"{int(fields[1]):05}.nul"
            blob = self.read(image, keep)
            argv = list(map(os.fsdecode, blob.split(b"\0")))
            assert argv.pop() == "" and int(argv[0]) == int(fields[2])
            if argv[3] != RUSTC:
                continue
            args = argv[4:]
            def value(flag):
                found = [args[i+1] if word == flag else word[len(flag)+1:] for i,word in enumerate(args)
                         if word == flag or word.startswith(flag+"=")]
                if len(found) > 1:
                    assert flag == "--crate-type" and all(x in ("bin","rlib","dylib","cdylib","staticlib","proc-macro","lib") for x in found)
                return found[0] if found else None
            crate, kind = value("--crate-name"), value("--crate-type")
            if crate is None:
                continue
            self.native_inode.add((int(argv[1]), int(argv[2])))
            rows.append(dict(crate=crate, kind=kind, argv=args, pid=int(argv[0])))
        assert rows == self.record(prefix + "/real-compiler.json", keep)
        return rows

    def program(self, prefix, executable, new):
        facts = self.record(prefix + "/native.json")
        h = facts["sha256"]
        assert facts["path"].endswith("/debug/" + executable)
        for key, digest in facts["help"].items():
            text = self.read(prefix + "/help-" + key + ".stdout")
            assert b"--help" in text and sha(text) == digest
        if executable == "ruff":
            cli = self.record(prefix + "/changed-CLI.json")
            out, err = [self.read(prefix + "/changed-CLI." + x) for x in ("stdout", "stderr")]
            assert cli["sha256"] == h and cli["state"] == EDITS[int(new)] and "--extend-exclude" in cli["argv"]
            if new:
                assert cli["status"] == 1 and b"Would reformat: main.py" in out
                assert all(x not in out for x in (b"cli_excluded.py", b"format_excluded.py", b"out/a.py"))
            else:
                assert cli["status"] == 2 and b"--extend-exclude" in err
        if h not in self.reopened_elf:
            name = "native-bodies/" + h + ".zst"
            assert 0 < self.z.getinfo(name).file_size < 256 * 2**20 and facts["bytes"] < 1024 * 2**20
            with tempfile.TemporaryFile() as compressed:
                with self.z.open(name) as stream:
                    shutil.copyfileobj(stream, compressed, 1 << 20)
                compressed.seek(0)
                child = subprocess.Popen(["zstd", "-qdc", "-M128MB"], stdin=compressed, stdout=subprocess.PIPE)
                with child.stdout as stream:
                    first = stream.read(64)
                    assert first[:6] == b"\x7fELF\x02\x01" and struct.unpack_from("<HH", first, 16) in ((2, 62), (3, 62))
                    hashed = hashlib.sha256(first)
                    total = len(first)
                    for block in iter(lambda: stream.read(1 << 20), b""):
                        hashed.update(block)
                        total += len(block)
                        assert total <= facts["bytes"]
                assert child.wait() == 0 and total == facts["bytes"] and hashed.hexdigest() == h
                self.reopened_elf[h] = total
        assert self.reopened_elf[h] == facts["bytes"]
        return facts

    def selected(self, prefix, new):
        inputs = self.record(prefix + "/selected.json")
        wire = self.read("metadata/" + inputs["meta_sha"] + ".zst")
        raw = subprocess.check_output(["zstd", "-qdc", "-M32MB"], input=wire)
        assert sha(raw) == inputs["meta_sha"] and len(raw) == inputs["bytes"] < 4 * 2**20
        # Recover the physical allocation-index locations and validate every Memory and provenance.
        folder, phase = prefix.rsplit("/", 1) if "/" in prefix else ("", prefix)
        if folder:
            records, memory, kinds, _, _, data = alloc.recover(self.z, phase, folder)
            allocs = {"count": len(records), "kinds": kinds, "memory": len(memory)}
        else:
            data = metadata.md.decode(raw, metadata.symbols, metadata.tables, "ruff", metadata.ver)
            allocs = None
        for tag, owner in (("stable", "CheckCommand"), ("changed", "FormatCommand")):
            witness = self.record(prefix + "/" + tag + ".json")
            diag = self.read(prefix + "/" + tag + ".stderr")
            src = self.read(prefix + "/" + tag + ".rs")
            assert "::" + owner + ")" in witness["source"] and src.decode() == witness["source"]
            assert witness["selected_rmeta"] == inputs["meta_sha"]
            assert (witness["status"] == 0) == (tag == "stable" or new)
            if witness["status"]:
                assert b"E0609" in diag and b"extend_exclude" in diag
        ledger = self.record(prefix + "/archive-inventory.json")
        return inputs, data, allocs, ledger

def short(rows):
    return [(r["crate"], r["kind"], any(x in ("-Zlink-only", "link-only") for x in r["argv"])) for r in rows]

def native_members(a, b):
    def members(q):
        rows = {}
        nonce = q["nonce"]
        for actual, stable, owner, digest, size in q["members"]:
            assert actual == stable.replace(".rcgu.o", "." + nonce + ".rcgu.o")
            assert stable not in rows and stable.endswith("." + owner + ".rcgu.o") and len(digest) == 64 and size > 0
            rows[stable] = (owner, digest, size)
        return rows
    x, y = members(a), members(b)
    return {"members": [len(x), len(y)], "common": len(x.keys() & y.keys()),
            "identical_bodies": sum(x[k] == y[k] for k in x.keys() & y.keys()),
            "archive_nonce": [a["nonce"], b["nonce"]], "metadata_members": [a["metadata"], b["metadata"]],
            "same_symbol_map_and_link_wrapper": (a["symbol_map"], a["link_wrapper"], a["symbols"]) == (b["symbol_map"], b["link_wrapper"], b["symbols"])}

def verify_role(source, role, retained):
    expected = ORIGINALS[role]
    assert source.stat().st_size == expected[1]
    with source.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == expected[2]
    with zipfile.ZipFile(source) as z:
        assert len(z.namelist()) == len(set(z.namelist())) < 60000
        obj = Original(z, role, retained)
        reg = obj.record("registration.json")
        name = {"P": "parent", "C": "candidate"}[role]
        sdk, src = [obj.record("factory/" + f + ".json") for f in ("sdk", "source")]
        assert reg["role"] == role and reg["source"] == src["source"] == SOURCE[name] and src["tree"] == SOURCE[name + "_tree"]
        assert reg["driver"] == sdk["driver"] == SDK[role]["driver"] and reg["original"] == SDK[role]
        assert src["source"] in sdk["versions"]["rustc"] and SOURCE["cargo"] in sdk["versions"]["cargo"]
        assert reg["source_edit"] == EDITS and obj.record("terminal.json") == {"role": role, "completed": True, "discovery_ordinary_only": True, "failures": {}}
        metadata.ver = sdk["versions"]["rustc"].splitlines()[0] + " (Ohm metadata 3)"
        chosen = obj.record("unit-graph.json")["chosen"]
        assert {k: client for k, client, prod in chosen} == {k: ["-p", k, "--bin", k] for k in ("ruff", "ruff_dev")}
        probes = obj.record("local-probes/direct.json")
        assert [q["native"] for q in probes] == ["Or Or true 17\n", "LShift Or true 17\n", "LShift Or true 17\n", "LShift Or false 17\n", "LShift Or false 17\n"]
        pointer = obj.record("local-probes/pointer-result.json")
        rows = pointer["records"]
        assert [q["label"] for q in rows] == ["shared","distinct","offset","aligned","mutable","separate-promotions","invalid","repaired"]
        assert rows[6]["attempts"] == [{"codes":["E0308"],"status":101}] * 2
        good = [q for q in rows if "edit" in q]
        assert len(set(q["edit"]["public_hash"] for q in good[:5])) == 5
        for q in good:
            assert q["edit"] == q["empty"]
            assert all(q["edit"][k] == q["settled"][k] for k in ("elf","output","public_hash"))
            assert all(q["settled"]["fresh"].values())
        observed = {}
        for crate in ("ruff", "ruff_dev"):
            lane = "normal-" + crate + "/"
            before = obj.executables(lane + "initial-consumer", keep=False)
            owner, = [v for v in before if v["crate"] == crate and v["kind"] == "bin"]
            samples = {}
            for phase, edit in (("initial-consumer", False), ("producer-NEW", True), ("producer-REPAIR", True), ("producer-OLD", False), ("unchanged-consumer", False)):
                samples[phase] = obj.selected(lane + phase, edit)
                if phase.startswith("producer-"):
                    actual = short(obj.executables(lane + phase))
                    assert not any(k == crate and t == "bin" for k,t,_ in actual)
            assert any(x.startswith("ruff=") and x.endswith(samples["initial-consumer"][0]["rlib"]) for x in owner["argv"])
            for phase in ("invalid", "invalid-again"):
                bad = obj.executables(lane + phase, 101)
                assert any(v["crate"] == "ruff" for v in bad) and b"error[E0308]" in obj.read(lane + phase + "/stderr")
            original = obj.program(lane + "initial-consumer", crate, False)
            for phase in ("settled-original", "settled-original-again", "settled-after", "settled-after-again"):
                floor = sorted(short(obj.executables(lane + phase)))
                assert floor == ([] if crate == "ruff" else [("ruff_dev","bin",True),("ty_python_semantic","lib",False)])
                assert obj.program(lane + phase, crate, False) == original
            after = short(obj.executables(lane + "unchanged-consumer"))
            assert obj.program(lane + "unchanged-consumer", crate, False) == original
            first, edit, restored = [samples[k] for k in ("initial-consumer","producer-NEW","producer-OLD")]
            a, b = first[1], restored[1]
            assert a[1] == b[1] and a[3:] == b[3:] and a[0]["public"] != edit[1][0]["public"] != b[0]["public"]
            assert b == samples["unchanged-consumer"][1]
            diff = sum(a[2].get(i) != b[2].get(i) for i in a[2].keys() | b[2].keys())
            captured = obj.record(lane + "summary.json")
            assert diff == captured["changed_public_rows"] and [a[0], b[0]] == captured["publication"]
            assert len(a[1]) == len(b[1]) and len(a[2]) == len(b[2])
            observed[crate] = {"actual_following_consumer": after, "selected_ruff_lib": {k: {"metadata_sha": v[0]["meta_sha"], "rlib_sha": v[0]["rlib_sha"], "public":v[1][0]["public"],"allocations":v[2]} for k,v in samples.items()},
                    "changed_public_rows": diff, "total_public_rows": len(a[2]), "same_definitions": len(a[1]), "same_expansions": len(a[3]), "same_required_crates": len(a[4]),
                    "restored_native_archive": native_members(first[3], restored[3]), "initial_restored_program": original["sha256"],
                    "collected_cargo_fingerprint_files": {k: len(obj.record(lane+k+"/cargo-fingerprints.json")) for k in ("initial-consumer","producer-OLD","unchanged-consumer")}}
        new = {p:obj.program(p,"ruff",True) for p in ("warm-new","empty-new")}
        assert new["warm-new"] == new["empty-new"] and new["warm-new"]["sha256"] != observed["ruff"]["initial_restored_program"]
        for p in new:
            obj.selected(p,True)
            assert any(r["crate"]=="ruff" and r["kind"]=="bin" for r in obj.executables(p,keep=(p=="warm-new")))
        assert len(obj.native_inode)==1
        return {"source":src["source"],"driver":sdk["driver"],"boot":reg["boot"],"actual_rustc_inode":list(obj.native_inode)[0],
                "original_sha256":expected[2],"lanes":observed,"independently_reopened_full_elf":obj.reopened_elf,"exact_warm_clean_edited_program":new["warm-new"]["sha256"],
                "seven_pointer_verdicts":[v["edit"]["output"] for v in good]}

if __name__ == "__main__":
    args = argparse.ArgumentParser()
    args.add_argument("directory",type=Path,help="directory with the original P.zip and C.zip")
    args.add_argument("--retain",type=Path,help="new compact raw control archive")
    opts=args.parse_args()
    artifact=zipfile.ZipFile(opts.retain,"x") if opts.retain else None
    try:
        out={r:verify_role(opts.directory/(r+".zip"),r,artifact) for r in "PC"}
    finally:
        if artifact:artifact.close()
    assert out["P"]["boot"]!=out["C"]["boot"]
    print(json.dumps(out,sort_keys=True,indent=1))
