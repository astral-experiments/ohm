"""Measure the two admitted compilers on fresh regular Ruff Cargo check and linked-library builds."""

from collections import defaultdict
from pathlib import Path
import gzip
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
point = HERE.parent / "strict-unwrapped-profile/study.py"
for rel, digest in (
    (
        "strict-unwrapped-profile/study.py",
        "1f2485440758b580e4f8de9d987592d3bc09060a5261329c36fa6036514958ac",
    ),
    (
        "strict-unwrapped-profile/prior.json",
        "110096a8c37e207a6a685a705868ed9fcd1de1f03d45f3e657ff751b450927f2",
    ),
    (
        "strict-share-bridge/bridge.py",
        "edfb13fd3745e9c556eba45a0bcd9eac7e514144320159a9ed750ce95b3be96c",
    ),
):
    assert hashlib.sha256((HERE.parent / rel).read_bytes()).hexdigest() == digest
spec = importlib.util.spec_from_file_location("ordinary_enrollment", point)
normal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(normal)
s, b, m = normal.s, normal.b, normal.m
R, S, O = m.R, m.S, m.O
LIB = "lib/rustlib/x86_64-unknown-linux-gnu/lib"
SEAL = json.loads((HERE / "custody" / "inputs" / "native-seal.json").read_bytes())
BOX = Path(os.environ["RUNNER_TEMP"]) / "admitted-native-kits"
role = {"P": "parent", "C": "candidate"}
letter = {"0": "A", "1": "B", "2": "C"}
history = {"01": "P0 C0 C1 P1 P2 C2".split(), "02": "C2 P2 P1 C1 C0 P0".split()}
source_direction = {"01": "reverse", "02": "forward"}
common_generated = {
    "generated.rs": "9b5eca67ab5970e513c5eb40dab5e9418f981cb0bc62167604396e760dc1184f",
    "generated_alias.rs": "9f5a28cda43b481b11d8dc6e1bf0f7579cacdf9489e3166ce6e3144a5d017e9f",
    "generated_phf.rs": "4812faa3a82d2a02ac004df2fbde343185927dd71dce1d6cf23b22e94385b855",
}
FORBID = normal.forbidden | {
    "RUSTC_BOOTSTRAP",
    "CARGO_BUILD_RUSTFLAGS",
    "LD_PRELOAD",
    "LD_LIBRARY_PATH",
    "CARGO_PROFILE_DEV_BUILD_OVERRIDE_OPT_LEVEL",
}
DRIVERS = {
    "parent": "b83289a6adecf1a24b790dcff1a42d77337909349c5745677485f8e914627447",
    "candidate": "5af5a6a20ccb67bdf4196ca2f3df5677ce19076f66110a955e903e32b124889c",
}
HOST = "x86_64-unknown-linux-gnu"


def config(level):
    if level == "0":
        return None
    assert level in ("1", "2")
    return f"[profile.dev.package.ruff_unicode_names2_generator]\nopt-level = {level}\n".encode()


def settings(env, level):
    assert not (FORBID & env.keys())
    p = Path(env["CARGO_HOME"]) / "config.toml"
    assert (
        p.parent == S / "cargo-home" and not p.is_symlink() and not (p.parent / "config").exists()
    )
    was = p.read_bytes() if p.exists() else None
    assert was in [config(i) for i in "012"]
    want = config(level)
    if want != was:
        if want is None:
            p.unlink()
        else:
            fresh = p.with_name("incoming-real-compiler-config")
            assert not fresh.exists()
            fresh.write_bytes(want)
            fresh.replace(p)
    assert (p.read_bytes() if p.exists() else None) == want


def stamp(p):
    s = p.stat()
    assert p.is_file() and not p.is_symlink()
    return [s.st_dev, s.st_ino, s.st_ctime_ns, s.st_size, s.st_mode & 0o777]


class Toolchains:
    def __init__(self, env):
        assert R.parent.resolve() == BOX.parent.resolve() and BOX.is_dir() and not BOX.is_symlink()
        assert m.read(BOX / "admission.json") == SEAL
        self.env = env
        self.active = None
        self.manifests = {}
        self.stamps = {}
        self.use = []
        for short, name in role.items():
            d = BOX / name
            manifest = m.read(BOX / (name + ".json"))
            self.manifests[short] = manifest
            assert (
                manifest["qa"] == SEAL["head"]
                and manifest["tree"] == SEAL["roles"][name]["tree"]
                and manifest["transfer"] == SEAL["roles"][name]["transfer"]
            )
            assert (
                len(manifest["files"]) == 68
                and not d.is_symlink()
                and {str(v.relative_to(d)) for v in d.rglob("*") if v.is_file()}
                == manifest["files"].keys()
            )
            self.stamps[short] = {k: stamp(d / k) for k in manifest["files"]}
            for k, (digest, size, mode) in manifest["files"].items():
                assert self.stamps[short][k][-2:] == [size, mode] and m.sha(d / k) == digest
            (dr,) = (d / "lib").glob("librustc_driver*.so")
            (std,) = (d / LIB).glob("libstd-*.rlib")
            assert (
                m.sha(dr) == DRIVERS[name]
                and m.sha(d / "bin/rustc")
                == "8bfdc9779937e9cd2c9ef5db9f50cee9aab03ddec5672b37a3a3c9278cf1f5d0"
            )
            assert (
                m.sha(d / "bin/cargo")
                == "035e681081683f4141e4c544b8cf9492b73784051e4541c12bb3cbdb73a798a4"
                and m.sha(d / "lib/rustlib" / HOST / "bin/wild-ld/ld.bfd")
                == "0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5"
            )
            m.save(O / ("native-manifest-" + short + ".json"), manifest)
            nodes = list(d.rglob("*"))
            unique = {(v.stat().st_dev, v.stat().st_ino): v.stat().st_blocks for v in [d, *nodes]}
            stored = sum(unique.values()) * 512
            calc = int(m.get(["du", "-s", "-B1", d]).split()[0])
            assert calc == stored
            m.save(
                O / ("native-storage-" + short + ".json"),
                {
                    "archive_physical_B": stored,
                    "logical_files_B": sum(v[1] for v in manifest["files"].values()),
                    "files": len(manifest["files"]),
                    "specimen_B": sum(v.stat().st_blocks * 512 for v in (d / "specimen").glob("*")),
                    "driver": str(dr.relative_to(d)),
                    "std": str(std.relative_to(d)),
                },
            )
        original = R / "initial-signed-tools-unused-for-measurement"
        assert not original.exists() and b.sdk == R / "sdk-21"
        assert (
            (Path(env["RUSTUP_HOME"]) / "toolchains/ohm").resolve() == b.sdk
            and not (S / "target").exists()
            and not (S / "shared").exists()
        )
        b.sdk.rename(original)

    def select(self, short, level):
        if short != self.active:
            assert (
                not (S / "target").exists() and not (S / "shared").exists()
            ), "runtime change with a populated measured root"
            if self.active is not None:
                parked = BOX / role[self.active]
                assert not parked.exists()
                self.assert_binaries(self.active)
                b.sdk.rename(parked)
            assert not b.sdk.exists()
            src = BOX / role[short]
            assert src.parent == BOX and src.is_dir() and not src.is_symlink()
            src.rename(b.sdk)
            self.active = short
            self.prove_selected(short)
        settings(self.env, level)
        return self.env

    def assert_binaries(self, short):
        assert self.stamps[short] == {n: stamp(b.sdk / n) for n in self.manifests[short]["files"]}

    def prove_selected(self, short):
        self.assert_binaries(short)
        assert (Path(self.env["RUSTUP_HOME"]) / "toolchains/ohm").samefile(b.sdk)
        sysroot = Path(
            m.get(["rustc", "+ohm", "--print", "sysroot"], env=self.env).decode().strip()
        )
        lib = Path(
            m.get(["rustc", "+ohm", "--print", "target-libdir"], env=self.env).decode().strip()
        )
        assert sysroot.samefile(b.sdk) and lib.samefile(b.sdk / LIB)
        cargo = m.get(["cargo", "+ohm", "-Vv"], env=self.env).decode()
        version = m.get(["rustc", "+ohm", "-vV"], env=self.env).decode()
        assert (
            "761ea115605c34f11a1cd29afd68812c1e1359dd" in cargo
            and version.startswith("rustc 1.99.0-dev\n")
            and "host: " + HOST in version
        )
        out = O / ("selection-" + str(len(self.use)) + "-" + short)
        out.mkdir()
        (dr,) = (b.sdk / "lib").glob("librustc_driver*.so")
        args = [
            "strace",
            "-f",
            "-s",
            "4096",
            "-qq",
            "-e",
            "trace=openat,openat2",
            "-o",
            out / "real-open.tsv",
            "rustc",
            "+ohm",
            "--print",
            "target-libdir",
        ]
        returned = Path(m.get(args, env=self.env).decode().strip())
        assert returned.samefile(lib)
        opens = []
        for ln in (out / "real-open.tsv").read_text().splitlines():
            if "librustc_driver" not in ln:
                continue
            mt = re.search(r'(?:openat|openat2)\([^"]*"([^"]+)"[^\n]*\)\s+=\s*[0-9]+$', ln)
            if mt:
                opens.append(Path(mt[1]))
        assert opens and all(p.is_absolute() and p.samefile(dr) for p in opens)
        source = self.manifests[short]
        infos = {
            n: {
                "file": str(f.resolve()),
                "sha256": m.sha(f),
                "dev_ino": stamp(f)[:2],
                "ctime_ns": stamp(f)[2],
            }
            for n, f in (("rustc", b.rust), ("cargo", b.cargo), ("driver", dr), ("wild", b.wild))
        }
        assert infos["driver"]["sha256"] == DRIVERS[role[short]]
        m.save(
            out / "selection.json",
            {
                "role": short,
                "tree": source["tree"],
                "argv": list(map(str, args)),
                "driver_opens": list(map(str, opens)),
                "version": version,
                "cargo": cargo,
                "sysroot": str(sysroot),
                "target_libdir": str(lib),
                "tools": infos,
                "kit_files": len(source["files"]),
            },
        )
        self.use.append({"role": short, "version": version, "tools": infos, "record": out.name})
        m.save(O / "all-selections.json", self.use)


def settings_probe(where, env, level, ref):
    (r,) = ref["kernel"]["selected"]["unicode_names2_generator"]
    a = r["argv"]
    info = b.argspec(a)
    assert (
        info["opt"] == level
        and info["debug"] == info["overflow"] == "on"
        and not any("share-generics" in x for x in a)
    )
    d = R / ("native-check-settings-" + where.name)
    d.mkdir()
    src = d / "probe.rs"
    src.write_text(
        'fn main(){std::panic::set_hook(Box::new(|_|{}));let n=std::hint::black_box(255u8);println!("{} {} {}",cfg!(debug_assertions),std::panic::catch_unwind(||debug_assert!(std::hint::black_box(false))).is_err(),std::panic::catch_unwind(||n+std::hint::black_box(1)).is_err());}\n'
    )
    out = d / "probe"
    argv = [
        "rustc",
        "+ohm",
        "--edition=2024",
        src,
        "-o",
        out,
        *[z for k, v in sorted(info["options"].items()) for z in ("-C", k + "=" + v)],
    ]
    m.run(argv, env=env)
    ran = m.get([out], env=env)
    assert ran == b"true true true\n"
    m.save(
        where / "checks.json",
        {"actual_scope": a, "probe": list(map(str, argv)), "stdout": ran.decode()},
    )


def symbols(where):
    lib = Path(m.read(where / "empty-edited/held-generator-rlib.json")["path"])
    assert lib.is_file()
    for lab, flag in (("defined", "--defined-only"), ("imported", "--undefined-only")):
        p = subprocess.run(
            ["nm", "--demangle=rust", "--format=posix", flag, lib],
            capture_output=True,
            check=True,
            env={"PATH": os.environ["PATH"], "LC_ALL": "C"},
        )
        m.gz(where / ("library-symbols-" + lab + ".gz"), p.stdout)
        m.gz(where / ("nm-" + lab + "-stderr.gz"), p.stderr)
        assert p.stdout.strip()


def driver_flank(where, env, which):
    place = where / "actual-cargo-driver"
    place.mkdir()
    temp = R / ("actual-compilation-open-" + where.name)
    temp.mkdir()
    (drv,) = (b.sdk / "lib").glob("librustc_driver*.so")
    cmd = [
        "strace",
        "-ff",
        "-qq",
        "-v",
        "-s",
        "65536",
        "-e",
        "trace=execve,openat,openat2",
        "-o",
        temp / "trace",
        *m.cmd,
    ]
    proc = subprocess.run(cmd, cwd=m.src, env=env, capture_output=True, timeout=240)
    m.gz(place / "stdout.gz", proc.stdout)
    m.gz(place / "stderr.gz", proc.stderr)
    with gzip.open(place / "all-process-opens.gz", "wb", compresslevel=1) as archive:
        for p in sorted(temp.glob("trace.*")):
            pid = str(int(p.name.split(".")[-1])).encode()
            with p.open("rb") as stream:
                for raw in stream:
                    archive.write(pid + b" " + raw)
            p.unlink()
    temp.rmdir()
    assert proc.returncode == 0
    typed = [json.loads(line) for line in proc.stdout.splitlines()]
    assert (
        typed[-1] == {"reason": "build-finished", "success": True}
        and sum(v["reason"] == "compiler-artifact" for v in typed) == 303
    )
    assert not any(v.get("message", {}).get("level") == "error" for v in typed)
    from opened_driver import inspect

    with gzip.open(place / "all-process-opens.gz", "rb") as archive:
        found = inspect(
            archive,
            lambda p: p.is_file() and p.samefile(b.rust),
            lambda p: p.is_file() and p.samefile(drv),
        )
    assert (
        sorted(x[1] for x in found) == ["build_script_build", "ron", "unicode_names2"]
        and m.sha(drv) == DRIVERS[role[which]]
    )
    m.save(
        place / "verified.json",
        {
            "role": which,
            "driver": str(drv),
            "sha256": m.sha(drv),
            "dev_ino": stamp(drv)[:2],
            "full_rustcs_opening_it": found,
            "args": list(map(str, cmd)),
        },
    )
    return s.generator(place, "unscored genuine Cargo driver proof")["sha256"]


def main():
    row = os.environ["QA_ROW"]
    seq = history[row]
    direction = source_direction[row]
    env = b.procure()
    for n in ("subjects", "strict"):
        (O / (n + ".json")).rename(O / ("initial-acquisition-" + n + ".json"))
    kits = Toolchains(env)
    m.save(
        O / "actual-compiler-enrollment.json",
        {
            "row": row,
            "host": os.uname().nodename,
            "sequence": seq,
            "direction": direction,
            "head": os.environ["GITHUB_SHA"],
            "run": os.environ["GITHUB_RUN_ID"],
            "plan": m.sha(HERE / "PLAN.md"),
            "seal": SEAL,
            "environment": env,
            "check": m.cmd,
            "source": m.c.RUFF,
            "history": m.hist,
            "configs": {l: None if config(l) is None else config(l).decode() for l in "012"},
        },
    )
    original = b.consumer.read_bytes()
    assert original == m.w.git(m.src, "show", "HEAD:crates/ty_project/src/lib.rs")
    diags = []
    logical = set()
    warnings = set()
    graphs = {}
    held = {}
    warm = {}
    for subject in seq:
        which, level = subject
        b.clear()
        kits.select(which, level)
        b.edited(direction == "forward")
        graphs[subject] = s.graph(env, subject)
        d = O / ("opt" + subject)
        images = set()
        m.save(d / "runtime.json", kits.use[-1])

        def visit(n, mode="score", rc=0, flank=None):
            assert kits.active == which and not (FORBID & env.keys())
            r = b.visit(subject, n, env, mode, rc)
            prog, rlib = normal.ancestor.retained(d / n, subject)
            images.add(prog)
            assert r["generated"] == common_generated
            if rc:
                diags.extend(r["errors"])
            else:
                assert not r["errors"] and r["typed"] == 303
                logical.add(r["logical_sha"])
                warnings.add(tuple(r["warning_sha"]))
            if mode == "trace":
                s.kernel(d / n, letter[level], n)
                normal.trace(d / n, letter[level], flank)
            return r

        cold = visit("cold")
        visit("neutral-unchanged")
        b.edited(direction != "forward")
        edit = visit("historical-edit")
        repeat = visit("first-unchanged")
        assert (
            cold["source"] != edit["source"] == repeat["source"] and "ty_project" in edit["dirty"]
        )
        visit("traced-unchanged", "trace", flank="check-repeat")
        assert driver_flank(d, env, which) in images
        b.consumer.write_bytes(original + b.BAD)
        bad = visit("warm-invalid", "ordinary", 101)
        b.consumer.write_bytes(original)
        visit("warm-repair", "ordinary")
        b.clear()
        ref = visit("empty-edited", "trace", flank="check-cold")
        symbols(d)
        settings_probe(d, env, level, ref)
        b.clear()
        b.consumer.write_bytes(original + b.BAD)
        badref = visit("empty-invalid", "ordinary", 101)
        b.consumer.write_bytes(original)
        visit("empty-repair", "ordinary")
        assert bad["errors"] == badref["errors"] and len(images) == 1
        held[subject] = next(iter(images))
        warm[subject] = [
            cold["instructions"],
            edit["instructions"],
            repeat["instructions"],
            repeat["storage"]["allocated_B"],
        ]
        kits.assert_binaries(which)
        b.clear()
    assert (
        len(logical) == len(warnings) == 1
        and len(diags) == 12
        and all(v == diags[0] for v in diags)
    )
    for level in "012":
        same = graphs["P" + level]
        assert same == graphs["C" + level] and sum(len(v) for v in same.values()) == 338
        (entry,) = [v for k, v in same.items() if "ruff_unicode_names2_generator#" in k]
        assert (
            len(entry) == 1
            and entry[0]["opt_level"] == level
            and not entry[0].get("rustflags")
            and entry[0]["debug_assertions"]
            and entry[0]["overflow_checks"]
        )
    for which in "PC":
        a = graphs[which + "0"]
        for level in "12":
            g = graphs[which + level]
            assert a.keys() == g.keys()
            changed = [k for k in a if a[k] != g[k]]
            assert len(changed) == 1 and "ruff_unicode_names2_generator" in changed[0]
            (orig,) = a[changed[0]]
            (current,) = g[changed[0]]
            assert orig | {"opt_level": level} == current
    m.save(
        O / "check-verified.json",
        {
            "neutral_elf": held,
            "check": warm,
            "graphs_and_errors": True,
            "generated": common_generated,
        },
    )
    import builds

    for level in "012" if row == "01" else "210":
        first = next(t[0] for t in seq if t[1] == level)
        order = "01" if first == "P" else "10"
        builds.study(
            b, env, lambda e, i: kits.select("PC"[int(i)], level), s.keep_elf, direction, order
        )
        d = O / ("linked-opt" + level)
        (O / "ordinary-lib").rename(d)
        (R / "reader-stable").rename(R / ("reader-stable-" + level))
        for i, which in enumerate("PC"):
            # Reopen the saved physical identifiers for the matching role. This extra activation is outside every measured window.
            kits.select(which, level)
            for n, flank in (
                ("independent-empty", "build-cold"),
                ("traced-repeat", "build-repeat"),
            ):
                normal.trace(d / ("opt" + str(i)) / n, letter[level], flank)
            m.save(d / ("opt" + str(i)) / "runtime.json", kits.use[-1])
        b.clear()
    from provider import check

    check(m, b.load, b.NATIVE, env, lambda e, i: kits.select("PC"[int(i)], "1"), b.wild)
    assert not b.wild.with_name("libutil.so").exists() and b.consumer.read_bytes() == original
    b.edited(False)
    settings(env, "0")
    assert len({x["version"] for x in kits.use}) == 1
    m.save(
        O / "complete.json",
        {
            "row": row,
            "sequence": seq,
            "input": "fresh compiler/profile for every measured installation",
            "all_sources": common_generated,
            "ordinary": True,
            "provider_mode": "same generator opt 1 on both physical compilers",
        },
    )
    from decision import compare

    m.save(O / "same-profile-decision.json", compare(O))
    print("qualified ordinary actual compiler", row, flush=True)


if __name__ == "__main__":
    main()
