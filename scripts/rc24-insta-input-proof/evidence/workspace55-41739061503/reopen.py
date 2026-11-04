"""Reopen the compact 55-member controls and both physical e2e binaries with Python 3.11+ and zstd."""

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import tarfile
import tempfile
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = "9827cae719308452d3293caadd022351e4a940b9c01502c3da339d12c036ed25"
REFUSED = "67a829d0ca8d4bdc5a1b078b1dc502ba42a3163a19c103400c60f73e1c9b5a47"


def file_sha(p):
    with p.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def read_json(path):
    return json.loads(path.read_bytes())


def module(path):
    spec = importlib.util.spec_from_file_location(path.stem.replace("-", "_"), path)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


class Controls:
    def __init__(self, records, bodies):
        self.records = records
        self.bodies = bodies

    def read(self, name):
        size, digest, crc = self.records[name]
        b = self.bodies[digest]
        assert len(b) == size and zlib.crc32(b) == crc
        return b


def native_bodies(packet, scratch, native_index, reader, comparison):
    base_zst = packet / "empty-e2e.elf.zst"
    delta = packet / "traced-parent.delta.zst"
    alt_zst = scratch / "traced-parent.elf.zst"
    assert file_sha(base_zst) == native_index[BASE]["compressed_sha256"]
    with alt_zst.open("xb") as f:
        subprocess.run(
            ["zstd", "-dq", "--patch-from=" + str(base_zst), "-c", delta],
            stdout=f, check=True
        )
    assert file_sha(alt_zst) == native_index[REFUSED]["compressed_sha256"]
    paths, images = {}, {}
    for h, src in ((BASE, base_zst), (REFUSED, alt_zst)):
        dest = scratch / h
        with dest.open("xb") as f:
            subprocess.run(["zstd", "-dq", "-c", src], stdout=f, check=True)
        images[h] = reader.elf_record(dest)
        assert images[h]["sha256"] == h and images[h]["bytes"] == native_index[h]["bytes"]
        paths[h] = dest
    # This compares the two full files, their real ELF program and section headers,
    # GNU notes, and their four loadable segments.
    return images, comparison.compare(paths[REFUSED], paths[BASE])


def reopen(packet):
    inventory = read_json(packet / "controls-index.json")
    v = read_json(packet / "verified.json")
    sdk_source = read_json(packet / "release-compiler.json")
    plan = read_json(packet / "workspace-enrollment.json")
    price = read_json(packet / "pricing.json")
    expected = read_json(packet / "expected.json")
    meta = read_json(packet / "run.json")
    assets = read_json(packet / "artifacts.json")["artifacts"]
    assert meta["head_sha"] == expected["head"] and meta["id"] == expected["run"] == 41739061503
    assert meta["event"] == "workflow_dispatch" and meta["run_attempt"] == 1
    assert set(inventory["blocks"]) == set(v) == {"PC", "CP"}
    bodies = {}
    with tarfile.open(packet / "raw-controls.tar.xz", "r|xz") as t:
        for m in t:
            assert m.isfile() and re.fullmatch(r"[0-9a-f]{64}", m.name) and m.name not in bodies
            b = t.extractfile(m).read()
            assert hashlib.sha256(b).hexdigest() == m.name and len(b) == m.size
            bodies[m.name] = b
    needed = {row[1] for block in inventory["blocks"].values() for row in block.values()}
    assert set(bodies) == needed
    rw = module(packet / "workspace-review.py")
    elf = module(packet / "e2e-difference.py")
    answer = {}
    with tempfile.TemporaryDirectory() as td:
        images, difference = native_bodies(packet, Path(td), inventory["native"], rw, elf)
        committed = read_json(packet / "PC-all-bytes.json")
        difference = json.loads(json.dumps(difference))
        assert difference == committed["roles"]["parent"]["vs_empty"][REFUSED]
        for block, paths in inventory["blocks"].items():
            item, = [x for x in assets if x["name"] == f"insta-workspace-{block}-{meta['id']}"]
            assert item["workflow_run"]["id"] == meta["id"]
            assert inventory["originals"][block] == [item["id"], item["size_in_bytes"], item["digest"]]
            z = Controls(paths, bodies)
            for k in paths:
                z.read(k)
            enrolled = rw.record(z, "admission.json")
            assert enrolled["head"] == meta["head_sha"] and int(enrolled["run"]) == meta["id"]
            assert enrolled["study"] == plan and enrolled["order"] == plan["orders"][block]
            assert enrolled["boot"] == v[block]["boot"]
            sdk = rw.record(z, "sdk-24.json")
            assert len(sdk["files"]) == len(sdk_source["members"]) == 79
            assert sdk["archive"]["sha256"] == "sha256:" + sdk_source["tar_sha256"] == "sha256:" + plan["sdk_archive"]
            for k, r in sdk_source["members"].items():
                assert sdk["files"][k][0] == r["sha256"] and sdk["files"][k][-1] > 0
            source = rw.record(z, "matched-source.json")
            assert source == v[block]["source"] and source["qa"] == price["producer_head"]
            assert int(source["run"]) == price["producer_run"]
            assert {role: c["sha256"] for role, c in source["cargo"].items()} == price["cargo"]
            assert 1.99 < rw.checked_pmu(rw.record(z, "calibration-fork.json")) / rw.checked_pmu(rw.record(z, "calibration-single.json")) < 2.01
            all_bytes = read_json(packet / f"{block}-all-bytes.json")
            assert item["digest"] == "sha256:" + all_bytes["original_zip_sha256"]
            first, second = enrolled["order"]
            assert all_bytes["roles"][first]["vs_empty"] == {REFUSED: difference}
            assert all_bytes["roles"][second]["vs_empty"] == {}
            for role_name, physical_read in all_bytes["roles"].items():
                phases = physical_read["native_phase_sha256"]
                assert phases["edit"] == phases["first-unchanged"] == phases["second-unchanged"] == phases["repair"] == phases["independent-empty"] == BASE
                assert phases["separate-unchanged-observed"] == (REFUSED if role_name == first else BASE)
            actual = rw.record(z, "result.json")
            for role in ("parent", "candidate"):
                ref = v[block]["roles"][role]

                def compact_native(z_unused, actual_role, ledgers):
                    assert role == actual_role and set(ledgers) == set(ref["native_files"])
                    reopened = {}
                    for h, ledger in ledgers.items():
                        assert ledger["sha256"] == h
                        sec = hashlib.sha256(json.dumps(ledger["sections"], separators=(",", ":")).encode()).hexdigest()
                        assert ref["native_files"][h] == {
                            "file_bytes": ledger["bytes"], "section_count": len(ledger["sections"]),
                            "physical_sections_digest": sec,
                        }
                        if h in images:
                            assert ledger == images[h]
                            reopened[h] = ref["native_files"][h]
                    return reopened

                reread = rw.roles(z, role, sdk, actual[role], plan, native_reader=compact_native)
                reread = json.loads(json.dumps(reread))
                native = reread.pop("native_files")
                assert native.keys() == images.keys() & ref["native_files"].keys()
                assert reread == {k: w for k, w in ref.items() if k != "native_files"}
                answer[f"{block}/{role}"] = {
                    "original_native_gate": actual[role]["e2e_exact"],
                    "primary_instructions": reread["whole"]["first-unchanged"],
                    "full_rustcs": reread["census"]["full"],
                    "physically_reopened_selected_elfs": sorted(native),
                    "additional_section_ledgers_from_originals": sorted(ref["native_files"].keys() - native.keys()),
                }
    assert len({v[b]["boot"] for b in v}) == len(v)
    return {"stages_and_census": answer, "refused_file_bytes": difference}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("packet", nargs="?", type=Path, default=HERE)
    print(json.dumps(reopen(p.parse_args().packet), indent=2, sort_keys=True))
