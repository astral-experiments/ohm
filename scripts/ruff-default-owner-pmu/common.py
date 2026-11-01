"""Frozen product, workflow, and ordinary command for the attribution-only diagnostic."""

import gzip
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
BRANCH = "charlie/qa-ruff-first-a-leaves-20261101"
REPO = "astral-experiments/ohm"
COLLECTOR = "8a659140df8ab27fd6a8cc61f5eb38717b3f8bbc"
CONTRACT = "42ab30fd5e6bcdcf908df81de9baac65ca64fbf9"
JOB = "Signed GNU Ruff first-A hardware instruction leaves"
ARTIFACT = "signed-gnu-ruff-first-a-instruction-leaves"
SAMPLER = "f5667dc0aa2083961065a3a947b06a091e00af98"
LAST_OWNER = dict(run=41349209691, job=124975532927, artifact=13100907533,
                  digest="sha256:fa0b3bf462528e8a0bef968ffd04aa99e4aeb8f3477d903ad2ea8f4904a6bd06",
                  boot="2ddd5b99-7fe4-4545-8e63-63f687a36969", runner="nsc-runner-f85r66gs8g04s",
                  runner_id=1385, ended="2026-11-01T21:07:13Z")
PREVIOUS = 41336398017
PREVIOUS_HEAD = "3c206e8bf2c2236c035f1e8f352d9ad547d69ef7"
BLOCKED_JOBS = (124937039974, 124937040076, 124937040027, 124937040042, 124937039985, 124937039779)
REFUSED = dict(run=41346940188, job=124968691232, artifact=13100172316,
               digest="sha256:478477d4a73271fdab470c5da3ceae5b3b3a2e0dbacf321b2f260e8390314f34",
               boot="e77e07dd-2fe9-4e31-8b24-83458644e258", runner="nsc-runner-9gc9c85qfst6q",
               runner_id=1382, ended="2026-11-01T20:41:07Z")
CMD = [
    "cargo",
    "+ohm",
    "build",
    "-p",
    "ruff",
    "--bin",
    "ruff",
    "--locked",
    "--offline",
    "-j4",
    "--message-format=json",
]
PHASES = {
    "reference": ("B", "A"),
    "plain-1": ("B", "A"),
    "attributed": ("B", "A", "unchanged", "invalid", "repair"),
    "plain-2": ("B", "A"),
    "empty-invalid": ("invalid", "repair"),
}
EXPECTED = {"A": "b5dba861cc38e3f7fb4524c9ceba3e01a474ea13", "B": "7b13f01ba1569887a25670820764b24c206da8e5"}
INVALID = b"\nconst ohm_branch_switch_invalid: () = 1u32;\n"
TREES = {"A": "2b61306d708a211b3725c8d920e7590be6da41ad", "B": "97ca36909f1ae8fa028b2c1f48f452fbdcdbbd4c"}
BRANCHES = {"A": "historical-parent", "B": "historical-feature"}
PARSER_SHAS = {
    False: "ee24a1933840a400c4730778a5c222d30c36d4b1b4f96bd97b502acfc07a4875",
    True: "3fbac7f54be2b5cd47eee1993f11e6d58724e32301c0ba3e5afb624562283ab5",
}
PARSER = "crates/ruff_python_parser/src/lib.rs"
SDK = json.loads((HERE / "signed-sdk.json").read_bytes())


def need(condition, why):
    if not condition:
        raise ValueError(why)


def sha(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def save(path, value):
    b = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    with path.open("xb") as f:
        f.write(gzip.compress(b, mtime=0) if path.suffix == ".gz" else b)


def read(path):
    return json.loads(gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes())


def git(repo, *options):
    return subprocess.check_output(["git", "--no-optional-locks", "-C", repo, *options])
