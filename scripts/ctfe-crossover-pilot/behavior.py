"""Run the genuine Cargo-produced CLI on the frozen PYI009 controls, outside every counter."""

import hashlib
import importlib.util
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
PATH = HERE.parent / "ctfe-cli-semantic/cases.py"
spec = importlib.util.spec_from_file_location("donor_sealed_semantic_cases", PATH)
cases = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cases)


def run(cli, cwd, env, semantic, whole):
    with cli.open("rb") as elf:
        if hashlib.file_digest(elf, "sha256").hexdigest() != whole:
            raise ValueError("different Cargo CLI before native cases")
    result = {}
    for name in cases.CASES:
        args = [str(cli), *cases.argv(name)]
        v = subprocess.run(
            args, input=cases.SOURCE, cwd=cwd, env=env, capture_output=True, timeout=30
        )
        cases.verdict(name, semantic, v.returncode, v.stdout, v.stderr, cwd)
        result[name] = {
            "argv": args,
            "cwd": str(cwd),
            "stdin": cases.sha(cases.SOURCE),
            "exit": v.returncode,
            "stdout": v.stdout.hex(),
            "stderr": v.stderr.hex(),
            "elf": whole,
        }
    return result


def verify(data, cwd, cli, semantic, whole):
    cases.need(set(data) == set(cases.CASES), "wrong CLI control roster")
    for name, row in data.items():
        cases.need(
            row["argv"] == [str(cli), *cases.argv(name)]
            and row["cwd"] == str(cwd)
            and row["elf"] == whole
            and row["stdin"] == cases.sha(cases.SOURCE),
            "wrong Cargo executable or oracle inputs",
        )
        cases.verdict(
            name,
            semantic,
            row["exit"],
            bytes.fromhex(row["stdout"]),
            bytes.fromhex(row["stderr"]),
            cwd,
        )
