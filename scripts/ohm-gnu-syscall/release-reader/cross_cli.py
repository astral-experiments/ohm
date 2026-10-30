"""Compare the released and integrated readers under two exact compilers on the Ruff CLI edit."""
import json
import os
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]
from subjects import ORIGINAL, SIGNED, SOURCES, registered, rt, select_cargo
import paired
from paired import census, cli


def main():
    writer, reader = sys.argv[1:]
    assert writer in ("register", "syscall") and reader in ("signed", "integrated")
    base = Path(os.environ["CENSUS_PARENT"]) if writer == "register" else rt.ROOT / "candidate-sdk"
    stable = rt.ROOT / "installed-ruff-sdk"
    shutil.copytree(base, stable, symlinks=True, copy_function=os.link)
    os.environ["CENSUS_SDK"] = str(stable)
    if writer == "register":
        os.environ.pop("CENSUS_CANDIDATE_RECORD", None)
    else:
        os.environ["CENSUS_CANDIDATE_RECORD"] = str(rt.LOG / "candidate.json")
    original = census.acquire
    def switch(*args):
        work, out, src, env = original(*args)
        old = census.sha(stable / "bin/cargo")
        assert old == ORIGINAL
        key = select_cargo(stable, reader)
        source = SOURCES["released" if reader == "signed" else "integrated"]["commit"]
        version = census.command(["cargo", "+ohm", "-Vv"], src, env)
        assert source in version and census.sha(stable / "bin/cargo") == key
        common = json.loads((HERE.parents[1] / "ohm-aarch64-portable-review/source/sdk-members.json").read_bytes())
        record = census.sha(base / common["driver_path"])
        for name, (digest, size, mode) in common["common"].items():
            p = stable / name
            assert p.stat().st_mode & 0o777 == mode
            if name == "bin/cargo":
                assert census.sha(p) == (SIGNED if reader == "signed" else registered()["elf_sha256"])
            else:
                assert census.sha(p) == digest and p.stat().st_size == size
        assert record == census.sha(stable / common["driver_path"])
        rt.save(out / "actual-reader.json", {"reader": reader, "writer": writer, "git": source, "cargo": key,
                "rustc_driver": record, "verified_sdk_members": len(common["common"]) + 1, "version": version})
        return work, out, src, env
    census.acquire = switch
    product = cli.cli_product
    def retain(exe, old, dest, src, env):
        result = product(exe, old, dest, src, env)
        paired.retain_elf(exe, result, dest, rt.LOG / "complete-elf/chunks")
        return result
    cli.cli_product = retain
    cli.main()
    out = Path(os.environ["CENSUS_ROOT"]) / "receipts"
    phases = json.loads((out / "terminal.json").read_bytes())["phases"]
    assert set(phases) == {"cold", "edit", "repeat", "invalid", "repair", "empty-new"}
    assert phases["invalid"]["diagnostic"] == "E0425"
    for phase in ("edit", "repeat", "repair"):
        assert phases[phase]["product"] == phases["empty-new"]["product"], (phase, phases[phase])
    assert phases["cold"]["product"]["sha256"] != phases["edit"]["product"]["sha256"]
    key = rt.sha(stable / "bin/cargo")
    assert key == (SIGNED if reader == "signed" else registered()["elf_sha256"])
    rt.save(rt.LOG / "release-cli-terminal.json", {"actual": json.loads((out / "actual-reader.json").read_bytes()),
            "phases": phases, "original_terminal": rt.sha(out / "terminal.json")})


if __name__ == "__main__":
    main()
