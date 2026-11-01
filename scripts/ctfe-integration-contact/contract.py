"""Source identities, off-window boundaries and the unscored continuation rule."""

import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
BRANCH = "charlie/qa-donor-integration-xb-contact-20261101"
COMMAND = [
    "cargo",
    "+ohm",
    "test",
    "-p",
    "ruff",
    "--test",
    "integration_test",
    "--no-run",
    "--locked",
    "--offline",
    "-j4",
    "--message-format=json",
]
BUILD = [
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
F_HEAD = "679e72fedd4968636469d958c38225c0ce3fefab"
KERNEL = "19f9a67b032cce44cea1e3bb7e324558cd9abd0a"
CTFE = "a333316177ef3f9c8b3264ca3bf76c451e0ca079"
ARMS = ("Eon", "Don")
EMPTY = ("clean-A", "clean-B", "clean-edited", "clean-semantic")
HISTORY = ("Y-B", "X-A", "X-B", "comment", "unchanged", "invalid", "repair")
PHASES = EMPTY + HISTORY


def need(value, reason):
    if not value:
        raise ValueError(str(reason))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git(repo, *args):
    return (
        subprocess.check_output(["git", "--no-optional-locks", "-C", repo, *args])
        .decode()
        .strip()
    )


def packages():
    ctfe = Path(os.environ["CTFE_CARRIER"]).resolve(strict=True)
    f = Path(os.environ["INTEGRATION_CARRIER"]).resolve(strict=True)
    for repo, head in ((ctfe, CTFE), (f, F_HEAD)):
        need(git(repo, "rev-parse", "HEAD") == head, ("wrong source checkout", repo))
    sys.path.insert(0, str(ctfe / "scripts/ctfe-crossover-pilot"))
    import source_guard

    source_guard.pilot(ctfe, CTFE)
    source_guard.tree(ctfe, CTFE, "scripts/gnu-same-revision-donor")
    source_guard.tree(ctfe, CTFE, "scripts/ctfe-cli-semantic")
    prefix = "scripts/ruff-integration-structure"
    source_guard.tree(f, F_HEAD, prefix)
    sys.path.insert(0, str(f / prefix))
    import selection
    import suite

    need(
        Path(selection.__file__).resolve() == f / prefix / "selection.py"
        and Path(suite.__file__).resolve() == f / prefix / "suite.py",
        "wrong integration helpers",
    )
    return ctfe, selection, suite


def check_source(reviewed):
    ctfe, _, _ = packages()
    import source_guard

    head = git(HERE, "rev-parse", "HEAD")
    need(head == reviewed, "unreviewed contact")
    files = source_guard.tree(
        HERE.parents[1], head, "scripts/" + HERE.name, (".github/workflows/ci.yml",)
    )
    expected = {Path(f).name for f in files if f.startswith("scripts/")} - {
        "SHA256SUMS"
    }
    expected.add("../../.github/workflows/ci.yml")
    seen = set()
    for line in (HERE / "SHA256SUMS").read_text().splitlines():
        digest, filename = line.split("  ", 1)
        need(
            filename in expected
            and filename not in seen
            and sha((HERE / filename).read_bytes()) == digest,
            ("unregistered or incorrect checksum", filename),
        )
        seen.add(filename)
    need(seen == expected, "manifest omitted an input")
    return ctfe


def install_boundary(execs):
    for row in execs:
        name = Path(row["exe"]).name
        need(
            not re.fullmatch(r"(?:integration_test|ruff)(?:-[0-9a-f]{16})?", name),
            ("subject executed a selected native product", row["pid"], row["exe"]),
        )


def reference(phase):
    if phase in ("clean-semantic", "dirty-X-B"):
        return "clean-semantic"
    if phase in ("clean-A", "X-A"):
        return "clean-A"
    if phase in ("clean-B", "Y-B", "X-B"):
        return "clean-B"
    need(phase in PHASES and phase != "invalid", "no native reference for this phase")
    return "clean-edited"


def identities(physical):
    def identity(row):
        argv = row["argv"]
        types = [argv[i + 1] for i, a in enumerate(argv) if a == "--crate-type"]
        types += [a.split("=", 1)[1] for a in argv if a.startswith("--crate-type=")]
        return [
            row["crate"],
            ",".join(sorted(types)) or "<implicit>",
            "--test" in argv if row["mode"] == "full" else None,
        ]

    rustcs = {r["event"]: identity(r) for r in physical["rustcs"]}
    need(len(rustcs) == len(physical["rustcs"]), "duplicate installed rustc event")
    return dict(
        full=sorted(
            [rustcs[r["event"]] for r in physical["rustcs"] if r["mode"] == "full"],
            key=str,
        ),
        link_only=sorted(
            [r["crate"] for r in physical["rustcs"] if r["mode"] == "link-only"]
        ),
        wild=sorted(
            [rustcs[r["rustc_event"]][:2] for r in physical["wild_processes"]], key=str
        ),
    )


def link_outputs(physical):
    def canonical(path):
        p = Path(path)
        # The same actual project output can carry a Cargo unit disambiguator.
        return re.sub(r"-[0-9a-f]{16}(?=\.|$)", "", p.name)

    owners = {r["event"]: r["crate"] for r in physical["rustcs"]}
    return sorted(
        owners[r["rustc_event"]] + "::" + canonical(r["output"])
        for r in physical["wild_processes"]
    )


def semantics():
    head = "0b50022990577aadd904731e51c4d6c2a0f9b665"
    repo = Path(os.environ["SEMANTIC_CARRIER"]).resolve(strict=True)
    need(git(repo, "rev-parse", "HEAD") == head, "different semantic oracle")
    import source_guard

    source_guard.tree(repo, head, "scripts/ctfe-cli-semantic")
    import importlib.util

    file = repo / "scripts/ctfe-cli-semantic/cases.py"
    spec = importlib.util.spec_from_file_location("ctfe_original_pyi009", file)
    cases = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cases)
    return cases


def operand_files(owners, providers, file_sha):
    paths = {
        v
        for owner in owners.values()
        for arg in owner["externs"].values()
        for v in arg.values()
        if v
    }
    paths.update(r["path"] for r in providers.values())
    paths.update(v for r in providers.values() for v in r["actual_rmeta"])
    result = {}
    for name in sorted(paths):
        p = Path(name)
        st = p.stat()
        result[name] = [st.st_dev, st.st_ino, st.st_size, file_sha(p)]
    return result


def excluded_boot(boot):
    import json

    records = json.loads((HERE / "excluded-boots.json").read_bytes())
    need(
        re.fullmatch(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}", boot)
        and all(boot not in r["boots"] for r in records.values()),
        "duplicate or invalid host boot",
    )


def fresh_runner(boot, runner):
    import json

    excluded_boot(boot)
    prior = json.loads((HERE / "contact-exclusions.json").read_bytes())
    need(
        boot not in prior["boots"]
        and re.fullmatch(r"nsc-runner-[a-z0-9]+", runner)
        and runner not in prior["runners"],
        "previously enrolled runner or boot",
    )
