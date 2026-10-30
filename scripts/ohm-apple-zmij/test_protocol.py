"""Portable negative tests for native receipts, command forwarding and the preregistered estimator."""

import hashlib
import itertools
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import study
from calibrate import classify, fields
from cohort import summarize
from measure import typed
from objects import archive_evidence, bag
from pilot import has_output
from prepare import freeze_stage, identity_digest, role_files
from wrapper import WrapperTrace, compiler_selector


class Protocol(unittest.TestCase):
    def test_balanced_order(self):
        seed = f"ohm/Apple-zmij/confirm/1:{study.ARCHIVE_SHA}:{study.EDIT}"
        value = int.from_bytes(hashlib.sha256(seed.encode()).digest(), "big")
        all_orders = list(itertools.combinations(range(12), 6))
        self.assertLess(value, 2**256 - 2**256 % len(all_orders))
        picked = all_orders[value % len(all_orders)]
        self.assertEqual(study.ORDERS["confirm"], ["PC" if i in picked else "CP" for i in range(12)])
        self.assertEqual(study.ORDERS["screen"], ["PC", "CP"])

        def rows(ratio):
            return [
                {
                    r: {s: {"cargo": {"ns": v}} for s in ("edit", "repeat-1", "repeat-2")}
                    for r, v in zip("PC", (ratio, 1))
                }
                for _ in range(12)
            ]

        result = summarize(rows(3), study.ORDERS["confirm"])["repeat-1"]
        self.assertEqual((result["assignments"], result["median_CI_96.14pct"]), (924, [3, 3]))
        self.assertEqual(result["one_sided_balanced_sharp_2x_p"], 1 / 924)
        self.assertEqual(
            summarize(rows(2), study.ORDERS["confirm"])["repeat-1"]["one_sided_balanced_sharp_2x_p"], 1.0
        )

    def test_counter_scope(self):
        def rows(levels):
            return [
                {
                    "depth": d,
                    "iters": n,
                    "instructions": 1000 + (2 * n if d in levels else 0),
                    "user": 0.12 if n else 0,
                }
                for d in range(3)
                for n in [0, 200_000_000] * 3
            ]

        self.assertEqual(
            classify(rows([0, 1, 2]), 200_000_000)["retired_instruction_scope"], "whole-tree-calibrated"
        )
        self.assertEqual(classify(rows([0]), 200_000_000)["retired_instruction_scope"], "direct-process-only")
        self.assertEqual(
            classify(rows([]), 200_000_000)["retired_instruction_scope"], "unavailable-or-inconclusive"
        )
        self.assertEqual(
            fields("  0.22 real  0.07 user  0.12 sys\n    10000 instructions retired\n"),
            {"wall": 0.22, "user": 0.07, "system": 0.12, "instructions": 10000},
        )

    def test_profile_is_a_typed_dimension(self):
        def art(opt):
            return {
                "reason": "compiler-artifact",
                "package_id": "unicode-ident",
                "target": {"name": "unicode_ident", "kind": ["lib"]},
                "features": [],
                "profile": {"opt_level": opt},
                "fresh": opt == "0",
            }

        def data(seq):
            return b"\n".join(
                json.dumps(r).encode() for r in [*seq, {"reason": "build-finished", "success": True}]
            )

        a, d, _, _ = typed(data([art("0"), art("1")]), True)
        self.assertEqual((len(a), len(d)), (2, 1))
        with self.assertRaises(RuntimeError):
            typed(data([art("0"), art("0")]), True)
        with self.assertRaises(RuntimeError):
            typed(data([art("0")]), False)

    def test_metadata_and_macho_are_distinct(self):
        def member(name, payload):
            n = name.encode()
            b = n + payload
            h = (
                f"#1/{len(n)}".ljust(16)
                + "0".ljust(12)
                + "0".ljust(6)
                + "0".ljust(6)
                + "100644".ljust(8)
                + str(len(b)).ljust(10)
                + "\x60\n"
            ).encode()
            return h + b + (b"\n" if len(b) % 2 else b"")

        def body(v):
            macho = bytes.fromhex("cffaedfe0c0000010000000001000000") + b"opaque"
            return b"!<arch>\n" + member("lib.rmeta", v) + member("long-owned-compiler-output.o", macho)

        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "x.rlib"
            p.write_bytes(body(b"version1"))
            a = archive_evidence(p)
            p.write_bytes(body(b"version2"))
            b = archive_evidence(p)
            self.assertEqual(bag(a), bag(b))
            self.assertNotEqual(a["archive_metadata"], b["archive_metadata"])
            p.write_bytes(body(b"version2")[:-6])
            with self.assertRaises(RuntimeError):
                archive_evidence(p)

    def test_filename_and_fds_survive_wrapper(self):
        w = Path(__file__).with_name("wrapper.py")
        with tempfile.TemporaryDirectory() as td:
            r, fd = os.pipe()
            try:
                os.write(fd, b"Z")
                env = dict(
                    os.environ,
                    QA_APPLE_REAL_RUSTC=sys.executable,
                    QA_APPLE_CALLS=td,
                    PYTHONDONTWRITEBYTECODE="1",
                )
                argv = [
                    sys.executable,
                    "-c",
                    "import os,sys; print(os.read(int(sys.argv[1]),1).decode()); sys.exit(19)",
                    str(r),
                ]
                p = subprocess.run([str(w), *argv], env=env, pass_fds=(r,), capture_output=True)
                self.assertEqual((p.returncode, p.stdout), (19, b"Z\n"), p.stderr)
                (f,) = Path(td).glob("*.json")
                row = json.loads(f.read_bytes())
                self.assertEqual((row["argv"], row["exit"]), (argv, 19))
            finally:
                os.close(r)
                os.close(fd)

    def test_bare_rustc_proxy_must_select_the_enrolled_sdk(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            rustup = d / "rustup"
            rustup.write_text('#!/bin/sh\n[ "$1 $2" = "which rustc" ] || exit 1\nprintf "%s\\n" "$REAL"\n')
            rustup.chmod(0o755)
            (d / "rustc").symlink_to(rustup)
            with patch.dict(os.environ, PATH=td, REAL=sys.executable):
                self.assertEqual(compiler_selector("rustc", Path(sys.executable))["kind"], "rustup")
                with self.assertRaisesRegex(RuntimeError, "rustup selected a different compiler"):
                    compiler_selector("rustc", rustup.parent)
                (d / "rustc").unlink()
                (d / "rustc").symlink_to("/bin/sh")
                with self.assertRaisesRegex(RuntimeError, "Cargo passed a different rustc"):
                    compiler_selector("rustc", Path(sys.executable))

    def test_only_the_selected_linker_output_counts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            output = root / "output"
            self.assertTrue(has_output(["ld", "-o", str(output)], output))
            output.touch()
            alias = root / "alias"
            alias.symlink_to(output)
            foreign = root / "other"
            foreign.touch()
            self.assertTrue(has_output(["ld", "-o", str(alias)], output))
            self.assertFalse(has_output(["ld", str(output), "-o", str(foreign)], output))

    def test_only_the_diagnostic_sets_the_exact_compiler(self):
        with tempfile.TemporaryDirectory() as td:
            rustup = Path(td)
            compiler = rustup / "toolchains/ohm/bin/rustc"
            compiler.parent.mkdir(parents=True)
            compiler.symlink_to(sys.executable)
            env = dict(os.environ, RUSTUP_HOME=td, RUSTC="rustc")
            argv = ["cargo", "+ohm", "build"]
            proc = subprocess.CompletedProcess(argv, 0)
            with patch("wrapper.subprocess.run", return_value=proc) as child:
                code, rows = WrapperTrace().command(argv, env=env, cwd=rustup, out=None, err=None)
            self.assertEqual((code, env["RUSTC"]), (0, "rustc"))
            self.assertEqual(child.call_args.args[0], argv)
            self.assertEqual(child.call_args.kwargs["env"]["RUSTC"], str(compiler.resolve()))
            self.assertEqual(rows[0]["selected_rustc"], str(compiler.resolve()))

    def test_stage_freezes_runtime_without_following_source_backlinks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "checkout"
            stage = repo / "build/host/stage1"
            rl = stage / "lib/rustlib"
            library = repo / "library"
            std = library / "std/src/lib.rs"
            std.parent.mkdir(parents=True)
            std.write_text("real standard library source")
            (library / ".git").write_text("private checkout control")
            for component in ("src", "rustc-src"):
                (rl / component).mkdir(parents=True)
                (rl / component / "rust").symlink_to(repo)
            dep = repo / "build/external.o"
            dep.write_bytes(b"P")
            host = rl / "native/lib"
            host.mkdir(parents=True)
            (host / "libstd.rlib").symlink_to(dep)
            (rl / "host").symlink_to("native")
            (stage / "lib/driver").symlink_to(dep)
            frozen = root / "P"
            links = freeze_stage(stage, frozen, repo, library)
            self.assertEqual(links, {"lib/rustlib/host": "lib/rustlib/native"})
            before = role_files(frozen)
            physical = identity_digest(frozen, before)
            dep.write_bytes(b"C")
            child = root / "C"
            freeze_stage(stage, child, repo, library)
            for path in ("lib/driver", "lib/rustlib/host/lib/libstd.rlib"):
                self.assertEqual((frozen / path).read_bytes(), b"P")
                self.assertEqual((child / path).read_bytes(), b"C")
            self.assertEqual(role_files(frozen), before)
            self.assertEqual(identity_digest(frozen, before), physical)
            self.assertTrue((frozen / "lib/rustlib/host").resolve().is_relative_to(frozen))
            self.assertFalse((frozen / "lib/rustlib/rustc-src/rust").exists())
            self.assertFalse((frozen / "lib/rustlib/src/rust/library/.git").exists())
            self.assertEqual((frozen / "lib/rustlib/src/rust/library/std/src/lib.rs").read_bytes(), std.read_bytes())
            (stage / "lib/unexpected").symlink_to(repo)
            with self.assertRaisesRegex(RuntimeError, "external or cyclic SDK alias"):
                freeze_stage(stage, root / "bad", repo, library)

    def test_whole_single_branch_transition(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            src = d / study.SOURCE
            src.parent.mkdir(parents=True)
            cmd = (
                lambda *a: subprocess.check_output(["git", "-C", str(d), *a], stderr=subprocess.DEVNULL)
                .decode()
                .strip()
            )
            cmd("init", "-b", "qa-apple-zmij")
            cmd("config", "user.email", "qa@example.com")
            cmd("config", "user.name", "QA")
            (d / "Cargo.lock").write_text("fixed lock\n")
            refs = []
            blobs = []
            for v in ("old", "new"):
                src.write_text(v)
                (d / "separate-file").write_text("full tree " + v)
                cmd("add", ".")
                cmd("commit", "-m", v)
                refs.append(cmd("rev-parse", "HEAD"))
                blobs.append(cmd("rev-parse", "HEAD:" + study.SOURCE))
            cmd("switch", "--detach", refs[0])
            cmd("branch", "-f", "qa-apple-zmij", refs[0])
            cmd("switch", "qa-apple-zmij")
            with patch.multiple(
                study,
                RUFF=refs[0],
                EDIT=refs[1],
                EDIT_TREE=cmd("rev-parse", refs[1] + "^{tree}"),
                OLD_BLOB=blobs[0],
                NEW_BLOB=blobs[1],
                LOCK=study.sha(d / "Cargo.lock"),
            ):
                vals = study.source_values(d)
                for s in ("old", "new", "invalid", "new", "old"):
                    study.change_source(d, vals, s)
                    self.assertEqual(
                        (d / "separate-file").read_text(), "full tree " + ("old" if s == "old" else "new")
                    )
                    self.assertEqual(cmd("rev-parse", "HEAD"), refs[0])


if __name__ == "__main__":
    unittest.main()
