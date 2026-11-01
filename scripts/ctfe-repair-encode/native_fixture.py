"""Small ordinary native Cargo history for the real source-qualified C compiler; run in a disposable mount."""

import argparse
import gzip
import hashlib
import json
import shutil
import subprocess as sp
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import evidence as v

arg = argparse.ArgumentParser(description=__doc__)
for key in ("root", "output", "sdk", "manifest", "proxies", "gate"):
    arg.add_argument("--" + key, type=Path, required=True)
arg.add_argument("--method", choices=("preload", "ordinary", "notify"), default="preload")
arg.add_argument("--positive-observer", type=Path)
arg.add_argument("--registry", type=Path)
arg.add_argument("--runner-env", action="store_true")
arg.add_argument("mode", choices=["pass", "blocked"])
args = arg.parse_args()
m = args.root
SDK = args.sdk
out = args.output / args.mode
v.need(
    all(p.is_absolute() for p in (m, SDK, out, args.manifest, args.proxies, args.gate))
    and SDK.name == "ohm"
    and SDK.parent.name == "toolchains"
    and m.resolve() == m
    and not (m / "work").exists(),
    "wrong/occupied fixture roots",
)
out.mkdir()
cfg = json.loads(args.manifest.read_bytes())
v.need(
    cfg["source"] == "df2c077a113a709ab379c8ec34e62c94c7513325" and len(cfg["files"]) == 81,
    "wrong source SDK",
)
canonical = {k: [r[0], r[4], r[3]] for k, r in cfg["files"].items()}
v.need(
    hashlib.sha256(
        (json.dumps(canonical, sort_keys=True, separators=(",", ":")) + "\n").encode()
    ).hexdigest()
    == "a51417a5cb8bdc6d20570b879e52e19fd07c40e686410815544a113779b6ed57",
    "different real compiler distribution",
)


def save(name, x):
    (out / name).write_text(json.dumps(x, indent=1, sort_keys=True) + "\n")


def hashes():
    files = {
        str(p.relative_to(SDK)): [v.sha(p), p.stat().st_mode & 0o7777, p.stat().st_size]
        for p in SDK.rglob("*")
        if p.is_file()
    }
    assert files == {k: [r[0], r[3], r[4]] for k, r in cfg["files"].items()} and len(files) == 81
    return files


physical = hashes()
save("source.json", physical)


def live_inventory():
    rows = {}
    for k, (digest, mode, size) in physical.items():
        t = (SDK / k).stat()
        rows[k] = [digest, t.st_dev, t.st_ino, mode, size, t.st_mtime_ns, t.st_ctime_ns]
    return rows


save("sdk-files.json", live_inventory())
w = m / "work"
repo = m / "project"
tmp = m / "tmp"
control = m / "control"
ci = out / "control"
for p in (w / "target", w / "build", repo / "src", repo / "app/src", tmp, m / "cargo", control):
    p.mkdir(parents=True, exist_ok=True)
env = dict(
    PATH=str(args.proxies) + ":/usr/bin:/bin",
    HOME=str(m / "home"),
    TMPDIR=str(tmp),
    RUSTUP_HOME=str(SDK.parents[1]),
    CARGO_HOME=str(m / "cargo"),
    CARGO_TARGET_DIR=str(w / "target"),
    CARGO_BUILD_BUILD_DIR=str(w / "build"),
    CARGO_ENCODED_RUSTFLAGS="-Zohm-branch-cache=yes",
    RUSTUP_AUTO_INSTALL="0",
    CARGO_NET_OFFLINE="true",
    LC_ALL="C",
    GIT_CONFIG_NOSYSTEM="1",
    GIT_CONFIG_GLOBAL="/dev/null",
    GIT_AUTHOR_NAME="fixture",
    GIT_COMMITTER_NAME="fixture",
    GIT_AUTHOR_EMAIL="fixture@example.invalid",
    GIT_COMMITTER_EMAIL="fixture@example.invalid",
    GIT_AUTHOR_DATE="2026-11-01T00:00:00Z",
    GIT_COMMITTER_DATE="2026-11-01T00:00:00Z",
)


if args.runner_env:
    home = SDK.parents[2]
    proxies = home / ".cargo/bin"
    proxies.mkdir(exist_ok=True, parents=True)
    shutil.copy2(args.proxies / "rustup", proxies / "rustup")
    import os

    for name in ("cargo", "rustc", "rustdoc"):
        os.link(proxies / "rustup", proxies / name)
    env.update(
        HOME=str(home),
        CARGO_HOME=str(home / ".cargo"),
        PATH=str(proxies) + ":/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        LD_LIBRARY_PATH=str(SDK / "lib"),
        CARGO_CACHE_AUTO_CLEAN_FREQUENCY="never",
        CARGO_TERM_COLOR="never",
    )
    save(
        "host-ownership.json",
        {
            f: [os.stat(f).st_uid, os.stat(f).st_mode]
            for f in ("/usr/bin/ar", "/usr/bin/gcc", "/usr/bin/perl")
        },
    )
    assert all(os.stat(f).st_uid == 0 for f in ("/usr/bin/ar", "/usr/bin/gcc", "/usr/bin/perl"))
if args.registry:
    seed = args.registry
    original = next((seed / "cache").iterdir()).name
    target = original
    picks = [
        ("cache", "itoa-1.0.15.crate", "4a5f13b858c8d314ee3e8f639011f7ccefe71f97f96e50151fb991f267928e2c"),
        ("index", ".cache/it/oa/itoa", "68eb575db6ce9b2e63daf948f499dd0b7298924765612ef5a799a87c4ebb575a"),
    ]
    for top, name, digest in picks:
        src = seed / top / original / name
        assert v.sha(src) == digest
        dst = Path(env["CARGO_HOME"]) / "registry" / top / target / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    shutil.copyfile(
        seed / "index" / original / "config.json",
        Path(env["CARGO_HOME"]) / "registry/index" / target / "config.json",
    )


def run(args, code=0, env_=None):
    c = sp.run(args, cwd=repo, env=env_ or env, capture_output=True)
    if c.returncode != code:
        fail = out / "refusal"
        fail.mkdir(exist_ok=True)
        (fail / "command.json").write_text(
            json.dumps(dict(argv=list(map(str, args)), status=c.returncode), sort_keys=True) + "\n"
        )
        for name, data in [("stdout", c.stdout), ("stderr", c.stderr)]:
            (fail / (name + ".gz")).write_bytes(gzip.compress(data, mtime=0))
        if control.is_dir():
            shutil.copytree(control, fail / "control", dirs_exist_ok=True)
        print(args, c.stdout[-1000:], c.stderr[-2600:], flush=True)
        raise RuntimeError(c.returncode)
    return c


def git(*args):
    return run(["git", *args]).stdout.decode().strip()


def source(value, bad=False):
    text = "#[inline(never)] pub fn value() -> u32 { " + str(value) + " }\n"
    for i in range(225):
        text += f"#[inline(never)] pub fn material_{i}(x:u32)->u32{{std::hint::black_box(x).wrapping_add({i}+{value})}}\n"
    if bad:
        text += "const WRONG: () = 1u32;\n"
    (repo / "src/lib.rs").write_text(text)


def commit(n):
    git("add", ".")
    git("-c", "commit.gpgSign=false", "commit", "-qm", n)


def build(label, expect, hook=False):
    ee = env
    if hook and args.method == "preload":
        ee = env | dict(
            LD_PRELOAD=str(m / "gate.so"),
            OHM_QA_PACK_CONTROL=str(control),
            OHM_QA_PACK_RUSTC=str(SDK / "bin/rustc"),
            OHM_QA_PACK_CARGO=str(SDK / "bin/cargo"),
            OHM_QA_PACK_WILD=str(SDK / v.WILD),
        )
    prefix = []
    if hook and args.method in ("ordinary", "notify"):
        if args.positive_observer:
            prefix = [str(args.positive_observer), str(out / "positive.tsv"), "--"]
        else:
            prefix = [
                "/usr/bin/strace",
                "--kill-on-exit",
                "-f",
                "-qq",
                "-s",
                "262144",
                "-e",
                "trace=execve,execveat",
                "-o",
                str(out / ("actual.exec" if args.method == "notify" else "ordinary.exec")),
                "--",
            ]
        if args.method == "notify":
            prefix.extend([str(args.gate), str(control), str(SDK), str(control / "notify.status"), "--"])
    if hook and args.positive_observer:
        import contact_kernel

        catalog_args = (
            SDK,
            Path(env["PATH"].split(":")[0]),
            args.gate if args.method == "notify" else None,
        )
        save("exec-before.json", contact_kernel.catalog(*catalog_args))
    c = run(
        prefix
        + [
            "cargo",
            "+ohm",
            "build",
            "--locked",
            "--offline",
            "-j2",
            "-p",
            "repair_app",
            "--message-format=json",
        ],
        101 if expect is None else 0,
        ee,
    )
    if hook and args.positive_observer:
        save("exec-after.json", contact_kernel.catalog(*catalog_args))
    save(label + ".command.json", dict(argv=c.args, status=c.returncode, source=v.sha(repo / "src/lib.rs")))
    for k, b in [("stdout", c.stdout), ("stderr", c.stderr)]:
        (out / (label + "." + k + ".gz")).write_bytes(gzip.compress(b, mtime=0))
    events = [json.loads(s) for s in c.stdout.splitlines()]
    assert events[-1] == {"reason": "build-finished", "success": expect is not None}
    if expect is None:
        assert any((e.get("message", {}).get("code") or {}).get("code") == "E0308" for e in events)
        return
    exe = Path(next(e["executable"] for e in events if e.get("executable")))
    b = run([exe])
    assert b.stdout == f"{expect}\n".encode()
    save(
        label + ".native.json",
        dict(argv=[str(exe)], stdout=b.stdout.decode(), status=b.returncode, elf=v.sha(exe)),
    )
    if label == "repair":
        shutil.copyfile(exe, m / "retained-repair")
        shutil.copyfile(exe, out / "repair.elf")
    if label in ("settled", "empty"):
        sp.run(["cmp", "--", exe, m / "retained-repair"], check=True)
    return v.sha(exe)


git("init", "-q", "-b", "role-y")
(repo / "Cargo.toml").write_text(
    '[package]\nname="repair_dep"\nversion="0.1.0"\nedition="2024"\n[workspace]\nmembers=["app"]\nresolver="3"\n'
)
(repo / "app/Cargo.toml").write_text(
    '[package]\nname="repair_app"\nversion="0.1.0"\nedition="2024"\n[dependencies]\nrepair_dep={path=".."}\n'
)
if args.registry:
    with (repo / "Cargo.toml").open("a") as fd:
        fd.write('[dependencies]\nitoa="=1.0.15"\n')
(repo / "app/src/main.rs").write_text('fn main(){println!("{}",repair_dep::value());}\n')
source(17)
run(["cargo", "+ohm", "generate-lockfile", "--offline"])
commit("B")
build("Y-B", 17)
git("switch", "-qc", "role-x")
source(29)
commit("A")
build("X-A", 29)
source(17)
commit("X-B")
build("X-B", 17)
git("switch", "-q", "role-y")
source(37, True)
build("invalid", None)
time.sleep(11)
source(37)
(dep,) = list(w.rglob("repair_dep-*/*/ohm-packed-dep-graph.bin"))[:1]
owner = dep.parent.parent.name
before = v.sessions(w, {owner})
path = before["owners"][owner]
apps = [p.name for p in (Path(path).parent).glob("repair_app-*") if p.is_dir()]
assert len(apps) == 1
(control / "config").write_text(("B" if args.mode == "blocked" else "P") + "\n" + path + "\n")
if args.method == "preload":
    shutil.copyfile(args.gate, m / "gate.so")
if args.method == "notify":
    (control / "owners").write_text(path + "\n" + str(Path(path).parent / apps[0]) + "\n")
elf = build("repair", 37, True)
# Preserve native evidence even when a stronger proposed gate rejects this local attempt.
shutil.copytree(control, ci)
after = v.sessions(w, {owner})
save("before.json", before)
save("after.json", after)
if args.method != "ordinary":
    images, events = v.physical(control, SDK, [path], kernel=args.method == "notify")
    save("events.json", events)
    save("images.json", images)
    report = v.certify(
        before, after, images, events, [owner], args.mode == "blocked", extra_passthrough=apps
    )
    save("objects.json", report)
    (wild,) = [
        x["argv"][x["argv"].index("-o") + 1]
        for x in images.values()
        if x["role"] == "wild" and "-o" in x["argv"]
    ]
    assert Path(wild).samefile(w / "target/debug/repair_app") and elf == v.sha(wild)
    save(
        "link.json", dict(path=wild, file=v.ident(Path(wild)), cargo=v.ident(w / "target/debug/repair_app"))
    )
post = build("settled", 37)
assert post == elf
for name in ("target", "build"):
    shutil.rmtree(w / name)
    (w / name).mkdir()
empty = build("empty", 37)
assert elf == empty
if args.method == "ordinary":
    save("result.json", dict(cli=elf, empty=empty, source=cfg["source"], method=args.method))
    raise SystemExit(0)
links = [
    x["argv"][x["argv"].index("-o") + 1]
    for x in images.values()
    if x["role"] == "wild" and "-o" in x["argv"]
]
assert len(links) == 1
assert {r["role"] for r in images.values()} == {"cargo", "rustc", "wild"} and len(images) == 4
save(
    "result.json",
    dict(
        mode=args.mode,
        owner=owner,
        runtime=37,
        cli=elf,
        empty=empty,
        objects=sum(len(x["objects"]) for x in report.values()),
        packed_objects=sum(o["packed"] for x in report.values() for o in x["objects"].values()),
        source=cfg["source"],
        driver=v.sha(SDK / v.DRIVER),
        wild=v.sha(SDK / v.WILD),
        gate=v.sha(args.gate),
        method=args.method,
        identical_reopened=hashes() == json.loads((out / "source.json").read_bytes()),
    ),
)
print((out / "result.json").read_text())
