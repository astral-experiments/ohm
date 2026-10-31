"""Exercise the old full-CLI linked-archive fixture and the genuine Ruff generator side by side."""

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import bindings as b
from bindings import need, save, sha, ROOT, OUT, SDK

BASE = "93526150df078af7dd8fc4226cdcc469539d2001"
SUBTREE = "6204e19cfc0fc74f827f8bd5d2f7d807d7045272"
LOCK = "c9e345325bec5ff08dbbe3916edd39ad0c3d1c7797a8c241ae32f62754e764bf"
MODULES = {
    "capture.py": "24bfc17dd20d773f147ec7581a6ad22e6d8cfbc513bf2c7697be21a7d48dcb1c",
    "observed.py": "3c38e842e9b8964f0d9411daa2058f2ebf49a704cba2721ece7d6ec7bd1f1cb4",
    "provider.c": "6d0b6d6a618c047ab78a894b70aa8cb8a693cde2b1d1ef73e290aec60994f3d4",
}
D = ROOT / "host-unicode-wild-dir-v1"
SIDE = SDK / b.WILD
SIDE = SIDE.with_name("libutil.so")


def open_provider(repo, env):
    donor = repo / "scripts/linux-294-parent"
    b.prepare_checkout(repo, b.DONOR, "scripts/linux-294-parent")
    need({n: sha(donor / n) for n in MODULES} == MODULES, "wrong native control and reader")
    D.mkdir()
    src = D / "source"
    subprocess.run(["git", "init", "--quiet", "--template=", src], check=True)
    b.git(
        src,
        "fetch",
        "--quiet",
        "--no-tags",
        "--depth=1",
        "https://github.com/astral-sh/ruff.git",
        BASE,
    )
    b.git(src, "checkout", "--detach", "-q", "FETCH_HEAD")
    need(
        b.git(src, "rev-parse", "HEAD", "HEAD:crates/ruff_unicode_names2").splitlines()
        == [BASE, SUBTREE]
        and sha(src / "Cargo.lock") == LOCK,
        "wrong Unicode generator source",
    )
    native = D / "native"
    native.mkdir()
    provider = donor / "provider.c"
    local = D / "cargo-home"
    local.mkdir()
    fetch = env | {"CARGO_HOME": str(local), "CARGO_NET_OFFLINE": "false"}
    subprocess.run(["cargo", "+ohm", "fetch", "--locked"], cwd=src, env=fetch, check=True)
    lock = {
        p["name"] + "-" + p["version"] + ".crate": p["checksum"]
        for p in tomllib.loads((src / "Cargo.lock").read_text())["package"]
        if "checksum" in p
    }
    need(
        len(lock) == 498
        and {p.name: sha(p) for p in (local / "registry/cache").glob("*/*.crate")} == lock,
        "foreign provider registry seed",
    )
    for tag, value in [("83", "0053"), ("47", "002F")]:
        dest = native / ("observe-" + tag + ".so")
        subprocess.run(
            [
                "cc",
                "-shared",
                "-fPIC",
                "-O2",
                '-DREPLACE_CODE="' + value + '"',
                provider,
                "-Wl,-soname," + str(SIDE),
                "-ldl",
                "-o",
                dest,
            ],
            check=True,
        )
        dyn = subprocess.check_output(["readelf", "-dW", dest])
        need(("[" + str(SIDE) + "]").encode() in dyn, "wrong loader soname")
        shutil.copy2(dest, OUT / "providers" / dest.name)
    need(
        (native / "observe-83.so").stat().st_size == (native / "observe-47.so").stat().st_size,
        "same-size negative control unavailable",
    )
    cfg = D / "fixture.json"
    save(
        cfg,
        dict(
            private_state=str(D),
            ruff=str(src),
            proxy=str(b.PROXIES),
            signed_sdk=str(SDK),
            effective_home=str(b.HOME),
            registry_home=str(local),
            roles={},
            qa=b.DONOR,
        ),
    )
    old_args = sys.argv
    sys.argv = [str(donor / "capture.py"), str(cfg), "unused"]
    try:
        spec = importlib.util.spec_from_file_location(
            "branch_return_unicode_fixture", donor / "capture.py"
        )
        c = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(c)
    finally:
        sys.argv = old_args
    c.SDK = SDK
    c.SIDE = SIDE
    c.rec = OUT / "providers"
    save(
        OUT / "providers" / "corpus.json",
        dict(
            source=BASE,
            locked=LOCK,
            workspace_subtree=SUBTREE,
            donor=b.DONOR,
            modules=MODULES,
            sha256={p.name: sha(p) for p in native.iterdir()},
            registry_count=len(lock),
            command=c.CARGO,
        ),
    )
    return c, local


def exercise(rows, repo, arms):
    from provider import native_controls

    start = OUT / "provider-seed"
    start.mkdir()
    base = b.activate(arms[0], rows, start)
    c, local = open_provider(repo, base)
    original_run = c.run
    for arm in arms:
        out = OUT / "providers" / arm
        out.mkdir()
        env = b.activate(arm, rows, out)
        native_controls(arm, env, ROOT, out)
        # Keep the established ordinary Cargo command. Profile selection is exactly the enclosing arm's.
        active = env | {
            "CARGO_HOME": str(local),
            "CARGO_TARGET_DIR": str(c.W / "target"),
            "CARGO_BUILD_BUILD_DIR": str(c.W / "shared"),
        }
        c.run = lambda *args, **kw: original_run(*args, **(kw | {"env": active}))
        hist = out / "history"
        hist.mkdir()
        empty = out / "empty"
        empty.mkdir()
        need(
            not SIDE.is_symlink()
            and not SIDE.exists()
            and SIDE.parent.resolve() == SIDE.parent
            and SIDE.parent.is_relative_to(SDK),
            "expected a pristine private Wild search directory",
        )
        phases = (
            ("absent", "absent", False),
            ("insert-83", "83", False),
            ("same-inode-47", "47", True),
            ("malformed", "bad", True),
            ("repair-47", "47", True),
            ("remove", "absent", False),
        )

        def visit(place, tag, mode, held):
            side = c.side(mode, held)
            result = c.phase(place, tag)
            save(place / tag / "provider.json", side)
            need(
                result["status"] == (101 if mode == "bad" else 0),
                ("unexpected provider verdict", arm, tag),
            )
            captures = result["physical"]["ld"]
            need(
                captures and all(Path(p).samefile(SDK / b.WILD) for _, p in captures),
                "missing actual Wild process",
            )
            sensitive = [
                q
                for q in result["search"]["probes"]
                if q["kind"] == "higher"
                and q["result"] >= 0
                and q["call"].startswith("open")
                and q["exe"]
            ]
            if mode != "absent":
                need(
                    any(
                        Path(q["exe"]).samefile(SDK / b.WILD)
                        for q in sensitive
                        if Path(q["exe"]).is_file()
                    ),
                    "Wild did not physically read higher-priority input",
                )
            if mode != "bad":
                need(
                    result["generate_code"] == {"absent": "0000", "83": "0053", "47": "002F"}[mode],
                    "stale data from actual Ruff native generator",
                )
                (generator,) = result["physical"]["generator"]
                prog = Path(generator[1])
                need(prog.is_file(), "returned generator missing")
                if mode != "absent":
                    need(
                        any(
                            Path(q["exe"]).samefile(prog)
                            for q in sensitive
                            if Path(q["exe"]).is_file()
                        ),
                        "generator runtime never physically loaded our provider",
                    )
            return [side, result]

        seen = {}
        references = {}
        try:
            with c.installation():
                for tag, mode, held in phases:
                    seen[tag] = visit(hist, tag, mode, held)
            for tag, mode, _ in phases[1:]:
                with c.installation():
                    references[tag] = visit(empty, tag, mode, False)
            for tag, (_, other) in references.items():
                prior = seen[tag][1]
                need(prior["status"] == other["status"], "different own-empty verdict")
                if prior["status"] == 0:
                    for key in ("generated", "reader", "reader_sha256"):
                        need(
                            prior[key] == other[key], ("own-empty generator output", arm, tag, key)
                        )
            held = [seen[k][0] for k in ("insert-83", "same-inode-47", "malformed", "repair-47")]
            need(
                len({(q["ino"], q["dev"], q["size"], q["mtime"]) for q in held}) == 1
                and len({q["sha256"] for q in held}) == 3,
                "not a same-inode size/mtime negative",
            )
            save(
                out / "complete.json",
                dict(
                    arm=arm,
                    source=BASE,
                    status={t: r["status"] for t, (_, r) in seen.items()},
                    values={t: r.get("generate_code") for t, (_, r) in seen.items()},
                    same_inode=held,
                ),
            )
        finally:
            c.side("absent")
    c.run = original_run
