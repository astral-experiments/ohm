"""Check both compilers' original marker output and the preserved native-provider readbacks."""
import gzip
import hashlib
import json
from pathlib import Path
import zipfile

HERE = Path(__file__).resolve().parent
def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    registered = json.loads((HERE / "registration.json").read_bytes())
    archive = HERE / "cross-marker-original.zip"
    assert sha(archive.read_bytes()) == registered["direct"]["zip"]
    with zipfile.ZipFile(archive) as z:
        summary = json.loads(z.read("cross-marker-and-getpid.json"))
        cases = {}
        for role in ("parent", "candidate"):
            markers = summary[role]["markers"]
            assert len(markers) == 26
            assert z.read(f"cross-{role}/getpid.stdout") == b"same pid\n"
            assert not z.read(f"cross-{role}/getpid.stderr")
            assert len(bytes.fromhex(summary[role]["getpid_elf"])) == 32
            for cfg, mode in markers.items():
                output = z.read(f"cross-{role}/{cfg}.stdout").splitlines()
                expected = (b"/dev/null/ohm-recheck-dependent-links-v2:" if mode == "checked-v2"
                            else b"/dev/null/ohm-untracked-relink-inputs:")
                assert [v for v in output if v.startswith(b"/dev/null/ohm-")] == [expected]
            cases[role] = markers
        assert [k for k in cases["parent"] if cases["parent"][k] != cases["candidate"][k]] == ["syscall"]
        assert cases["candidate"]["syscall"] == "checked-v2" and cases["candidate"]["syscall_file"] == "hard"

    b = (HERE / "native-readbacks.json.gz").read_bytes()
    assert sha(b) == registered["readbacks"]
    native = json.loads(gzip.decompress(b))
    for mode, record in native.items():
        assert [record[k] for k in ("run","head","artifact","sha256")] == registered["native"][mode]
        migrating = mode.startswith("migrate-")
        assert record["total_Cargo"] == (42 if migrating else 108)
        for label, hist in record["histories"].items():
            phases = hist["phases"]
            assert len(phases) == (21 if migrating else 18)
            for name, row in phases.items():
                assert row["opening_trace"] == row["source_specific_terminal"] and row["actual_provider_ld"] >= 1
                assert (row["cargo_exit"] == 101) == (row["answer"] is None)
                if row["elf"] is not None:
                    assert row["elf"] in record["ELFs"] and row["cargo_exit"] == 0
                if name.startswith("empty-") or name == "cold-lower":
                    continue
                reference = "empty-" + ("restored-edit" if name == "restored-repeat" else name)
                for key in ("cargo_exit","answer","elf","selected_provider","earlier_negative","later_negative"):
                    assert row[key] == phases[reference][key], (mode,label,name,key)
        print(mode, record["total_Cargo"], "native builds")
    assert set(native) == {"signed","classic","aware","migrate-signed","migrate-classic"}
    print("26 compiler controls per arm, including a real getpid syscall, and 408 native builds.")


if __name__ == "__main__":
    main()
