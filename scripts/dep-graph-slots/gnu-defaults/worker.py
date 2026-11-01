"""Exercise the integrated SDK's default declared linker with three actual GNU input changes."""

import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]
from events import reopen
from qualify import BIND, CHILD, checksum, guard, need, save, verify_live
from release_smoke import WILD, identities, toolchain

WILD_PATH = Path("lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd")
NAMES = ("script", "library", "startup")
PORTABLE = "18bd183bc7e303c41bfceed5fbff642b8927c3b6c2292eeba5878786773fc19c"


def packed(path, data):
    path.write_bytes(gzip.compress(data, compresslevel=5, mtime=0))


def identity(path):
    state = path.stat()
    return state.st_dev, state.st_ino, checksum(path)


def install_file(source, target):
    # Both references must be regular native files under the new SDK's own spelling.
    need(target.is_symlink(), "unexpected SDK projection: " + str(target))
    target.unlink()
    if source.stat().st_mode & 0o022:
        shutil.copyfile(source, target)
        target.chmod(0o555)
    else:
        try:
            os.link(source.resolve(strict=True), target)
        except OSError:
            shutil.copy2(source, target)
    need(
        target.is_file() and not target.is_symlink() and checksum(source) == checksum(target),
        "projected executable differs",
    )


def compile_object(native, name, text):
    out = native / (name + ".o")
    subprocess.run(["/usr/bin/cc", "-fPIC", "-x", "c", "-c", "-o", out, "-"], check=True, input=text.encode())
    return out


def archive(native, name, member):
    path = native / ("lib" + name + ".a")
    subprocess.run(["/usr/bin/ar", "rcs", path, member], check=True)
    return path


def prepare_case(mode, root, prefix, receipt):
    src = root / "project"
    native = src / "native"
    (src / "src").mkdir(parents=True)
    (src / "engine/src").mkdir(parents=True)
    native.mkdir()
    (src / "Cargo.toml").write_text(
        '[package]\nname="reader"\nversion="0.0.0"\nedition="2021"\n[dependencies]\nengine={path="engine"}\n'
    )
    (src / "engine/Cargo.toml").write_text('[package]\nname="engine"\nversion="0.0.0"\nedition="2021"\n')
    (src / "engine/src/lib.rs").write_text(
        'pub fn register(v:i32)->i32 { unsafe { core::arch::asm!("/* {0:e} */", in(reg) v, options(nostack, nomem, preserves_flags)); } v }\n'
    )
    main = src / "src/main.rs"
    main.write_text(
        'extern "C" { fn answer()->i32; } fn main() { println!("{}",engine::register(unsafe { answer() })); }\n'
    )
    watched = ["libanswer.a"]
    alternate = archive(
        native, "ohm_alternate", compile_object(native, "new", "int ohm_provider(void){return 29;}")
    )
    if mode == "script":
        answer = "extern int ohm_provider(void); int answer(void){return ohm_provider();}"
        archive(native, "ohm_private", compile_object(native, "old", "int ohm_provider(void){return 17;}"))
        system = Path(
            subprocess.check_output(["/usr/bin/cc", "-print-file-name=libgcc_s.so.1"], text=True).strip()
        ).resolve(strict=True)
        (native / "libgcc_s.so").write_text(f"GROUP ( {system} -lohm_private )\n")
        watched += ["libohm_private.a", "libohm_alternate.a", "libgcc_s.so"]
        provider = native / "libohm_private.so"
        good = f"INPUT ( {alternate} )".encode().ljust(512) + b"\n"
    else:
        answer = "extern int ohm_prefix_choice(void) __attribute__((weak)); int answer(void){return ohm_prefix_choice?ohm_prefix_choice():17;}"
        if mode == "library":
            obj = compile_object(native, "prefix", "int ohm_prefix_choice(void){return 29;}")
            provider = prefix / "libutil.so"
            good = f"INPUT ( {obj} )".encode().ljust(512) + b"\n"
        else:
            provider = prefix / "crti.o"
            stock = Path(
                subprocess.check_output(["/usr/bin/cc", "-print-file-name=crti.o"], text=True).strip()
            ).resolve(strict=True)
            sentinel = compile_object(
                native,
                "sentinel",
                "static volatile int x; __attribute__((constructor)) static void init(void){x=29;} int ohm_prefix_choice(void){return x;}",
            )
            obj = native / "replacement.o"
            subprocess.run(["/usr/bin/ld.bfd", "-r", stock, sentinel, "-o", obj], check=True)
            for name, path in [("stock", stock), ("sentinel", sentinel), ("replacement", obj)]:
                packed(receipt / (name + ".o.gz"), path.read_bytes())
            sections = subprocess.check_output(["/usr/bin/readelf", "-hSWs", obj])
            need(b".init_array" in sections and b"ohm_prefix_choice" in sections, "startup control missing")
            (receipt / "startup.readelf").write_bytes(sections)
            good = obj.read_bytes()
    archive(native, "answer", compile_object(native, "answer", answer))
    script = 'fn main(){ let path=std::env::var("CARGO_MANIFEST_DIR").unwrap();\n'
    for name in watched:
        script += 'println!("cargo::rerun-if-changed={path}/native/' + name + '");\n'
    script += 'println!("cargo::rustc-link-search=native={path}/native"); println!("cargo::rustc-link-lib=static=answer"); }\n'
    (src / "build.rs").write_text(script)
    need(not os.path.lexists(provider), "preexisting provider " + str(provider))
    save(
        receipt / "initial-inputs.json",
        {str(f.relative_to(src)): checksum(f) for f in sorted(src.rglob("*")) if f.is_file()},
    )
    for p in [main, src / "build.rs", src / "engine/src/lib.rs"]:
        (receipt / (str(p.relative_to(src)).replace("/", "_"))).write_bytes(p.read_bytes())
    return src, provider, good


def set_provider(provider, data):
    if data is None:
        provider.unlink(missing_ok=True)
        return None
    old = provider.stat() if provider.exists() else None
    if old is None or provider.read_bytes() != data:
        provider.write_bytes(data)
    if old is not None and (old.st_mtime_ns != provider.stat().st_mtime_ns):
        os.utime(provider, ns=(old.st_atime_ns, old.st_mtime_ns))
        now = provider.stat()
        need(
            (now.st_dev, now.st_ino, now.st_size, now.st_mtime_ns)
            == (old.st_dev, old.st_ino, old.st_size, old.st_mtime_ns),
            "same-stat control changed identity",
        )
    st = provider.stat()
    return [st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, checksum(provider)]


def retained(roots):
    manifests = {}
    seals = {}
    aliases = []
    for directory in roots:
        for p in directory.glob("**/declared-native/inputs.json"):
            manifests[str(p)] = json.loads(p.read_bytes())
        for p in directory.glob("**/declared-native/seal"):
            seals[str(p)] = checksum(p)
        aliases.extend(directory.glob("**/ohm-declared-cc"))
    return manifests, seals, aliases


def visit(name, root, out, src, env, proxy, sdk, observer, provider, installed):
    phase = out / name
    phase.mkdir()
    cli = [str(proxy / "cargo"), "+ohm", "build", "--offline", "--message-format=json"]
    log = root / "active-kernel.tsv"
    need(not log.exists(), "unexpected preceding active ledger")
    res = subprocess.run([observer, log, "--", *cli], cwd=src, env=env, capture_output=True)
    raw = log.read_bytes() if log.is_file() else b""
    for key, body in [("kernel.tsv", raw), ("stdout", res.stdout), ("stderr", res.stderr)]:
        packed(phase / (key + ".gz"), body)
    save(
        phase / "invocation.json",
        {"argv": cli, "rc": res.returncode, "env": env, "cwd": str(src), "provider": installed},
    )
    if log.exists():
        log.unlink()
    ex = reopen(raw, res.returncode)
    events = ex["execs"]

    def actors(path):
        wanted = identity(path)
        return [e for e in events if tuple(e["image"][k] for k in ("dev", "ino", "sha256")) == wanted]

    cargo = actors(sdk / "bin/cargo")
    need(sum(e["argv"][1:] == cli[2:] for e in cargo) == 1, "actual Cargo not enrolled")
    relays = [e["ordinal"] for e in cargo if Path(e["argv"][0]).name == "ohm-declared-cc"]
    wild = sdk / WILD_PATH
    wilds = actors(wild)
    writes = []
    for e in wilds:
        a = e["argv"]
        if "-o" in a:
            writes.append(
                {
                    "ordinal": e["ordinal"],
                    "output": Path(a[a.index("-o") + 1]).name,
                    "startup": [p for p in a if Path(p).name == "crti.o"],
                }
            )
        else:
            need(a[1:] in (["-v"], ["--version"]), "unclassified Wild invocation")
    syscc = actors(Path("/usr/bin/cc"))
    asks = []
    for e in events:
        a = e["argv"]
        if any(v == "-print-search-dirs" or v.startswith("-print-file-name=") for v in a):
            need(
                e in syscc and a[1:-1] == ["-m64", "-B" + str(wild.parent)],
                "foreign driver resolution command",
            )
            asks.append([e["ordinal"], a[-1]])
    manifests, seals, aliases = retained((Path(env["CARGO_TARGET_DIR"]), Path(env["CARGO_BUILD_BUILD_DIR"])))
    need(all(p.is_symlink() and p.samefile(sdk / "bin/cargo") for p in aliases), "wrong declared relay")
    messages = [json.loads(line) for line in res.stdout.splitlines()]
    need(
        messages[-1] == {"reason": "build-finished", "success": res.returncode == 0},
        "missing Cargo JSON verdict",
    )
    tag = digest = None
    if res.returncode == 0:
        binary = Path(env["CARGO_TARGET_DIR"]) / "debug/reader"
        native = subprocess.run([binary], check=True, capture_output=True)
        tag = int(native.stdout)
        digest = checksum(binary)
        (phase / "program.stdout").write_bytes(native.stdout)
        body = out / "bodies" / (digest + ".gz")
        if not body.exists():
            packed(body, binary.read_bytes())
    else:
        errors = [
            m["message"]["rendered"]
            for m in messages
            if m["reason"] == "compiler-message" and m["message"]["level"] == "error"
        ]
        need(
            res.returncode == 101
            and len(errors) == 1
            and "wild: error: Failed to process" in errors[0]
            and provider.name in errors[0]
            and "/missing-real-ohm-transitive-provider" in errors[0],
            "unrelated malformed-input failure",
        )
    row = dict(
        code=res.returncode,
        tag=tag,
        elf=digest,
        manifests=manifests,
        seals=seals,
        relay=relays,
        writes=writes,
        driver_queries=asks,
        actors=len(events),
        family=ex["terminal_groups"],
        raw_sha256=hashlib.sha256(raw).hexdigest(),
        provider=installed,
    )
    save(phase / "row.json", row)
    return row


def validate(mode, rows, wild_prefix):
    expected = {
        "cold": 17,
        "unchanged": 17,
        "new": 29,
        "new-repeat": 29,
        "bad": None,
        "repair": 29,
        "removed": 17,
        "empty-new": 29,
        "empty-bad": None,
        "empty-old": 17,
        "forced-bad": None,
        "forced-repair": 18,
        "forced-repeat": 18,
        "return": 17,
        "return-repeat": 17,
    }
    need(set(rows) == set(expected), "missing or duplicate ordinary phase")
    for n, tag in expected.items():
        r = rows[n]
        for k in r["seals"]:
            slot = Path(k)
            need(
                slot.parts[-3:] == ("reader.rlink-objects", "declared-native", "seal")
                and str(slot.with_name("inputs.json")) in r["manifests"],
                "a seal is not paired with the final reader manifest",
            )
        need(
            r["tag"] == tag and r["code"] == (101 if tag is None else 0),
            "wrong program or compiler result at " + n,
        )
    for n, reference in [
        ("new", "empty-new"),
        ("new-repeat", "empty-new"),
        ("repair", "empty-new"),
        ("removed", "empty-old"),
        ("unchanged", "empty-old"),
        ("cold", "empty-old"),
        ("forced-repeat", "forced-repair"),
        ("return", "empty-old"),
        ("return-repeat", "empty-old"),
    ]:
        need(rows[n]["elf"] == rows[reference]["elf"], "whole executable differs at " + n)
    need(rows["new"]["elf"] != rows["cold"]["elf"], "invalid new-program discriminator")
    ids = [rows[n]["provider"] for n in ["new", "bad", "repair"]]
    need(
        ids[0][:4] == ids[1][:4] == ids[2][:4] and ids[0][4] == ids[2][4] != ids[1][4],
        "provider was not changed in place",
    )

    def wild(n):
        return [v["output"] for v in rows[n]["writes"]]

    for n in ["new", "bad", "repair", "removed", "forced-bad", "forced-repair", "return"]:
        need(
            wild(n) == ["reader"] and len(rows[n]["relay"]) == 1, "expected genuine final target link in " + n
        )
    empty_failure = ["build_script_build", "reader"] if mode == "script" else ["build_script_build"]
    need(
        wild("empty-new") == ["build_script_build", "reader"] and wild("empty-bad") == empty_failure,
        "wrong independent native links",
    )
    if mode == "script":
        for n in [
            "cold",
            "unchanged",
            "new",
            "new-repeat",
            "bad",
            "repair",
            "removed",
            "forced-repeat",
            "return-repeat",
        ]:
            need(
                not rows[n]["seals"] and "reader" in wild(n),
                "open library search was blindly retained at " + n,
            )
    else:
        for n in ["unchanged", "forced-repeat", "return-repeat"]:
            r = rows[n]
            need(
                len(r["relay"]) == len(r["manifests"]) == len(r["seals"]) == 1 and not wild(n),
                "missing authenticated zero-link positive at " + n,
            )
            need(
                {v for _, v in r["driver_queries"]} >= {"-print-search-dirs", "-print-file-name=crti.o"},
                "missing effective driver queries",
            )
        if mode == "startup":
            need(
                not wild("new-repeat") and len(rows["new-repeat"]["seals"]) == 1,
                "valid startup object was not retained",
            )
            for n in ["new", "bad", "repair", "forced-bad", "empty-bad", "empty-new"]:
                need(
                    all(w["startup"] == [str(wild_prefix / "crti.o")] for w in rows[n]["writes"]),
                    "actual linker used a different startup object",
                )
    return {
        n: {k: r[k] for k in ["code", "tag", "elf", "relay", "writes", "driver_queries"]}
        | {"manifests": len(r["manifests"]), "seals": len(r["seals"])}
        for n, r in rows.items()
    }


def run_case(mode, root, out, sdk, prefix, proxy, observer):
    root.mkdir()
    out.mkdir()
    (out / "bodies").mkdir()
    src, provider, good = prepare_case(mode, root, prefix, out)
    disk_roots = [root / "target", root / "build"]
    for n in ["home", "registry", "tmp"]:
        (root / n).mkdir()
    env = {
        "PATH": str(proxy) + ":/usr/bin:/bin",
        "HOME": str(root / "home"),
        "RUSTUP_HOME": str(sdk.parents[1]),
        "CARGO_HOME": str(root / "registry"),
        "CARGO_TARGET_DIR": str(disk_roots[0]),
        "CARGO_BUILD_BUILD_DIR": str(disk_roots[1]),
        "CARGO_NET_OFFLINE": "true",
        "CARGO_INCREMENTAL": "1",
        "CARGO_TERM_COLOR": "never",
        "TMPDIR": str(root / "tmp"),
        "LC_ALL": "C",
    }
    need(sdk.parent.name == "toolchains" and sdk.name == "ohm", "different canonical rustup toolchain")
    printed = subprocess.check_output(
        [proxy / "rustc", "+ohm", "--print", "sysroot"], env=env, text=True
    ).strip()
    need(Path(printed).samefile(sdk), "driver selected another SDK")
    save(out / "environment.json", env)
    bad = b"INPUT ( /missing-real-ohm-transitive-provider )\n".ljust(len(good), b" ")
    rows = {}
    main = src / "src/main.rs"
    original = main.read_text()

    def capture(name, data, empty=False):
        installed = set_provider(provider, data)
        if empty:
            for p in disk_roots:
                need(p.parent == root and p.is_dir() and not p.is_symlink(), "wrong private target")
                shutil.rmtree(p)
        rows[name] = visit(name, root, out, src, env, proxy, sdk, observer, provider, installed)
        print(mode, name, rows[name]["code"], rows[name]["tag"], len(rows[name]["writes"]), flush=True)

    try:
        for name, body in [
            ("cold", None),
            ("unchanged", None),
            ("new", good),
            ("new-repeat", good),
            ("bad", bad),
            ("repair", good),
            ("removed", None),
        ]:
            capture(name, body)
        for name, body in [("empty-new", good), ("empty-bad", bad), ("empty-old", None)]:
            capture(name, body, True)
        needle = "engine::register(unsafe { answer() })"
        need(original.count(needle) == 1, "wrong native target edit")
        main.write_text(original.replace(needle, "(" + needle + ") + 1"))
        capture("forced-bad", bad)
        capture("forced-repair", None)
        capture("forced-repeat", None)
        main.write_text(original)
        capture("return", None)
        capture("return-repeat", None)
    finally:
        provider.unlink(missing_ok=True)
    return validate(mode, rows, (sdk / WILD_PATH).parent)


def execute(work, out, sdk, prefix, proxy, observer):
    need(
        checksum(HERE / "reproduce.sh") == PORTABLE and checksum(sdk / WILD_PATH) == WILD,
        "foreign script or Wild",
    )
    for name in NAMES:
        result = run_case(name, work / name, out / name, sdk, prefix, proxy, observer)
        save(out / name / "verified.json", result)
    env = {
        "PATH": str(proxy) + ":/usr/bin:/bin",
        "HOME": str(work),
        "RUSTUP_HOME": str(sdk.parents[1]),
        "TMPDIR": str(work),
        "LC_ALL": "C",
    }
    with (out / "standalone.log").open("xb") as stream:
        subprocess.run(
            ["/bin/bash", HERE / "reproduce.sh", "fixed", "ohm"],
            env=env,
            stdout=stream,
            stderr=subprocess.STDOUT,
            check=True,
        )
    need(
        (out / "standalone.log").read_text().splitlines()[-1] == "outcome fixed",
        "portable standalone check failed",
    )


def main():
    _, repo, reports, tmp, host = guard()
    verify_live(repo)
    need(host == "x86_64-unknown-linux-gnu" and os.geteuid() != 0, "GNU user required")
    os.umask(0o022)
    previous = json.loads((reports / "slot-link-smoke/complete.json").read_bytes())
    need(previous["qualified"] and previous["host"] == host, "missing historical native compatibility gate")
    source = repo / "build" / host / "stage1"
    old = tmp / "packaged-linux-50/sdk-22"
    cargo = tmp / "release-link-smoke/cargo-build/debug/cargo"
    proxy = tmp / "release-link-smoke/proxies"
    out = reports / "slot-default-gnu"
    out.mkdir()
    with tempfile.TemporaryDirectory(prefix="ohm-gnu-defaults-", dir="/tmp") as td:
        work = Path(td)
        need(shutil.disk_usage(work).free > 4 << 30, "less than 4 GiB available")
        sdk = work / "rustup/toolchains/ohm"
        toolchain(sdk, source, cargo, host, old / WILD_PATH)
        install_file(cargo, sdk / "bin/cargo")
        install_file(old / WILD_PATH, sdk / WILD_PATH)
        (work / "rustup/settings.toml").write_text('version = "12"\nprofile = "minimal"\n')
        env = {
            "PATH": str(proxy) + ":/usr/bin:/bin",
            "RUSTUP_HOME": str(work / "rustup"),
            "HOME": str(work),
            "LC_ALL": "C",
        }
        versions = identities(sdk, source, cargo, CHILD, BIND["trees"]["src/tools/cargo"], host, env)
        for tool in ["driver", "rustc", "cargo"]:
            need(
                versions[tool]["sha256"] == previous["results"]["rebased"]["versions"][tool]["sha256"],
                "unmatched physical " + tool,
            )
        save(
            out / "identity.json",
            {
                "host": host,
                "rust": CHILD,
                "cargo": BIND["trees"]["src/tools/cargo"],
                "versions": versions,
                "wild": identity(sdk / WILD_PATH),
                "cargo_physical": identity(sdk / "bin/cargo"),
                "cc_physical": identity(Path("/usr/bin/cc")),
                "sdk": str(sdk),
                "proxy": str(proxy),
                "uid": os.geteuid(),
            },
        )
        observer = work / "exec-events"
        subprocess.run(
            [
                "/usr/bin/cc",
                "-O2",
                "-Wall",
                "-Wextra",
                "-Werror",
                HERE / "exec_events.c",
                "-lcrypto",
                "-o",
                observer,
            ],
            check=True,
        )
        save(
            out / "observer.json",
            {
                str(p.name): checksum(p)
                for p in [observer, HERE / "exec_events.c", HERE / "events.py", HERE / "reproduce.sh"]
            },
        )
        execute(work, out, sdk, (sdk / WILD_PATH).parent, proxy, observer)
    save(
        out / "complete.json",
        {
            "qualified": True,
            "cases": {n: checksum(out / n / "verified.json") for n in NAMES},
            "portable": checksum(out / "standalone.log"),
            "identity": checksum(out / "identity.json"),
        },
    )


if __name__ == "__main__":
    main()
