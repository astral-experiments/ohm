"""Offline source, native and adversarial admission tests. Optional arguments reopen real historical media."""

import argparse
import copy
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import shutil
import sys
import tempfile
import unittest
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cases as s
import exercise
import read

BASE = PurePosixPath("/home/runner/work/_temp/ohm-branch-object-qa")
SDK = BASE / "home/.rustup/toolchains/ohm"
CLI = str(BASE / "work/target/debug/ruff")
OUT = BASE / "work/build/workspaces/ws/v2-test/ruff/0/out"


def native_rows():
    r = str(SDK / "bin/rustc")
    w = str(SDK / s.WILD)
    owner = dict(
        pid=4,
        exe=r,
        argv=[r, "--crate-name", "ruff", "--crate-type", "bin", "--out-dir", str(OUT)],
        crate="ruff",
        mode="full",
    )
    ast = dict(pid=5, exe=r, argv=[r, "--crate-name", "ruff_python_ast"], crate="ruff_python_ast", mode="full")
    wild = dict(pid=6, exe=w, argv=[w, "-o", str(OUT / "ruff")], output=str(OUT / "ruff"))
    return [owner, ast], [wild]


class Controls(unittest.TestCase):
    def test_all_native_status_and_diagnostic_changes(self):
        cwd = "/private/task"
        for edited in (True, False):
            for case in s.CASES:
                warning = case == "qno-as-pyi" or case == "pyi" and not edited
                value = (
                    [s.REFERENCE["diagnostic"] | {"filename": cwd + "/dev_loop." + s.CASES[case][0]}]
                    if warning
                    else []
                )
                result = json.dumps(value).encode()
                s.verdict(case, edited, int(warning), result, b"", cwd)
                for code, blob, err in (
                    (1 - int(warning), result, b""),
                    (int(warning), result, b"warning"),
                    (int(warning), b"[]" if warning else b"[{}]", b""),
                ):
                    with self.assertRaises(ValueError):
                        s.verdict(case, edited, code, blob, err, cwd)
                if warning:
                    with self.assertRaises(ValueError):
                        s.verdict(case, edited, 1, result.replace(cwd.encode(), b"/other"), b"", cwd)
        self.assertNotEqual(s.argv("pyi"), s.argv("pyi-as-py"))

    def test_link_pid_output_and_false_owner(self):
        rs, ws = native_rows()
        self.assertEqual(s.link_rows(rs, ws, CLI, SDK, "edit"), (rs[0], ws[0]))
        for rustcs, wilds, cli in (
            (rs[:1], ws, CLI),
            (rs, [], CLI),
            (rs, 2 * ws, CLI),
            (rs, [ws[0] | {"output": "/tmp/ruff"}], CLI),
            (rs, [ws[0] | {"exe": "/usr/bin/ld"}], CLI),
            (rs, ws, str(BASE / "work/build/debug/ruff")),
        ):
            with self.assertRaises(ValueError):
                s.link_rows(rustcs, wilds, cli, SDK, "edit")
        s.link_rows(rs[:1], ws, CLI, SDK, "revert")

    def test_same_bytes_different_inode_and_link_destination(self):
        with tempfile.TemporaryDirectory(prefix="ctfe-link-output-") as d:
            folder = Path(d).resolve()
            linked = folder / "out"
            cli = folder / "ruff"
            copy = folder / "copy"
            linked.write_bytes(b"real native payload")
            cli.hardlink_to(linked)
            copy.write_bytes(linked.read_bytes())
            digest = s.sha(linked.read_bytes())
            s.require_same_output(cli, linked, digest)
            with self.assertRaises(ValueError):
                s.require_same_output(cli, copy, digest)
            with self.assertRaises(ValueError):
                s.require_same_output(cli, linked, s.sha(b"stale"))
            cli.unlink()
            cli.symlink_to(linked)
            with self.assertRaises(ValueError):
                s.require_same_output(cli, linked, digest)

    def test_independently_closed_exec(self):
        text = '21 execve("/x", ["/x", "a"], 0x1 <unfinished ...>\n21 <... execve resumed>) = 0\n22 execve("/bad", [], 0x0) = -1 ENOENT (missing)\n'
        self.assertEqual(read.exec_records(text), [(21, "/x", ["/x", "a"])])
        for wrong in (
            text.splitlines()[0],
            text.splitlines()[1],
            text.replace('"/x", [', "0x3, ["),
            text.replace("execve(", "execveat("),
        ):
            with self.assertRaises((ValueError, SyntaxError)):
                read.exec_records(wrong)

    def test_unmodified_repeat_and_clean_history(self):
        rows = {
            k: dict(
                source={"b": k in s.EDITED},
                native={"cli": {"whole": "changed" if k in s.EDITED else "old"}},
                stub={"pyi": int(k not in s.EDITED)},
            )
            for k in s.PHASES
        }
        rows["X-A"]["native"]["cli"]["whole"] = "parent"
        read.same_history(rows)
        for phase, field, val in (
            ("repeat", "source", {"b": False}),
            ("edit", "native", rows["Y-B"]["native"]),
            ("repair", "stub", rows["Y-B"]["stub"]),
            ("revert", "native", rows["edit"]["native"]),
            ("empty-edit", "native", rows["Y-B"]["native"]),
        ):
            bad = copy.deepcopy(rows)
            bad[phase][field] = val
            with self.assertRaises(ValueError):
                read.same_history(bad)

    def test_physical_root_collision_before_reset(self):
        with tempfile.TemporaryDirectory(prefix="ctfe-roots-") as d:
            root = Path(d).resolve()
            paths = [root / "target", root / "build"]
            for p in paths:
                p.mkdir()
            self.assertEqual(len(s.physical_roots(paths, empty=True)), 2)
            with self.assertRaises(ValueError):
                s.physical_roots([paths[0], paths[0]], empty=False)
            paths[1].rmdir()
            paths[1].symlink_to(paths[0], target_is_directory=True)
            with self.assertRaises(ValueError):
                s.physical_roots(paths, empty=False)
            paths[1].unlink()
            paths[1].mkdir()
            (paths[0] / "foreign").write_bytes(b"keep")
            with self.assertRaises(ValueError):
                s.physical_roots(paths, empty=True)
            self.assertEqual((paths[0] / "foreign").read_bytes(), b"keep")

    def test_separate_roots_and_genuine_Cargo_bin(self):
        env = dict(
            CARGO_TARGET_DIR=str(BASE / "work/target"),
            CARGO_BUILD_BUILD_DIR=str(BASE / "work/build"),
            CARGO_ENCODED_RUSTFLAGS="-Zohm-branch-cache=yes",
            CARGO_NET_OFFLINE="true",
        )
        s.roots(env, BASE)
        with self.assertRaises(ValueError):
            s.roots(env | {"CARGO_BUILD_BUILD_DIR": env["CARGO_TARGET_DIR"]}, BASE)
        e = dict(
            reason="compiler-artifact",
            target={"name": "ruff", "kind": ["bin"]},
            executable=CLI,
            filenames=[CLI],
        )
        self.assertEqual(read.cargo_roots([e], BASE), CLI)
        for row in (
            e | {"executable": str(OUT / "ruff")},
            e | {"filenames": ["/tmp/ruff"]},
            e | {"filenames": [str(OUT / "../foreign")]},
        ):
            with self.assertRaises(ValueError):
                read.cargo_roots([row], BASE)


def real_route(donor):
    """Only the two historical source files are checked out from the existing Git object store."""
    with tempfile.TemporaryDirectory(prefix="ctfe-stub-route-") as temp:
        root = Path(temp)
        repo = root / "subject"
        subprocess.run(["git", "init", "--quiet", "--template=", repo], check=True)
        objects = s.git(donor, "rev-parse", "--path-format=absolute", "--git-path", "objects").decode().strip()
        (repo / ".git/objects/info/alternates").write_text(objects + "\n")
        shallow = Path(
            s.git(donor, "rev-parse", "--path-format=absolute", "--git-path", "shallow").decode().strip()
        )
        if shallow.is_file():
            shutil.copyfile(shallow, repo / ".git/shallow")
        s.git(repo, "config", "core.sparseCheckout", "true")
        (repo / ".git/info").mkdir(exist_ok=True)
        (repo / ".git/info/sparse-checkout").write_text("/" + s.AST + "\n/" + s.PARSER + "\n")
        for k in ("A", "B"):
            s.git(repo, "branch", s.NAMES[k], s.REVS[k])
        s.git(repo, "switch", "--quiet", s.NAMES["B"])
        result = {}
        for phase in s.PHASES:
            s.advance(repo, phase)
            row = s.snapshot(repo, phase)
            s.check_source(row, phase)
            result[phase] = {"ast": row["ast"], "parser": row["parser"], "modified": row["modified"]}
            if phase == "edit":
                previous = row
            if phase == "repeat":
                s.need(row == previous, "real unchanged source was touched")
                (repo / s.AST).write_bytes((repo / s.AST).read_bytes() + b"\n")
                try:
                    s.snapshot(repo, phase)
                except ValueError:
                    pass
                else:
                    raise ValueError("accepted another source edit")
                (repo / s.AST).write_bytes(s.altered(s.git(repo, "show", "HEAD:" + s.AST)))
        return result


def historical(archive):
    ref = s.REFERENCE
    with archive.open("rb") as file:
        s.need(
            archive.stat().st_size == ref["archive_bytes"]
            and hashlib.file_digest(file, "sha256").hexdigest() == ref["archive_sha256"],
            "wrong original source ZIP",
        )
    with zipfile.ZipFile(archive) as z:
        cases = {}
        pre = "measured/Eon/main/invalid"
        original_events = [json.loads(line) for line in read.raw(z, pre, "cargo.stdout.gz").splitlines()]
        read.parser_error(z, pre, original_events)
        for branch in ("A", "B"):
            native = read.old.replay_native.native_verdict(z, "clean/Eon/" + branch, branch)
            if branch == "B":
                s.need(
                    (native["cli"]["whole"], native["cli"]["size"]) == (ref["whole_elf"], ref["bytes"]),
                    "wrong retained known Ruff",
                )
            cases[branch] = {
                "cli": native["cli"]["whole"],
                "outcome": exercise.replay(z, native, s.REVS[branch], False),
                "typed": native["typed"],
            }
        try:
            exercise.replay(z, native, s.REVS["B"], True)
        except ValueError as error:
            s.need("wrong native PYI009 verdict" in str(error), "unexpected stale-binary refusal")
        else:
            raise ValueError("unmodified old executable passed as edited")
        return cases


def historical_link(archive):
    with archive.open("rb") as source:
        s.need(
            archive.stat().st_size == 309332766
            and hashlib.file_digest(source, "sha256").hexdigest()
            == "aeef5d5226815f3d5cd8a11210a1f2265ee1291214e5e885eddee1dc2c3cbb65",
            "wrong physical trace archive",
        )
    name = "structural/Koff/first-B"
    with zipfile.ZipFile(archive) as z:
        native = read.data(z, name + "/native-execs.json.gz")
        events = read.exec_records(read.raw(z, name, "exec.raw.gz").decode())
        r, w = s.link_rows(native["rustcs"], native["wild_processes"], CLI, SDK, "edit")
        s.need(
            all((x["pid"], x["exe"], x["argv"]) in events for x in (r, w)),
            "historical compiler or writer not in raw source",
        )
        return {"rustc": r["pid"], "wild": w["pid"], "output": w["output"], "execs": len(events)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--old-cli", type=Path)
    parser.add_argument("--old-link", type=Path)
    opt = parser.parse_args()
    tested = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(Controls))
    if not tested.wasSuccessful():
        sys.exit(1)
    result = {"tests": tested.testsRun}
    if opt.repo:
        result["source"] = real_route(opt.repo)
    if opt.old_cli:
        result["real_cli"] = historical(opt.old_cli)
    if opt.old_link:
        result["real_link"] = historical_link(opt.old_link)
    print(json.dumps(result, sort_keys=True, indent=2))
