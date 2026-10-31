"""Contrast an untouched packed work product with one shadowed by a valid object from another branch."""

import fcntl
import gzip
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile

from objects import digest as sha, dump, escrow, file_sha, unpack
from physical import observe

CRATE = "shadow_leaf"


def copy_state(source, dest):
    inodes = {}

    def member(src, dst):
        st = os.stat(src)
        identity = (st.st_dev, st.st_ino)
        if identity in inodes:
            os.link(inodes[identity], dst)
        else:
            shutil.copy2(src, dst)
            inodes[identity] = dst
        return dst

    shutil.copytree(source, dest, symlinks=True, copy_function=member)


def experiment(report, work, sdk, rustup, files, source, driver, policy, path):
    assert policy in {"original", "reject"} and len(files) == 81
    assert (rustup / "toolchains/ohm").resolve() == sdk.resolve()
    for key, item in files.items():
        p = sdk / key
        assert [file_sha(p), p.stat().st_size, stat.S_IMODE(p.stat().st_mode)] == item
    report.mkdir()
    dump(
        report / "subject.json",
        {"source": source, "driver": files[driver], "cargo": files["bin/cargo"], "members": 81},
    )
    with tempfile.TemporaryDirectory(prefix="trial-", dir=work) as temp:
        root = Path(temp)
        ws = root / "workspace"
        ws.mkdir()
        out = root / "products"
        out.mkdir()
        home = root / "home"
        home.mkdir()
        env = {
            "HOME": str(home),
            "PATH": path,
            "RUSTUP_HOME": str(rustup),
            "RUSTUP_AUTO_INSTALL": "0",
            "CARGO_HOME": str(root / "cargo-home"),
            "CARGO_TARGET_DIR": str(out / "target"),
            "CARGO_BUILD_BUILD_DIR": str(out / "build"),
            "CARGO_NET_OFFLINE": "true",
            "CARGO_CACHE_AUTO_CLEAN_FREQUENCY": "never",
            "CARGO_ENCODED_RUSTFLAGS": "-Zohm-branch-cache=yes",
            "LC_ALL": "C",
            "LD_LIBRARY_PATH": str(sdk / "lib"),
        }
        (ws / "Cargo.toml").write_text(
            '[workspace]\nmembers=["leaf","app"]\nresolver="2"\n[profile.dev]\ncodegen-units=1\ndebug=0\nincremental=true\n'
        )
        for package in ("leaf", "app"):
            (ws / package / "src").mkdir(parents=True)
            line = '[dependencies]\nshadow_leaf={path="../leaf"}\n' if package == "app" else ""
            (ws / package / "Cargo.toml").write_text(
                f'[package]\nname="shadow_{package}"\nversion="0.0.0"\nedition="2021"\n' + line
            )
        (ws / "app/src/main.rs").write_text('fn main() {println!("{}",shadow_leaf::value());}\n')

        def cli(args):
            cmd = subprocess.run(args, cwd=ws, env=env, capture_output=True, timeout=45)
            if cmd.returncode:
                (report / "refusal.stderr.gz").write_bytes(gzip.compress(cmd.stderr, mtime=0))
                dump(
                    report / "refusal.json",
                    {"command": [str(part) for part in args], "code": cmd.returncode},
                )
                raise RuntimeError(cmd.stderr.decode(errors="replace")[-2000:])
            return cmd

        (ws / "leaf/src/lib.rs").touch()
        cli(["git", "init", "-q", "-b", "a"])
        cli(["cargo", "+ohm", "generate-lockfile", "--offline"])

        def switch(branch, value):
            cli(["git", "symbolic-ref", "HEAD", "refs/heads/" + branch])
            rs = [f"pub fn f{i}(x:u32)->u32{{x.wrapping_add({i})}}" for i in range(384)]
            rs += [
                f"static DATA:[u8;32768]=[{value};32768];",
                "#[inline(never)] pub fn value()->u32{f0(std::hint::black_box(&DATA)[0].into())}",
            ]
            (ws / "leaf/src/lib.rs").write_text("\n".join(rs) + "\n")

        def sessions():
            return {
                p
                for p in out.rglob("s-*")
                if p.is_dir()
                and p.parent.name.startswith(CRATE + "-")
                and not p.name.endswith("-working")
            }

        def force():
            paths = [
                p
                for p in out.rglob("*")
                if p.name in {"lib-shadow_leaf", "bin-shadow_app"} and p.is_file()
            ]
            if len(paths) != 2:
                dump(
                    report / "fingerprint-discovery.json",
                    [str(p.relative_to(out)) for p in out.rglob("*") if "fingerprint" in str(p)],
                )
            assert len(paths) == 2, paths
            for path in paths:
                path.unlink()
            return [str(p.relative_to(out)) for p in paths]

        def build(name, allowed_failure=False):
            before = sessions()
            cmd = [
                "cargo",
                "+ohm",
                "build",
                "--locked",
                "--offline",
                "-p",
                "shadow_app",
                "-j1",
                "--message-format=json",
                "-vv",
            ]
            c = observe(cmd, ws, env, report, name, sdk / driver, source)
            (report / (name + ".stderr.gz")).write_bytes(gzip.compress(c.stderr, mtime=0))
            (report / (name + ".stdout.gz")).write_bytes(gzip.compress(c.stdout, mtime=0))
            messages = [json.loads(l) for l in c.stdout.splitlines()]
            rows = [m for m in messages if m["reason"] == "compiler-artifact"]
            if c.returncode:
                text = (c.stdout + b"\n" + c.stderr).lower()
                rec = {
                    "cargo": cmd,
                    "status": c.returncode,
                    "diagnostics": [
                        m["message"]["message"] for m in messages if m["reason"] == "compiler-message"
                    ],
                    "source": file_sha(ws / "leaf/src/lib.rs"),
                    "panic_or_ice": any(
                        term in text for term in (b"panicked at", b"internal compiler error")
                    ),
                }
                dump(report / (name + ".json"), rec)
                assert allowed_failure and c.returncode == 101 and not rec["panic_or_ice"], rec
                return None, rec
            assert len(rows) == 2 and all(not row["fresh"] for row in rows)
            exe = Path(next(r["executable"] for r in rows if r["executable"]))
            output = cli([exe]).stdout
            (report / (name + ".runtime")).write_bytes(output)
            verdict = int(output.strip())
            assert output == f"{verdict}\n".encode()
            escrow(report / "elf", file_sha(exe), exe.read_bytes())
            (current,) = sessions() - before
            rec = {
                "cargo": cmd,
                "status": 0,
                "source": file_sha(ws / "leaf/src/lib.rs"),
                "program": file_sha(exe),
                "runtime": verdict,
                "fresh": {r["target"]["name"]: r["fresh"] for r in rows},
                "new": current.name,
                "all_sessions": sorted(p.name for p in sessions()),
                "files": sorted(f.name for f in current.iterdir()),
                "marker": (current / "reader-origin-marker").exists(),
            }
            dump(report / (name + ".json"), rec)
            return current, rec

        switch("a", 17)
        A, a = build("A17")
        assert a["runtime"] == 17
        old_objects = {p.name: p.read_bytes() for p in A.glob("*.o")}
        switch("b", 29)
        B, b = build("B29")
        assert b["runtime"] == 29
        candidates = []
        for p in B.glob("ohm-packed-object-*"):
            obj, _, digest = p.name.removeprefix("ohm-packed-object-").partition("-")
            actual, payload = unpack(p.read_bytes(), p.name, B.name)
            assert actual == obj
            if obj in old_objects and b"\x11" * 8192 in old_objects[obj] and b"\x1d" * 8192 in payload:
                candidates.append((p, obj, digest, payload))
        assert len(candidates) == 1, (len(candidates), [p.name for p in B.iterdir()])
        packed, name, digest, correct = candidates[0]
        assert not (B / name).exists()
        assert len(old_objects[name]) == len(correct)
        escrow(report / "inputs", "raw-A", old_objects[name])
        escrow(report / "inputs", "raw-B", correct)
        escrow(report / "inputs", "packed-B", packed.read_bytes())
        # The raw reader and its negative start from exactly the same completed tree.
        parked = root / "held"
        copy_state(out, parked)
        captured = {
            "raw_A": sha(old_objects[name]),
            "raw_B": sha(correct),
            "packed_B": file_sha(packed),
            "session": B.name,
            "packed_filename": packed.name,
            "original_raw_absent": True,
            "lengths": [len(old_objects[name]), len(correct)],
            "payloads": {"old": 17, "new": 29},
        }

        def restore_fixture():
            shutil.rmtree(out)
            copy_state(parked, out)

        original = policy == "original"

        # All mutations are in different physical copies of the same complete B tree.
        # The compiler is checked for changes to the source after acquiring its real Linux session flock.
        def contents(directory):
            results = {}
            for path in sorted(directory.iterdir()):
                st = path.lstat()
                results[path.name] = [
                    st.st_dev,
                    st.st_ino,
                    st.st_size,
                    st.st_mtime_ns,
                    stat.S_IMODE(st.st_mode),
                    (
                        file_sha(path)
                        if stat.S_ISREG(st.st_mode)
                        else (
                            os.readlink(path)
                            if stat.S_ISLNK(st.st_mode)
                            else str(stat.S_IFMT(st.st_mode))
                        )
                    ),
                ]
            return results

        cases = [
            ("honest", "absent", "valid", False, 29, True),
            ("matching-raw", "good", "valid", False, 29, original),
            ("conflicting-raw", "old", "valid", False, 17 if original else 29, original),
            ("bad-zlib", "absent", "broken", False, 29, False),
            ("bad-digest-no-raw", "absent", "digest", False, 29, False),
            ("bad-digest-with-raw", "old", "digest", False, 17 if original else 29, original),
            ("bad-digest-name", "absent", "name", False, 29, False),
            ("bad-both", "old", "broken", False, 17 if original else 29, original),
            ("nonregular-raw-symlink", "link", "valid", False, 29, False),
            ("nonregular-raw-fifo", "fifo", "valid", False, 29, False),
            ("locked", "old", "valid", True, 29, False),
            ("raw-only-old", "old", "none", False, 17, True),
            ("malformed-raw", "broken", "valid", False, None if original else 29, False),
        ]
        captured["cases"] = {}
        for label, raw_mode, sidecar, exclusive, expected, marker in cases:
            restore_fixture()
            raw = B / name
            assert not raw.exists()
            if raw_mode in ("good", "old", "broken"):
                raw.write_bytes(
                    {
                        "good": correct,
                        "old": old_objects[name],
                        "broken": b"bad object from a failed external writer",
                    }[raw_mode]
                )
            elif raw_mode == "link":
                outside = root / "outside-object"
                outside.write_bytes(old_objects[name])
                raw.symlink_to(outside)
            elif raw_mode == "fifo":
                os.mkfifo(raw)
            if sidecar == "broken":
                packed.write_bytes(b"not-a-zlib-stream")
            elif sidecar == "none":
                packed.unlink()
            elif sidecar == "digest":
                packed.rename(B / ("ohm-packed-object-" + name + "-not-a-digest"))
            elif sidecar == "name":
                packed.rename(B / "ohm-packed-object-not-a-valid-object-name")
            (B / "reader-origin-marker").write_text(label)
            lock_path = B.parent / (B.name.rsplit("-", 1)[0] + ".lock")
            assert lock_path.is_file()
            with lock_path.open("rb+") as lock:
                fcntl.flock(lock, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
                before = contents(B)
                captured["forced"] = force()
                _, rec = build("B-" + label, allowed_failure=expected is None)
                after = contents(B)
                assert before == after, label
                dump(
                    report / (label + "-source-unchanged.json"),
                    {"mode": "EX" if exclusive else "SH", "before": before, "after": after},
                )
            if expected is None:
                assert rec["status"] == 101 and rec["diagnostics"], rec
            else:
                assert (
                    rec["runtime"] == expected
                    and rec["marker"] == marker
                    and rec["program"] == ({17: a, 29: b}[expected]["program"])
                ), (label, rec)
            captured["cases"][label] = {
                k: rec.get(k) for k in ("runtime", "status", "marker", "program", "panic_or_ice")
            }
            dump(report / "partial.json", captured)
        shutil.rmtree(out)
        out.mkdir()
        _, clean = build("B-independent-empty")
        assert clean["runtime"] == 29 and clean["program"] == b["program"]
        captured["expected_policy"] = policy
        captured["producer"] = source
        captured["consumer"] = source
        dump(report / "complete.json", captured)
