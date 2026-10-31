"""Verify the same GC and Ruff controls on the candidate that preserves native link checks."""
import json
from collections import Counter
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
release = runpy.run_path(str(HERE.parent / "release-check/verify.py"))


def verify_unicode_link(data, prefix, runtime, subjects, workers, links, previous):
    """Identify each extra compiler, the real Wild link and the subsequent generator execution."""
    assert Counter(workers) == Counter([*previous, "build_script_build", "unicode_names2"])
    [(link_pid, linker_path)] = links
    wild = subjects["tools"]["wild"]
    assert linker_path == wild["physical"] and wild["sha256"] == "0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5"
    outputs = []
    executed = []
    compilers = {}
    for line in data[prefix + "trace/exec.tsv"].decode().splitlines():
        seq, pid, dev, ino, _, image = line.split("\t")
        identity = [int(dev), int(ino)]
        argv = data[prefix + f"trace/args-{int(seq):04d}"].rstrip(b"\0").decode().split("\0")
        if int(pid) == link_pid and image == linker_path:
            assert identity == wild["dev_ino"] and "-o" in argv
            outputs.append(argv[argv.index("-o") + 1])
        if identity == runtime["rustc"][:2] and "--crate-name" in argv and "--out-dir" in argv:
            crate = argv[argv.index("--crate-name") + 1]
            assert crate not in compilers
            compilers[crate] = argv
        executed.append(image)
    [output] = outputs
    assert "/ruff_unicode_names2/" in output and Path(output).name == "build_script_build"
    assert executed.index(output) > executed.index(linker_path)
    assert "crates/ruff_unicode_names2/build.rs" in compilers["build_script_build"]
    assert "--emit=dep-info,link" in compilers["build_script_build"]
    assert "crates/ruff_unicode_names2/src/lib.rs" in compilers["unicode_names2"]
    assert "--emit=dep-info,metadata" in compilers["unicode_names2"]


def repeated_instructions(directory):
    """Read complete hardware counters from three ordinary JSON checks of the corrected source."""
    meta = json.loads((directory / "artifacts.json").read_bytes())["ruff"]
    packet = release["joint"]["read"](directory / "combined-ruff.zip", meta["sha256"])
    rows = {}
    for phase in ("fixed-repeat", "fixed-after-forced", "fixed-independent-repeat"):
        prefix = "matched-Ruff/" + phase + "/"
        counts = json.loads(packet[prefix + "pmu.json"])
        raw = [line.split() for line in packet[prefix + "trace/counts.tsv"].decode().splitlines()]
        assert counts == {name: [int(field) for field in values] for name, *values in raw}
        assert counts["root"][1] == 0 and counts["hits"] == [1]
        instructions = {}
        for scope in ("whole", "selected"):
            error, retired, enabled, running = counts[scope]
            assert error == 0 and retired > 0 and enabled == running > 0
            instructions[scope] = retired
        assert 0 < instructions["selected"] < instructions["whole"]
        source = json.loads(packet[prefix + "receipt.json"])
        assert source["exit"] == 0 and source["style"] == "json"
        rows[phase] = {"whole": instructions["whole"], "ron": instructions["selected"]}
    return rows


if __name__ == "__main__":
    phases = ("fixed-repeat", "fixed-repeat-human", "fixed-forced-one-missing",
              "fixed-after-forced", "fixed-independent-repeat")
    result = release["verify"](
        HERE,
        "761ea115605c34f11a1cd29afd68812c1e1359dd",
        "19c379477ec24be16c82b952dc2e892c0563e2c7",
        "035e681081683f4141e4c544b8cf9492b73784051e4541c12bb3cbdb73a798a4",
        "c43d43954ae37b222933baae703bbac6dcb7905de4caaa5e27bef3ecfc1618c3",
        "f23a67771c625785cd70f58e9b46e8d26af3d317",
        41151297839,
        {name: verify_unicode_link for name in phases},
    )
    result["original_work_count_failures"] = list(phases)
    result["retired_user_instructions"] = {
        "three_fix_declared_reader": repeated_instructions(HERE.parent / "release-check"),
        "strict_reader": repeated_instructions(HERE),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
