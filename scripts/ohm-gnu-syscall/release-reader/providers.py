"""Exercise the integrated Cargo on ordinary path collisions and real native-provider changes."""
import importlib.util
import os
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from subjects import ORIGINAL, SOURCES, SVC, registered, rt
from native_kits import Selection, identity
import named
import safety


def legacy(selection, inputs):
    choices = selection(inputs, "P")
    edges = safety.edges
    original = edges.BUILD
    edges.BARRIER = safety.GNU
    report = {}
    expected = {"higher": "29 7", "removed-higher": "17 7", "same-inode-value": "29 7", "real-Rust-edit": "29 11",
                "same-inode-malformed": None, "repaired-edit": "29 13", "missing": None,
                "restored-edit": "17 19", "restored-repeat": "17 19"}
    for reader in ("signed", "classic", "aware"):
        choices.choose(reader)
        for watch, declaration in (("undeclared", ""), ("directories", 'println!("cargo:rerun-if-changed={n}");'),
                                  ("files", 'println!("cargo:rerun-if-changed={n}/libqa_owned_external.a");')):
            edges.BUILD = original.replace('for n in ["early","late"]{', 'for n in ["early","late"]{' + declaration)
            for placement in ("direct", "library"):
                key = "-".join((reader, watch, placement))
                folder = rt.LOG / key
                folder.mkdir()
                edges.run(folder, "P", placement, True, history=safety.mutations, rust_source=safety.PARENT)
                rows = {r["name"]: r for r in rt.load(folder / "completed.json")["cases"]}
                assert len(rows) == 18
                marked = [rt.sha(folder / "raw-depfiles" / m[2]) == m[2] and
                          (safety.OLD.encode() + b":") in (folder / "raw-depfiles" / m[2]).read_bytes().splitlines()
                          for m in rows["cold-lower"]["markers"].values()]
                assert any(marked)
                verdicts = {}
                for actual, reference in safety.parent_study.PAIRS:
                    x, y = rows[actual], rows[reference]
                    assert (y["exit"], y["answer"]) == (101 if expected[actual] is None else 0, expected[actual])
                    assert len(y["actual_GNU_linkers"]) >= 1
                    verdicts[actual] = {"observed": [x["exit"], x["answer"]], "empty": [y["exit"], y["answer"]],
                                        "same_bytes": x["elf"] == y["elf"]}
                report[key] = verdicts
    choices.close()
    # Keep all results, including any difference from either original reader.
    rt.save(rt.LOG / "old-writer-compatibility.json", report)


def main(mode):
    spec = importlib.util.spec_from_file_location("original_syscall_providers", SVC / "providers.py")
    driver = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(driver)
    pin = registered()
    class Receiver:
        def __init__(self, inputs, role):
            super().__init__(inputs, role)
            assert self.active == "signed" and self.identities["aware"]["sha256"] == ORIGINAL
            parked = self.parking / "aware"
            assert identity(parked) == self.identities["aware"]
            temp = self.parking / "integrated"
            shutil.copy2(rt.ROOT / "reader-inputs/integrated", temp)
            temp.replace(parked)
            self.identities["aware"] = identity(parked)
            self.versions["aware"] = SOURCES["integrated"]["commit"]
            assert self.identities["aware"]["sha256"] == pin["elf_sha256"]
            self.reg = {**self.reg, "writer_capsule_original_cargo": self.reg["cargo_elf"],
                        "cargo_elf": pin["elf_sha256"], "integrated_cargo": pin}

    class Integrated(Receiver, driver.Candidate):
        pass

    inputs = Path(os.environ["CENSUS_PARENT"]).parent / "inputs"
    if mode == "legacy":
        class IntegratedOriginal(Receiver, Selection):
            pass
        legacy(IntegratedOriginal, inputs)
        return
    safety.Selection = Integrated
    safety.GNU = driver.RUST
    safety.CHILD = driver.CHILD
    if mode == "named":
        selected = Integrated(inputs, "C")
        named.GNU, named.CHILD = driver.RUST, driver.CHILD
        for name in ("none", "v1", "v2", "both"):
            named.case(selected, name)
        selected.close()
        rt.save(rt.LOG / "named-terminal.json", {name: rt.sha(rt.LOG / ("named-" + name) / "complete.json")
                                                for name in ("none", "v1", "v2", "both")})
    else:
        assert mode in ("aware", "migrate-signed", "migrate-classic")
        safety.main(mode, inputs)
        info = rt.load(rt.LOG / "versioned-native-terminal.json")
        assert info["sources"]["aware"] == SOURCES["integrated"]["commit"] and info["compiler"] == driver.CHILD


if __name__ == "__main__":
    main(sys.argv[1])
