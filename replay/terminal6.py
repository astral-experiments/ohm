"""Usage: python3 replay/terminal6.py PAIR SDK5 SDK6 OUTPUT"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import history as h

WINDOWS = {
    "utf8": ("4933645d81498e53ea150f96bde5860f6dcb2e5f",
             "a95835b2760dc7e17d4e375b2a30cd707c24e849",
             "fdf7d95485ec69c599418b7e7154baa4518fed2c"),
    "derive": ("6892bc2b7efe5909cbbeec8f757ed2c4c76b1d30",
               "9d07a922605313dc47b78b802c7b0616fd76d409"),
    "bounds": ("91f5d22ef48bde459d90a8c7dbeab416e97d0f2b",
               "178cc027e283fd965cb72d0a7395b219eada170c"),
}


def controls(work, cargo, env, out, candidate):
    src = work / "fixture"
    src.mkdir()
    checks = {}
    fresh = work / "fresh"
    root = Path(env["CARGO_TARGET_DIR"])
    def put(path, source):
        path = src / path
        path.parent.mkdir(exist_ok=True, parents=True)
        path.write_text(source + "\n")
    def invoke(name, *args, error=False, expect=None, avoid=None, audit=False):
        def run(target, phase):
            p = subprocess.run([cargo, *args, "-v", "--offline", "--message-format=json"],
                               cwd=src, env={**env, "CARGO_TARGET_DIR": str(target)},
                               capture_output=True, text=True)
            (out / f"{name}-{phase}.log").write_text(p.stderr + p.stdout)
            diagnostics = [event["message"] for line in p.stdout.splitlines()
                           if (event := json.loads(line))["reason"] == "compiler-message"]
            if p.returncode != (101 if error else 0):
                raise RuntimeError(f"{name}: {p.stderr[-1500:]} {diagnostics}")
            if error:
                assert any((msg["code"] or {}).get("code") == "E0080" for msg in diagnostics)
            return p.stderr, diagnostics
        log, ds = run(root, "warm")
        if candidate:
            assert not expect or expect in log, (name, expect, log[-1600:])
            assert not avoid or avoid not in log, (name, avoid, log[-1600:])
        if audit:
            _, clean = run(fresh, "fresh")
            assert ds == clean, (name, ds, clean)
            shutil.rmtree(fresh)
        checks[name] = dict(checked_fresh=audit, messages=ds)
        return ds
    package = lambda name: f"[package]\nname='{name}'\nversion='0.1.0'\nedition='2024'\n"
    def binary(bin, name, **kwargs):
        return invoke(name, "check", "-p", "app", "--bin", bin, **kwargs)

    put("Cargo.toml", package("app") + "[workspace]\n[dependencies]\ndep={path='dep'}")
    put("dep/Cargo.toml", package("dep"))
    f = "pub fn f<'a, 'b: 'a, 'c>(x: &'a str, _: &'b str, _: &'c str) -> &'a str { x }"
    put("dep/src/lib.rs", f)
    put("src/bin/a.rs", """fn main() { dep::f::<'static, 'static>("", "", ""); }""")
    put("src/bin/b.rs", """fn main() { dep::f("", "", ""); }""")
    terminal = "-Zohm-terminal-check-hash"
    assert "lib.rs:1:22" in str(binary("a", "first-warning"))
    binary("b", "first-clean")
    put("dep/src/lib.rs", "\n" * 10 + f)
    binary("b", "move", expect=terminal, avoid="--crate-name b ")
    assert "lib.rs:11:22" in str(binary("a", "switch", audit=True))
    cache, = root.rglob("output-bin-a")
    cache.unlink()
    put("dep/src/lib.rs", f)
    assert "lib.rs:1:22" in str(binary("a", "lost-warning", avoid=terminal, audit=True))

    put("Cargo.toml", (src / "Cargo.toml").read_text() + "observe={path='observe'}")
    put("observe/Cargo.toml", package("observe") + "[lib]\nproc-macro=true")
    put("observe/src/lib.rs", """use proc_macro::TokenStream;
#[proc_macro]
pub fn line(input: TokenStream) -> TokenStream {
    input.into_iter().next().unwrap().span().line().to_string().parse().unwrap()
}""")
    for name, producer, expr in (
        ("constant", "pub const fn at() -> u32 {core::panic::Location::caller().line()}", "dep::at()"),
        ("macro", "#[macro_export] macro_rules! at { () => {observe::line!(ink)} }", "dep::at!()"),
    ):
        producer = "#[derive(Debug, Clone)] pub struct Ink(pub u32);\n" + producer
        put("dep/src/lib.rs", producer)
        put("src/bin/b.rs", f"const _: () = assert!({expr} == 2); fn main() {{}}")
        binary("b", name + "-seed")
        put("dep/src/lib.rs", "\n" + producer)
        binary("b", name + "-move", error=True, audit=True)

    put("dep/src/lib.rs", "")
    put("dep/build.rs", """fn main() {
    let out = std::env::var("OUT_DIR").unwrap();
    println!("cargo::rerun-if-changed=generated.rs");
    println!("cargo::rustc-link-search={out}");
    assert!(std::process::Command::new(std::env::var_os("RUSTC").unwrap())
        .args(["--crate-type=rlib", "generated.rs", "--out-dir", &out])
        .status().unwrap().success());
}""")
    put("dep/generated.rs", "pub const VALUE: u32 = 1;")
    put("src/bin/b.rs", "extern crate generated; const _: () = assert!(generated::VALUE == 1); fn main() {}")
    binary("b", "generated-seed")
    put("dep/generated.rs", "pub const VALUE: u32 = 2;")
    binary("b", "generated-update", error=True, audit=True)

    shutil.rmtree(src)
    shutil.rmtree(root)
    put("Cargo.toml", package("app") + "[workspace]\nmembers=['client']")
    put("client/Cargo.toml", package("client") + "[dependencies]\napp={path='..'}")
    reader = 'fn main() { println!("{}", app::value()); }'
    put("src/main.rs", "fn main() {}")
    put("client/src/main.rs", reader)
    full = "-Zohm-prefer-full-crate-hash"
    def edit(n):
        put("src/lib.rs", f"pub fn value() -> u8 {{ {n} }}")
    for cmd in ("check", "build"):
        edit(1)
        invoke(cmd + "-seed", cmd, "-p", "app")
        edit(2)
        invoke(cmd + "-unused", cmd, "-p", "app", expect=full)
    invoke("workspace", "build", "--workspace", avoid=full)
    assert subprocess.check_output([root / "debug/client"]) == b"2\n"
    put("src/main.rs", reader)
    for n in (3, 4):
        edit(n)
        invoke(f"use-{n}", "build", "-p", "app", avoid=full if n == 4 else None)
        assert int(subprocess.check_output([root / "debug/app"])) == n
    shutil.rmtree(src)
    shutil.rmtree(root)
    h.save(out / "controls.json", checks)
    print(out.name, "semantic checks passed", flush=True)


def run(pair, kits, out, work):
    h.calibrate(work, out)
    src = work / "rg"
    subprocess.run(["git", "init", "-q", src], check=True)
    h.git(src, "fetch", "-q", "--depth=4", "https://github.com/BurntSushi/ripgrep",
          *(seq[-1] for seq in WINDOWS.values()))
    sdk = work / "rustup/toolchains/ohm"
    sdk.parent.mkdir(parents=True)
    cargo, rustc = sdk / "bin/cargo", sdk / "bin/rustc"
    target = work / "target"
    env = dict(HOME=os.environ["HOME"], USER=os.environ["USER"], LANG="C.UTF-8",
               PATH=f"{sdk / 'bin'}:{os.environ['PATH']}", CARGO_HOME=str(work / "registry"),
               CARGO_BUILD_JOBS="4", CARGO_TARGET_DIR=str(target), CARGO_TERM_COLOR="never",
               RUSTUP_HOME=str(work / "rustup"), RUSTUP_TOOLCHAIN="ohm")
    result = {"pair": pair, "arms": {}}
    for role in (["control", "candidate"] if pair == 1 else ["candidate", "control"]):
        sdk.symlink_to(kits[role])
        folder = out / role
        folder.mkdir()
        driver, = (sdk / "lib").glob("librustc_driver-*.so")
        arm = dict(cargo=h.sha(cargo), rustc=h.sha(rustc), driver=h.sha(driver), windows={})
        result["arms"][role] = arm
        for case, seq in WINDOWS.items():
            rows = arm["windows"][case] = []
            trial = folder / case
            trial.mkdir()
            for i, commit in enumerate(seq):
                h.git(src, "checkout", "-q", "--detach", commit)
                if i == 0:
                    h.command([cargo, "fetch", "--locked", "--target", "x86_64-unknown-linux-gnu"],
                              src, env, trial / "fetch.log")
                else:
                    assert h.git(src, "rev-parse", "HEAD^").decode().strip() == seq[i - 1]
                receipt = trial / f"{i}.tsv"
                h.command([work / "meter", rustc, receipt, cargo, *h.CHECK, "-p", "ripgrep"],
                          src, env, trial / f"{i}.log")
                units = h.read_counts(receipt)
                tree = int(Path(str(receipt) + ".tree").read_text().split()[0])
                if i:
                    assert any(u["name"] == "ignore" for u in units)
                rows.append(dict(commit=commit, seed=i == 0, tree=tree, units=units,
                                 rustc=sum(u["instructions"] for u in units)))
                if i:
                    print(role, case, commit[:8], tree, [u["name"] for u in units], flush=True)
            h.compare_fresh(cargo, src, env, trial)
            audit = json.loads((trial / "audit.json").read_text())
            assert audit["warm_diagnostics"] == audit["fresh_diagnostics"], (role, case)
            rows[-1]["metadata_differences"] = [
                k for k, row in audit["outputs"].items() if row["warm"] != row["fresh"]]
            h.save(out / "terminal.json", result)
            shutil.rmtree(target)
        controls(work, cargo, env, folder, role == "candidate")
        sdk.unlink()
    for case in WINDOWS:
        def total(role):
            return sum(r["tree"] for r in result["arms"][role]["windows"][case][1:])
        print(case, f"{100*(total('candidate')/total('control')-1):+.2f}% whole-command instructions")
    result["complete"] = True
    h.save(out / "terminal.json", result)


if __name__ == "__main__":
    pair = int(sys.argv[1])
    assert pair in (1, 2)
    base, latest, output = map(Path, sys.argv[2:])
    output.mkdir(exist_ok=True, parents=True)
    with tempfile.TemporaryDirectory() as tmp:
        run(pair, dict(control=base, candidate=latest), output, Path(tmp))
