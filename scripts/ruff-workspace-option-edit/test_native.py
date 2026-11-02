"""Exercise the real signed root .rlib, downstream client and post-exec collector on a two-crate fixture."""

import json
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import worker as w
import reopen
from worker import p


def put(dest, data):
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data if isinstance(data, bytes) else data.encode())


def fixture_source(repo, rev):
    source = p.git(repo, "show", rev + ":" + p.OPTIONS).decode()
    code = [
        "pub mod options {",
        "use ruff_options_metadata::{OptionsMetadata,OptionSet,Visit,OptionField};",
        "pub struct Options; pub struct Lint;",
        'impl OptionsMetadata for Options { fn record(v:&mut dyn Visit) {v.record_set("lint", OptionSet::of::<Lint>());} }',
        "impl OptionsMetadata for Lint { fn record(v:&mut dyn Visit) {",
    ]
    for key in (p.KEY, p.SIBLING):
        name = key.partition(".")[2]
        fields = p.field(source, name.replace("-", "_"))
        lit = lambda f: 'r##"' + fields[f] + '"##'
        code.append(
            'v.record_field("'
            + name
            + '",OptionField{doc:'
            + lit("doc")
            + ",default:"
            + lit("default")
            + ",value_type:"
            + lit("value_type")
            + ",example:"
            + lit("example")
            + ",scope:Some("
            + lit("scope")
            + "),deprecated:None});"
        )
    return "\n".join(code + ["}}}", ""])


def exercise(repo, work, rustup_home, proxies, recorder):
    gold = p.source_pair(repo)
    work.mkdir(mode=0o700)
    sdk = rustup_home / "toolchains/ohm"
    env = {
        "HOME": str(work),
        "CARGO_HOME": str(work / "cargo-home"),
        "CARGO_TARGET_DIR": str(work / "target"),
        "CARGO_BUILD_BUILD_DIR": str(work / "build"),
        "RUSTUP_HOME": str(rustup_home),
        "RUSTUP_AUTO_INSTALL": "0",
        "PATH": str(proxies) + ":/usr/local/bin:/usr/bin:/bin",
        "LD_LIBRARY_PATH": str(sdk / "lib"),
        "CARGO_NET_OFFLINE": "true",
        "LC_ALL": "C",
    }
    for tool, commit in [("cargo", w.c.SDK["cargo"]), ("rustc", w.c.SDK["rust"])]:
        p.need(
            commit in subprocess.check_output([tool, "+ohm", "-vV"], cwd=work, env=env, text=True),
            "wrong signed fixture actor",
        )
    put(
        work / "Cargo.toml",
        '[workspace]\nmembers=["ruff_options_metadata","ruff_workspace"]\nresolver="2"\n[profile.dev]\ndebug=1\nopt-level=1\n',
    )
    for name in ("ruff_options_metadata", p.OWNER):
        manifest = '[package]\nname="' + name + '"\nversion="0.1.0"\nedition="2024"\n'
        if name == p.OWNER:
            manifest += '[dependencies]\nruff_options_metadata={path="../ruff_options_metadata"}\n'
        put(work / name / "Cargo.toml", manifest)
    put(
        work / "ruff_options_metadata/src/lib.rs",
        p.git(repo, "show", p.OLD + ":crates/ruff_options_metadata/src/lib.rs"),
    )
    put(work / "option-client.rs", (HERE / "client.rs").read_bytes())
    put(work / "bad-option-client.rs", p.BAD_CLIENT)
    product = work / "ruff_workspace/src/lib.rs"
    put(product, fixture_source(repo, p.OLD))
    subprocess.run(["cargo", "+ohm", "generate-lockfile", "--offline"], cwd=work, env=env, check=True)
    store = work / "cgu-originals"
    store.mkdir()
    bodies = work / "client-bodies"
    bodies.mkdir()
    compiled = {}
    for phase, rev, method in (
        ("observe-old", p.OLD, "observe"),
        ("capture-old", p.OLD, "capture"),
        ("capture-new", p.NEW, "capture"),
        ("capture-unchanged", p.NEW, "capture"),
        ("capture-empty-new", p.NEW, "capture"),
    ):
        if phase in ("capture-old", "capture-empty-new"):
            for n in ("target", "build"):
                q = work / n
                p.need(q.is_dir() and q.resolve(strict=True) == q and q.parent == work, "fixture root")
                shutil.rmtree(q)
        if product.read_text() != fixture_source(repo, rev):
            put(product, fixture_source(repo, rev))
        where = work / phase
        where.mkdir()
        stage = where / "stage"
        stage.mkdir()
        out = w.command_output(
            [recorder, stage, sdk / "bin/rustc", method, *p.CMD], work, {**env, "OHM_CGU_REQUEST": p.FLAG}
        )
        for suffix, b in (("stdout", out.stdout), ("stderr", out.stderr)):
            (where / ("cargo." + suffix)).write_bytes(b)
        p.need(out.returncode == 0, (phase, out.stderr[-1024:]))
        rows = [json.loads(line) for line in out.stdout.splitlines()]
        products = p.results(rows, True)
        st = (sdk / "bin/rustc").stat()
        actual = reopen.roster(
            stage,
            method,
            str(sdk / "bin/rustc"),
            env,
            phase.rsplit("-", 1)[1],
            False,
            products,
            {"bin/rustc": [None, st.st_dev, st.st_ino]},
        )
        w.captured(where, rows, method, work, store, False)
        w.native.client(where, rows, products, work, work, env, gold[rev], bodies)
        cg = w.c.read(where / "cgus.json")[p.OWNER]
        compiled[phase] = {
            "cgus": len(cg["emitted"]),
            "rustc_events": [[name, target, query] for name, target, query, _ in actual],
            "new_compiler": cg["call"] is not None,
            "root": w.c.read(where / "root-archive.json"),
            "field": p.sha((where / "client/field.stdout").read_bytes()),
        }
    p.need(
        compiled["capture-old"]["cgus"]
        and compiled["capture-new"]["cgus"]
        and compiled["capture-empty-new"]["cgus"]
        and not compiled["capture-unchanged"]["new_compiler"]
        and not compiled["observe-old"]["cgus"],
        "real native/root fixture lost its intended polarity",
    )
    p.save(
        work / "qualified.json",
        {
            "source": "real two option literals + unmodified Ruff metadata API; two-crate root and physical observer fixture",
            "results": compiled,
        },
    )
    print(json.dumps(compiled, sort_keys=True))


if __name__ == "__main__":
    if len(sys.argv) != 6:
        raise SystemExit("RUFF NEW_PRIVATE_WORK RUSTUP_HOME PROXY_BIN RECORDER")
    exercise(*(Path(x).absolute() for x in sys.argv[1:]))
