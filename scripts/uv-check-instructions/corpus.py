"""Exercise metadata-only check histories using sources from Rust's own tests."""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

UI_AREAS = (
    "consts", "closures", "macros", "type-alias-impl-trait", "rpitit",
    "associated-types", "async-await", "layout", "traits", "coroutine",
    "opaque-types", "generic-associated-types",
)
PASS = r"(run-pass|check-pass|build-pass)"
EDIT_REVS = re.compile(r"//@ revisions: +([a-z][a-z0-9_]+) +([a-z][a-z0-9_]+)")

def fixtures(tests, compatibility):
    for path in sorted((tests / "incremental").rglob("*.rs")):
        yield path, False
        if not compatibility:
            yield path, True
    if compatibility:
        return
    for area in UI_AREAS:
        files = [
            src for src in sorted((tests / "ui" / area).rglob("*.rs"))
            if re.search(r"//@ " + PASS, src.read_text(errors="replace"))
        ]
        if len(files) > 80:
            files = [files[i * len(files) // 80] for i in range(80)]
        for path in files:
            yield path, False

    paths = subprocess.check_output(
        ["grep", "-rl", "--include=*.rs", "//@ revisions:", str((tests / "ui").resolve())], text=True,
    ).splitlines()
    for name in sorted(paths):
        path = Path(name)
        if path.suffix != ".rs":
            continue
        text = path.read_text(errors="replace")
        revisions = EDIT_REVS.search(text)
        if revisions and "cfg" in text and re.search(
            r"//[ @]*\[" + revisions[1] + r"\] " + PASS, text
        ):
            yield tests / "ui" / path.relative_to((tests / "ui").resolve()), True

def sha(data):
    return hashlib.sha256(data).hexdigest()

def check(item):
    path, changed = item
    origin = path.relative_to(args.tests)
    source = path.read_text()
    result = dict(fixture=str(origin), edit=changed, source_sha256=sha(source.encode()))
    revision_line = re.search(r"//[@ ]+revisions:\s*(.*)", source)
    revisions = revision_line[1].split() if revision_line else []
    if (origin.parts[0] == "incremental" and not revisions) or (changed and len(revisions) < 2):
        return dict(result, status="inapplicable")
    edition = re.search(r"//[@ ]+edition:\s*(\d+)", source)
    edition = edition[1] if edition else "2015"
    first = re.search(r"//[@ ]+revisions:\s*(\w+)", source)
    cfg = first[1] if first else "testcfg"
    if changed:
        cfg = "cmp_revision"
    with tempfile.TemporaryDirectory(dir=args.scratch) as cwd:
        cwd = Path(cwd)
        file = cwd / "subject.rs" if changed else path
        def compile(rustc, salt, state):
            command = [
                rustc, "--crate-type=rlib", "--error-format=json", "--json=artifacts",
                "-Zohm-shared-stages", "-Zincremental-verify-ich", "--emit=metadata",
                "--crate-name=review", "-Zpublic-api-hash", "-Zquery-dep-graph",
                "--cfg", cfg, "--edition=" + edition, file, "-Cmetadata=" + salt,
                "-Cincremental=incr", "-Zassert-incr-state=" + state,
            ]
            env = dict(os.environ, RUSTC_BOOTSTRAP="1", CARGO_PKG_NAME="review", CARGO_PKG_VERSION="1.0.0")
            proc = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True)
            diagnostics = proc.stderr.replace(str(cwd), "<scratch>").replace(str(args.tests), "<tests>")
            obs = {"exit": proc.returncode}
            if proc.returncode == 0:
                data = (cwd / "libreview.rmeta").read_bytes()
                assert data.startswith(b"rust") and len(data) >= 56
                obs.update(private=data[24:40].hex(), public=data[40:56].hex(), metadata=sha(data))
                diagnostics = "\n".join(sorted(line for line in diagnostics.splitlines() if "artifact" not in line))
            obs["diagnostics"] = sha(diagnostics.encode())
            return obs, diagnostics

        def set_source(i):
            if changed:
                expr = r'(?<!")\b' + re.escape(revisions[i]) + r'\b(?!")'
                file.write_text(re.sub(expr, cfg, source))

        set_source(0)
        salt = "a" if args.mode == "salt" else "b"
        prime, da = compile(args.other or args.rustc, salt, "not-loaded")
        if prime["exit"]:
            return dict(result, status="prime-failed", exit=prime["exit"])
        if args.mode == "compat":
            warm = prime
        else:
            set_source(1)
            warm, da = compile(args.rustc, "b", "loaded")
        shutil.rmtree(cwd / "incr")
        fresh, db = compile(args.rustc, "b", "not-loaded")
        result.update(status="same" if warm == fresh else "different", warm=warm)
        if warm != fresh:
            result["fresh"] = fresh
        if da != db:
            result.update(log_warm=da, log_fresh=db)
        return result

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("rustc", type=Path)
parser.add_argument("tests", type=Path, help="tests directory in the #449 Rust source tree")
parser.add_argument("mode", choices=("salt", "fixed", "compat"))
parser.add_argument("--other", type=Path, help="other compiler for fresh-against-fresh comparison")
parser.add_argument("--scratch", type=Path)
parser.add_argument("--jobs", type=int, default=2)
args = parser.parse_args()
if bool(args.other) != (args.mode == "compat"):
    parser.error("supply --other with compat mode only")
args.rustc = args.rustc.resolve()
args.tests = args.tests.resolve()
if args.other:
    args.other = args.other.resolve()
if args.scratch:
    args.scratch = args.scratch.resolve()
with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
    for result in pool.map(check, fixtures(args.tests, args.mode == "compat")):
        print(json.dumps(result), flush=True)
