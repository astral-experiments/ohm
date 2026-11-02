"""Focused custody, clock, corpus and actual native selector controls."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("RUNNER_TEMP", tempfile.gettempdir())
import study as p
import worker as w
import reopen as r
import setup


def refuses(op):
    try:
        op()
    except (ValueError, AssertionError):
        return
    raise AssertionError("corrupted control passed")


def main(repo, recorder):
    gold = p.source_pair(repo)
    p.need(
        len(gold[p.OLD][p.KEY]) == 463
        and len(gold[p.NEW][p.KEY]) == 722
        and gold[p.OLD][p.SIBLING] == gold[p.NEW][p.SIBLING],
        "genuine historical option outputs",
    )
    corrupted = (
        p.git(repo, "show", p.NEW + ":" + p.OPTIONS)
        .decode()
        .replace("For more information on the glob syntax", "For less information on the glob syntax")
    )
    refuses(lambda: p.expected_outputs(p.NEW, corrupted))
    clock = {"code": 0, "event_errno": 0, "instructions": 100, "enabled": 13, "running": 13}
    p.need(r.strict_clock(clock, 0) == 100, "reference clock")
    for wrong in ({"event_errno": 2}, {"enabled": 12}, {"instructions": 0}, {"code": 101}):
        refuses(lambda: r.strict_clock({**clock, **wrong}, 0))
    invalid = {
        "reason": "compiler-message",
        "target": {"name": p.OWNER},
        "message": {
            "code": {"code": "E0308"},
            "level": "error",
            "spans": [
                {"is_primary": True, "file_name": p.OPTIONS, "text": [{"text": p.INVALID.decode().strip()}]}
            ],
        },
    }
    terminal = {"reason": "build-finished", "success": False}
    p.results([invalid, terminal], False)
    refuses(lambda: p.results([{**invalid, "target": {"name": "ruff_linter"}}, terminal], False))
    refuses(lambda: p.results([terminal], False))
    graph = {
        "version": 1,
        "roots": [0],
        "units": [
            {
                "pkg_id": "path+file:///fixture",
                "mode": "build",
                "dependencies": [],
                "target": {
                    "name": p.OWNER,
                    "kind": ["lib"],
                    "crate_types": ["lib"],
                    "src_path": "/fixture/lib.rs",
                },
                "features": [],
            }
        ],
    }
    p.need(sum(w.graph_units(graph).values()) == 1, "graph")
    refuses(lambda: w.graph_units({**graph, "units": graph["units"] * 2}))
    with tempfile.TemporaryDirectory(prefix="ohm-option-controls-") as tmp:
        base = Path(tmp)
        target = base / "target"
        target.mkdir()
        deps = base / "build"
        deps.mkdir()
        actual = deps / "libruff_workspace-abcdef.rlib"
        promoted = target / "libruff_workspace.rlib"
        args = base / "actor"
        args.mkdir()
        (args / "original.nul").write_bytes(
            b"rustc\0--out-dir\0" + os.fsencode(deps) + b"\0-C\0extra-filename=-abcdef\0"
        )
        row = {"target": {"name": p.OWNER, "kind": ["lib"]}, "filenames": [str(promoted)]}
        actual.write_bytes(b"a")
        promoted.write_bytes(b"a")
        p.need(w.roots_for(row, args, base) == (promoted, actual), "byte-identical promoted copy")
        promoted.write_bytes(b"b")
        refuses(lambda: w.roots_for(row, args, base))
        # Use the historical executable fixture with this study's one changed predicate.
        orig = (setup.CGU / "test_capture.py").read_text()
        replacements = {
            '("ordinary", "observe", "ruff_linter", helper, True)': '("ordinary", "observe", "ruff_workspace", helper, True)',
            '("scope", "capture", "ruff_linter", helper, True)': '("scope", "capture", "ruff_linter", helper, False)',
            '("other-inode", "capture", "ruff_linter", other, False)': '("other-inode", "capture", "ruff_workspace", other, False)',
            "Both target owners, observation, distinct-inode, unselected crate, and missing request passed.": "Workspace-only mutation, both pass-through cases, physical inode, observed argv and absent request passed.",
        }
        for a, b in replacements.items():
            p.need(orig.count(a) == 1, "changed historical fixture")
            orig = orig.replace(a, b)
        adapted = base / "native-fixture.py"
        adapted.write_text(orig)
        subprocess.run([sys.executable, "-IB", adapted, recorder], check=True)
    subprocess.run([sys.executable, "-IB", setup.CGU / "test_files.py"], check=True)
    print(
        "Historical fields, wrong-option, wrong-crate/diagnostic, scaled/failed clocks, missing graph unit, contradictory promoted archive and physical native controls passed."
    )


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve(strict=True), Path(sys.argv[2]).resolve(strict=True))
