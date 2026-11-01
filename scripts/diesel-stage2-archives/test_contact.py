"""Exercise real archive framing, PIPE rights through exec, clone equivalence, and original-case provenance."""

import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import contact
import jobserver
import products
import read_outputs


class Tests(unittest.TestCase):
    def test_incoming_archive_locations(self):
        cwd = Path("/private/test")
        out = cwd / "target/release/build/diesel/abcd/out"
        argv = ["rustc", "extra-filename=-abcd", "--out-dir", str(out)]
        rlib, rmeta = (str(p.relative_to(cwd)) for p in products.outputs(argv))
        public = "target/release/libdiesel.rlib"
        lib = {"type": "file", "size": 19, "sha256": "1" * 64}
        meta = {"type": "file", "size": 17, "sha256": "2" * 64}
        present = {rmeta: meta, public: lib}
        expected = {Path(rlib).name: [19, "1" * 64], Path(rmeta).name: [17, "2" * 64]}
        for rows in (present, {**present, rlib: lib}, {rlib: lib, rmeta: meta}):
            state = products.incoming(argv, cwd, rows)
            self.assertEqual(state["outputs"], expected)
            self.assertEqual(state["paths"][rlib] is not None, rlib in rows)
            self.assertEqual(state["paths"][public] is not None, public in rows)
        for bad in ({public: lib}, {rmeta: meta}, {**present, rlib: meta}, {**present, public: {"type": "symlink"}}):
            with self.assertRaises(ValueError):
                products.incoming(argv, cwd, bad)

    def test_full_literal_name_reconstruction(self):
        clang = shutil.which("clang")
        ar = shutil.which("llvm-ar") or shutil.which("llvm-ar-18")
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            metadata = b"rust\0" + b"x" * 51
            (base / "lib.rmeta").write_bytes(metadata)
            for target, fmt, section, machine, expected in (
                ("arm64-apple-macos11", "darwin", "__DWARF,.rmeta-link", 0x0100000C, "Mach-O"),
                ("x86_64-unknown-linux-gnu", "gnu", ".rmeta-link", 62, "ELF"),
            ):
                views = []
                for suffix in ("0abcdef", "1bcdefg"):
                    name = f"actual-library.872091ac-cgu.00.{suffix}.rcgu.o"
                    cg = base / name
                    subprocess.run(
                        [clang, "-target", target, "-c", "-x", "c", "-", "-o", cg],
                        input=b"int projected(int v){return v+17;}",
                        check=True,
                    )
                    # MemEncoder's Vec<String>, the empty native-library vector, and its footer.
                    data = bytes([1, len(name)]) + name.encode() + b"\xc1\x00rust-end-file"
                    decl = (
                        f'__attribute__((section("{section}"),used)) const unsigned char names[]={{'
                        + ",".join(map(str, data))
                        + "};"
                    )
                    wrapper = base / "lib.rmeta-link"
                    subprocess.run(
                        [clang, "-target", target, "-c", "-x", "c", "-", "-o", wrapper],
                        input=decl.encode(),
                        check=True,
                    )
                    archive = base / (fmt + "-" + suffix + ".rlib")
                    subprocess.run(
                        [ar, "--format=" + fmt, "rcs", archive, base / "lib.rmeta", wrapper, cg], check=True
                    )
                    raw = archive.read_bytes()
                    view = products.archive(raw, metadata)
                    member = next(m for m in view["members"] if m["name"] == name)
                    self.assertEqual((member["object"]["format"], member["object"]["cpu"]), (expected, machine))
                    views.append((raw, view, member))
                (a, va, _), (b, vb, cgu) = views
                good = products.suffix_proof(a, b, va, vb)
                self.assertEqual(good["result"], "full byte-for-byte reconstruction in both directions")
                self.assertEqual(good["forward"]["reencoded"], products.digest(b))
                self.assertEqual(len(good["forward"]["edits"]), 2)
                self.assertEqual(good["reverse"]["reencoded"], products.digest(a))
                code = next(s for s in cgu["object"]["sections"] if s["group"] == "code")
                for offset in (cgu["payload_offset"] + code["offset"], cgu["header_offset"] + 16):
                    changed = bytearray(b)
                    changed[offset] ^= 1
                    changed = bytes(changed)
                    mutant = products.suffix_proof(a, changed, va, products.archive(changed, metadata))
                    self.assertEqual(mutant["result"], "literal reconstruction unavailable")
                for bad in (
                    data + b"!",
                    data.replace(b"\xc1", b"\x99"),
                    data.replace(b"\x00rust-end", b"\x01\x02rust-end"),
                ):
                    with self.assertRaises(ValueError):
                        products.rust_object_names(bad)

    def test_real_native_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            clang = shutil.which("clang")
            ar = shutil.which("llvm-ar") or shutil.which("llvm-ar-18")
            self.assertTrue(clang and ar)
            meta = b"rust\0" + b"independent native framing" * 80
            # Darwin ar can include extra eight-byte alignment in a member's
            # declared length. This framing-only control uses identical payloads.
            meta += b"x" * (-len(meta) % 8)
            (p / "lib.rmeta").write_bytes(meta)
            obj = p / "a-real-long-codegen-unit.00000000000.rcgu.o"
            defs = [
                "int data=17; int projected(int v){return v+data;}",
                "int data=41; int projected(int v){ return v * 3 + data; }",
            ]
            views = []
            for index, source in enumerate(defs):
                (p / "one.c").write_text(source)
                subprocess.run([clang, "-g", "-c", p / "one.c", "-o", obj], check=True)
                for fmt in ("gnu", "darwin"):
                    dst = p / (str(index) + fmt + ".rlib")
                    subprocess.run([ar, "--format=" + fmt, "rcs", dst, obj, p / "lib.rmeta"], check=True)
                    data = dst.read_bytes()
                    a = products.archive(data, meta)
                    self.assertEqual(
                        [m["name"] for m in a["members"] if m["role"] != "archive-index"], [obj.name, "lib.rmeta"]
                    )
                    native = next(m for m in a["members"] if m["name"] == obj.name)
                    self.assertIn(native["object"]["format"], ("ELF", "Mach-O"))
                    self.assertTrue(any(s["group"] == "code" for s in native["object"]["sections"]))
                    self.assertEqual(native["sha256"], products.digest(obj.read_bytes()))
                    self.assertGreaterEqual(
                        next(m for m in a["members"] if m["name"] == "lib.rmeta")["embedded_standalone_offset"], 0
                    )
                    with self.assertRaises((ValueError, IndexError)):
                        products.archive(data[:-11], meta)
                    views.append(a)
            framing = products.compare(views[0], views[1])
            self.assertFalse(framing["archive_equal"])
            self.assertTrue(framing["ordered_nonindex_bodies_equal"])
            change = products.compare(views[0], views[2])
            self.assertFalse(change["ordered_nonindex_bodies_equal"])
            self.assertTrue(any("code" in d["changed_section_groups"] for d in change["differences_by_ordinal"]))

    def test_kernel_handoff_and_exec(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as tmp:
            base = Path(tmp)
            (base / "archive-handoff").mkdir(mode=0o700)
            broker = subprocess.Popen([sys.executable, "-IB", HERE / "jobserver.py", "serve", base])
            r, w = os.pipe()
            got = []
            high = []
            try:
                end = time.monotonic() + 5
                while not Path(jobserver.address(base)).is_socket() and time.monotonic() < end:
                    time.sleep(0.015)
                os.write(w, b"example")
                sent = jobserver.describe((r, w))
                held, unused = jobserver.exchange(base, "offer", (r, w))
                claimed, got = jobserver.exchange(base, "claim")
                self.assertEqual((held["available_bytes"], claimed["available_bytes"]), (7, 7))
                self.assertEqual(jobserver.identity(held), jobserver.identity(sent))
                self.assertEqual(jobserver.identity(jobserver.describe(got)), jobserver.identity(sent))
                self.assertEqual((unused, broker.wait(timeout=5)), ([], 0))
                # A synthetic token written after transfer is visible on the original
                # read end. Neither operation occurs in an actual collector recording.
                os.write(got[1], b"!")
                self.assertEqual(os.read(r, 8), b"example!")
                high = [fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, 64) for fd in got]
                detector = base / "child.py"
                detector.write_text(
                    "import os,sys,stat\nprint([(n,stat.S_ISFIFO(os.fstat(n).st_mode)) for n in (7,11)] if sys.argv[1]=='live' else [os.path.exists('/dev/fd/'+str(n)) for n in (7,11)])"
                )
                env = {
                    "PATH": "/usr/bin:/bin",
                    "CASE": "registered",
                    "CARGO_MAKEFLAGS": "-j --jobserver-fds=7,11 --jobserver-auth=7,11",
                }
                for role, flag, fds in (("ordinary-1", "live", high), ("closed-fds", "dead", [])):
                    start = base / role
                    rec = base / (role + ".json")
                    argv = [sys.executable, "-IB", str(detector), flag]
                    rec.write_text(json.dumps({"environment": env, "argv": argv}))
                    out = subprocess.run(
                        [sys.executable, "-IB", HERE / "jobserver.py", "exec", rec, start, role, *map(str, fds)],
                        cwd=tmp,
                        pass_fds=fds,
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(out.returncode, 0, out.stderr)
                    self.assertEqual(out.stdout.strip(), "[(7, True), (11, True)]" if fds else "[False, False]")
                    saved = json.loads(start.read_text())
                    self.assertEqual((saved["argv"], saved["env"]), (argv, env))
                    if fds:
                        self.assertEqual(jobserver.identity(saved["fds"]), jobserver.identity(sent))
                    else:
                        self.assertIsNone(saved["fds"])
                with self.assertRaises(ValueError):
                    jobserver.describe((w, r))
                for bad in (
                    "-j",
                    "--jobserver-fds=1,2",
                    "--jobserver-auth=8,8",
                    "--jobserver-fds=7,11 --jobserver-auth=8,12",
                ):
                    with self.assertRaises(ValueError):
                        jobserver.numbers({"CARGO_MAKEFLAGS": bad})
            finally:
                if broker.poll() is None:
                    broker.kill()
                    broker.wait()
                for fd in [r, w, *got, *high]:
                    os.close(fd)

    def test_replay_seed_and_cold(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve(strict=True)
            slot = base / "seed"
            slot.mkdir()
            (slot / "a").write_bytes(b"immutable")
            os.link(slot / "a", slot / "alias")
            dest = base / "copy"
            shutil.copytree(slot, dest)
            with self.assertRaises(ValueError):
                contact.capture.clone_matches(slot, dest)
            contact.check_clone(slot, dest)
            passed = contact.capture.clone_matches(slot, dest)
            (dest / "a").write_bytes(b"different")
            with self.assertRaises(ValueError):
                contact.capture.clone_matches(slot, dest)
            self.assertEqual(passed["unique_files"], 1)
            inc = dest / "incremental-state/source/s-a"
            inc.mkdir(parents=True)
            (inc / "dep-graph.bin").write_bytes(b"incoming")
            out = dest / "target/release/build/diesel/abcd/out"
            out.mkdir(parents=True)
            extern = dest / "target/derive.dylib"
            extern.write_bytes(b"real dependency input")
            argv = [
                "rustc",
                "-C",
                "extra-filename=-abcd",
                "--out-dir",
                str(out),
                "--extern",
                "diesel_derives=" + str(extern),
            ]
            for f in products.outputs(argv):
                f.write_bytes(b"seed output")
            published = dest / "target/release/libdiesel.rlib"
            os.link(products.outputs(argv)[0], published)
            untouched = dest / "target/release/build/diesel/other/out/libdiesel-other.rlib"
            untouched.parent.mkdir(parents=True)
            untouched.write_bytes(b"plain A sibling")
            record = {"argv": argv, "cwd": str(dest)}
            ex = contact.external_inputs(record)
            alias = base / "logical-workspace"
            alias.symlink_to(dest, target_is_directory=True)
            self.assertEqual(ex, contact.external_inputs({**record, "cwd": str(alias)}))
            outside = base / "foreign.dylib"
            outside.write_bytes(b"unrelated library")
            escaped = dest / "escape.dylib"
            escaped.symlink_to(outside)
            with self.assertRaisesRegex(ValueError, "foreign explicit dependency"):
                contact.external_inputs({"cwd": str(alias), "argv": ["--extern", "diesel_derives=" + str(escaped)]})
            cold = contact.cold_unit(dest, record)
            self.assertEqual(len(cold["removed_outputs"]), 3)
            self.assertEqual(untouched.read_bytes(), b"plain A sibling")
            self.assertFalse(published.exists())
            self.assertEqual(ex, contact.external_inputs(record))
            self.assertFalse(list((dest / "incremental-state").iterdir()) or list(out.iterdir()))

    def test_darwin_pipe_status(self):
        # Endpoint snapshots from the first macOS 15 run, before and after SCM_RIGHTS.
        def snapshot(platform, read_flags, write_flags):
            return {
                "platform": platform,
                "ends": [
                    {"fd": 7, "dev": 0, "ino": 2119632488035979604, "mode": 4528, "flags": read_flags},
                    {"fd": 11, "dev": 0, "ino": 14995846943073723440, "mode": 4528, "flags": write_flags},
                ],
            }

        before = snapshot("darwin", 0, 65537)
        after = snapshot("darwin", 4096, 69633)
        self.assertEqual(jobserver.identity(before), jobserver.identity(after))
        self.assertEqual([end["flags"] for end in after["ends"]], [4096, 69633])
        self.assertEqual(jobserver.identity(before), jobserver.identity(snapshot("darwin", 8192, 73729)))
        self.assertNotEqual(jobserver.identity(before), jobserver.identity(snapshot("darwin", 4, 65537)))
        self.assertNotEqual(jobserver.identity(before), jobserver.identity(snapshot("darwin", 0, 1)))
        self.assertNotEqual(jobserver.identity(snapshot("linux", 0, 1)), jobserver.identity(snapshot("linux", 4096, 1)))
        swapped = snapshot("darwin", 0, 65537)
        swapped["ends"][1]["ino"] += 1
        self.assertNotEqual(jobserver.identity(before), jobserver.identity(swapped))
        with self.assertRaises(ValueError):
            jobserver.identity(snapshot("darwin", 1, 65537))

    def test_independent_seed_zip(self):
        with tempfile.TemporaryDirectory() as t:
            base = Path(t)
            src = base / "inputs"
            src.mkdir()
            (src / "lib.bootstrap").write_bytes(b"actual captured file")
            os.link(src / "lib.bootstrap", src / "alias")
            (src / "symlink").symlink_to("lib.bootstrap")
            d = base / "archives/original"
            d.mkdir(parents=True)
            archived = contact.pack(src, d / "before-B-source-and-A-session.tar.gz")
            expected = {
                "complete_archive": archived,
                "normalized": contact.capture.projection(contact.facts(src)[0]),
            }
            for index in range(2):
                if index:
                    expected["complete_archive"]["sha256"] = "0" * 64
                (d / "seed.json").write_text(json.dumps(expected))
                zpath = base / f"original-{index}.zip"
                with zipfile.ZipFile(zpath, "x") as zip:
                    for p in d.iterdir():
                        zip.write(p, p.relative_to(base))
                with zipfile.ZipFile(zpath) as zip:
                    if index:
                        with self.assertRaises(ValueError):
                            read_outputs.original_inputs(zip)
                    else:
                        self.assertEqual(expected, read_outputs.original_inputs(zip))

    def test_prior_source_and_registration(self):
        case = json.loads((HERE / "previous.json").read_bytes())
        self.assertEqual(case["run"], 41273385731)
        self.assertEqual(case["head"], "87d296ac3b05648c082193fdb91d1145652797ff")
        self.assertEqual(case["planned_after_natural"], list(contact.ROLES))
        n, l = case["natural_outputs"], case["loaded_outputs"]
        self.assertEqual(set(n), set(l))
        for name in n:
            self.assertEqual(n[name][0], l[name][0])
            self.assertEqual(n[name][1] == l[name][1], name.endswith(".rmeta"))
        self.assertEqual(len(case["prior_official_zips"]), 3)


def historic(folder):
    case = json.loads((HERE / "previous.json").read_bytes())
    source = []
    for item in case["prior_official_zips"]:
        path = folder / (str(item["id"]) + "-" + item["name"] + ".zip")
        assert path.stat().st_size == item["size_in_bytes"] and "sha256:" + contact.sha(path) == item["digest"]
        with zipfile.ZipFile(path) as z:
            infos = [i for i in z.infolist() if not i.is_dir()]
            assert not any(
                i.filename.endswith((".rlib", ".rmeta", ".o", ".tar", ".tar.gz", ".tar.zst"))
                or i.file_size in (15193038, 15326392)
                for i in infos
            )
            source.extend(i.filename for i in infos)
            if "graph-witness.json" in z.namelist():
                w = json.loads(z.read("graph-witness.json"))
                assert (w["actual_rustcs"][-1]["outputs"], w["loaded_control"]) == (
                    case["natural_outputs"],
                    case["loaded_outputs"],
                )
                assert b"failed to connect to jobserver" in z.read("loaded-B-export/stderr")
            if "focused/natural.json" in z.namelist():
                eb = [json.loads(z.read(n)) for n in z.namelist() if n.endswith("/before.json")]
                eb.sort(key=lambda v: v["monotonic_ns"])
                assert [(r["source"], r["incremental"]) for r in eb] == [("A", False), ("A", True), ("B", True)]
                b = eb[-1]
                assert jobserver.numbers(b["environment"]) == (3, 5)
                assert b"failed to connect to jobserver" not in z.read(
                    "focused/events/" + str(b["wrapper"]) + "/rustc.stderr"
                )

                def after(ev):
                    return read_outputs.read(z, f"focused/events/{ev['wrapper']}/after.json")

                values = after(b)["outputs"]
                paths = products.outputs(b["argv"])
                first = {
                    "before": b,
                    "native_pid": after(b)["pid"],
                    "collector": read_outputs.read(z, "focused/natural.json"),
                }
                seed = {"incoming_products": {"outputs": after(eb[-2])["outputs"]}}
                # The previous originals carry hashes only. Exercise the same
                # event/graph/profile reader without claiming their missing bodies.
                inv = {
                    "paths": list(map(str, paths)),
                    "archive": values[paths[0].name],
                    "standalone_metadata": values[paths[1].name],
                }
                read_outputs.natural_evidence(z, first, seed, inv)
                try:
                    read_outputs.natural_evidence(z, first | {"native_pid": -2}, seed, inv)
                except ValueError:
                    pass
                else:
                    raise AssertionError("wrong natural compiler accepted")
    assert len(source) == 154
    print(
        "Three authenticated original ZIPs, 154 members, no original library bodies; real FD warning distinguished."
    )


def native_seed(path):
    """Check our B-entry reader on the actual Mac archive from before the third physical compile."""
    assert path.stat().st_size == 216576568
    assert contact.sha(path) == "c0ffcb6f51f0cf4282dfc341b1ec64d4b27c97c75144b7ddacea0d84cc3022de"
    with zipfile.ZipFile(path) as z:
        inv = read_outputs.read(z, "archives/original/before-B-source-and-A-session.tar.inventory.json")
        before = read_outputs.read(z, "focused/events/12316/before.json")
        previous = read_outputs.read(z, "focused/events/12035/after.json")
        cwd = Path(before["cwd"])
        assert previous["code"] == 0 and previous["pid"] == 12059 and previous["source"] == "A"
        assert before["source"] == "B" and before["graphs"] == previous["graphs"] and inv["root"] == str(cwd)
        state = products.incoming(before["argv"], cwd, inv["entries"])
        assert state["outputs"] == previous["outputs"] and len(inv["entries"]) == 622
        rlib, rmeta = products.outputs(before["argv"])
        published = "target/release/libdiesel.rlib"
        assert state["paths"][str(rlib.relative_to(cwd))] is None
        names = [published, str(rmeta.relative_to(cwd))]
        archive = read_outputs.member(z, "archives/original/before-B-source-and-A-session.tar.gz")
        inode = lambda name: (inv["entries"][name]["dev"], inv["entries"][name]["ino"])
        requested = {inode(n) for n in names}
        bodies = {}
        seen = set()
        with z.open(archive) as stream, tarfile.open(fileobj=stream, mode="r|gz") as tar:
            for item in tar:
                ident = inode(item.name)
                if ident not in requested:
                    continue
                seen.add(item.name)
                if item.islnk():
                    assert item.linkname in seen and inode(item.linkname) == ident and ident in bodies
                else:
                    assert item.isfile() and ident not in bodies
                    with tar.extractfile(item) as f:
                        bodies[ident] = f.read()
        assert set(names) <= seen
        inventory = products.archive(*(bodies[inode(n)] for n in names))
        assert inventory["archive"] == state["outputs"][rlib.name]
        assert inventory["standalone_metadata"] == state["outputs"][rmeta.name]
    print("Previous A products and the absent B-entry rlib path match the complete 622-entry Apple seed.")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "originals":
        historic(Path(sys.argv[2]))
    elif len(sys.argv) == 3 and sys.argv[1] == "native-seed":
        native_seed(Path(sys.argv[2]))
    else:
        unittest.main()
