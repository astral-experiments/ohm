"""Check the private-derive contract across same-path Cargo and rustc-driver changes."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time

ops = Path(__file__).resolve().parent


def save(path, value):
    path.write_text(json.dumps(value, indent=1, sort_keys=True) + "\n")


def sha(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def identity(path):
    st = path.stat()
    return [st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns]


def mem():
    return int(re.search(r"^MemAvailable:\s+(\d+)", Path("/proc/meminfo").read_text(), re.M)[1]) * 1024


def bounded(argv, cwd, env, result, root):
    start = time.monotonic()
    while mem() < 8 * 2**30 + 256 * 2**20:
        assert time.monotonic() - start < 900
        time.sleep(3)
    assert shutil.disk_usage(root).free > 15 * 2**30
    with (result / "stdout").open("wb") as out, (result / "stderr").open("wb") as err:
        p = subprocess.Popen(argv, cwd=cwd, env=env, start_new_session=True, stdout=out, stderr=err)
        while p.poll() is None:
            if mem() < 8 * 2**30 or shutil.disk_usage(root).free < 15 * 2**30 or time.monotonic() - start > 150:
                os.killpg(p.pid, signal.SIGKILL)
                p.wait()
                raise RuntimeError("physical resource or duration floor")
            time.sleep(0.03)
    assert p.returncode == 0, (result, p.returncode, (result / "stderr").read_text()[-1000:])


def main():
    ap = argparse.ArgumentParser()
    for name in ("registration", "parent-sdk", "candidate-sdk", "aware-cargo", "fixed-cargo", "work"):
        ap.add_argument("--" + name, type=Path, required=True)
    args = ap.parse_args()
    reg = json.loads(args.registration.read_bytes())
    assert reg["C"] in ('800fcd497d67c2e0926f26ecbfe12b8837013637', 'b6c3da0e9c7df8d7239cdf702600d334a8057c3a') and reg["option"] == ('-Zohm-checked-private-derives' if reg["C"] == '800fcd497d67c2e0926f26ecbfe12b8837013637' else '-Zohm-checked-private-derives-v2')
    base = args.work.resolve()
    base.mkdir(mode=0o700, exist_ok=False)
    proof = base / "proof"
    proof.mkdir()
    save(proof / "registration.json", reg)
    roots = {r: s.resolve(strict=True) for r, s in zip("PC", (args.parent_sdk, args.candidate_sdk))}
    sdk = base / "install"
    payload = base / "packs"
    payload.mkdir()
    driver_name, = [p.name for p in (roots["P"] / "lib").glob("librustc_driver-*.so")]
    driver = sdk / "lib" / driver_name
    front = sdk / "bin/rustc"
    for r, kit in roots.items():
        (payload / r).mkdir()
        for name, src in (("driver", kit / "lib" / driver_name), ("rustdoc", kit / "bin/rustdoc")):
            dest = payload / r / name
            shutil.copy2(src, dest)
            assert sha(dest) == sha(src)
        assert sha(payload / r / "driver") == reg["driver"][r]
        os.utime(payload / r / "driver", ns=(1_700_000_000_000_000_000,) * 2)
    assert sha(roots["P"] / "bin/rustc") == sha(roots["C"] / "bin/rustc")
    shutil.copy2(roots["P"] / "bin/rustc", payload / "common-frontend")
    cargos = {"signed": roots["P"] / "bin/cargo", "fixed": args.fixed_cargo, "aware": args.aware_cargo}
    for name, binary in cargos.items():
        assert sha(binary) == reg[{"signed": "cargo", "fixed": "fixed_cargo_sha256", "aware": "aware_cargo_sha256"}[name]]
        shutil.copy2(binary, payload / name)

    # Create every hardlink before enrollment, then change only the one visible directory.
    # Renaming a directory preserves the ctime of each regular file below it.
    views = {}
    for client, role in sorted({tuple(row) for row in reg["switch_order"]}):
        view = payload / (client + "-" + role)
        (view / "bin").mkdir(parents=True)
        (view / "lib").mkdir()
        for name, source in (("rustc", payload / "common-frontend"), ("rustdoc", payload / role / "rustdoc"), ("cargo", payload / client)):
            os.link(source, view / "bin" / name)
        os.link(payload / role / "driver", view / "lib" / driver_name)
        for file in (roots["P"] / "lib").iterdir():
            if file.name != driver_name:
                (view / "lib" / file.name).symlink_to(file)
        views[client, role] = view
    stable_front = identity(payload / "common-frontend")
    physical: dict = {
        "frontend": stable_front,
        "drivers": {r: identity(payload / r / "driver") for r in roots},
        "rustdocs": {r: identity(payload / r / "rustdoc") for r in roots},
        "clients": {c: identity(payload / c) for c in cargos},
    }
    save(proof / "installed-before-any-typed-command.json", physical)
    previous_view = None
    def bind(client, role):
        nonlocal previous_view
        if previous_view != (client, role):
            if previous_view is not None:
                sdk.rename(views[previous_view])
            views[client, role].rename(sdk)
            previous_view = (client, role)
        assert identity(front) == physical["frontend"]
        assert identity(driver) == physical["drivers"][role]
        assert identity(sdk / "bin/rustdoc") == physical["rustdocs"][role]
        assert identity(sdk / "bin/cargo") == physical["clients"][client]

    ru = base / "rustup"
    (ru / "toolchains").mkdir(parents=True)
    (ru / "toolchains/ohm").symlink_to(sdk)
    (ru / "settings.toml").write_text('version="12"\nprofile="minimal"\n')
    proxies = base / "proxies"
    proxies.mkdir()
    rustup = Path(shutil.which("rustup")).resolve(strict=True)
    for name in ("rustup", "rustc", "cargo", "rustdoc"):
        (proxies / name).symlink_to(rustup)
    env = {"HOME": str(base / "home"), "CARGO_HOME": str(base / "cargo-home"),
           "CARGO_TARGET_DIR": str(base / "target"), "CARGO_BUILD_BUILD_DIR": str(base / "shared"),
           "RUSTUP_HOME": str(ru), "RUSTUP_AUTO_INSTALL": "0", "CARGO_CACHE_AUTO_CLEAN_FREQUENCY": "never",
           "CARGO_TERM_COLOR": "never", "CARGO_NET_OFFLINE": "true", "PATH": str(proxies) + ":/usr/bin:/bin",
           "CARGO_BUILD_JOBS": "1", "LC_ALL": "C", "TMPDIR": str(base / "temp"),
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "RUSTC": str(front)}
    for key in ("home", "cargo-home", "target", "shared", "temp"):
        (base / key).mkdir()
    work = base / "source"
    for crate in ("dep", "app"):
        (work / crate / "src").mkdir(parents=True)
    (work / "Cargo.toml").write_text('[workspace]\nmembers=["dep","app"]\nresolver="3"\n')
    for crate in ("dep", "app"):
        toml = f'[package]\nname="{crate}"\nversion="0.0.0"\nedition="2024"\n'
        if crate == "app":
            toml += '[dependencies]\ndep={path="../dep"}\n'
        (work / crate / "Cargo.toml").write_text(toml)
    (work / "Cargo.lock").write_text('version=4\n[[package]]\nname="app"\nversion="0.0.0"\ndependencies=["dep"]\n[[package]]\nname="dep"\nversion="0.0.0"\n')
    fixture = ops / "fixture"
    files = json.loads((fixture / "source.json").read_bytes())["files"]
    assert all(sha(fixture / n) == key for n, key in files.items())
    (work / "dep/src/lib.rs").write_bytes((fixture / "dep-lib.rs").read_bytes())
    (work / "app/src/main.rs").write_bytes((fixture / "app-main.rs").read_bytes())
    hidden = work / "dep/src/hidden.rs"
    hidden.write_bytes((fixture / "dep-hidden-old.rs").read_bytes())
    decoder = json.JSONDecoder()
    cells = []

    def visit(role, client, active, parent, name, command, explicit_off=False, wrapper=None):
        result = parent / name
        result.mkdir()
        effective = env.copy()
        if wrapper is not None:
            effective["RUSTC_WORKSPACE_WRAPPER"] = str(wrapper)
        argv = ["cargo", "+ohm", *(["-Zohm-defaults=no"] if explicit_off else []), command, "-p", "app", "--locked", "--offline", "-j1", "--message-format=json"]
        save(result / "invocation.json", {"cargo": sha(sdk / "bin/cargo"), "driver": sha(driver), "frontend": identity(front),
                                          "argv": argv, "hidden": sha(hidden), "role": role, "client": client})
        assert identity(front) == stable_front and identity(driver)[3] == 1_700_000_000_000_000_000
        assert identity(driver) == physical["drivers"][role]
        assert identity(sdk / "bin/rustdoc") == physical["rustdocs"][role]
        assert identity(sdk / "bin/cargo") == physical["clients"][client]
        trace = ["/usr/bin/strace", "-ff", "-qq", "-yy", "-s", "260000", "-e", "trace=execve,mmap,clone,clone3,fork,vfork,unlink,unlinkat", "-o", str(result / "trace")]
        bounded(trace + argv, work, effective, result, base)
        raw = [json.loads(line) for line in (result / "stdout").read_text().splitlines()]
        assert raw[-1] == {"reason": "build-finished", "success": True}
        art, = [r for r in raw if r.get("reason") == "compiler-artifact" and r["target"]["name"] == "dep"]
        metas = [Path(n) for n in art["filenames"] if n.endswith(".rmeta")]
        if not metas:
            library, = [Path(n) for n in art["filenames"] if n.endswith(".rlib")]
            meta = library.with_suffix(".rmeta")
        else:
            meta, = metas
        assert meta.is_file()
        root = subprocess.check_output(["rustc", "+ohm", meta, "-Zls=root"], env=effective, text=True)
        (result / "metadata-header.txt").write_text(root)
        pub = re.search(r"^public_hash (\w{32})$", root, re.M)[1] if not explicit_off and wrapper is None else None
        snaps = proof / "objects"; snaps.mkdir(exist_ok=True)
        digest = sha(meta)
        if not (snaps / digest).exists():
            shutil.copyfile(meta, snaps / digest)
        assert sha(snaps / digest) == digest
        option = reg.get("secondary") if client == "fixed" else reg["option"] if client == "aware" else None
        true, probes, native = [], [], []
        hint_custody = []
        for path in result.glob("trace.*"):
            body = path.read_bytes()
            s = body.decode()
            found = re.findall(r'^unlink(?:at)?\(.*?"([^"]+/\.ohm-check-graphs/[0-9a-f]{16})".*?\) = 0$', s, re.M)
            if found:
                assert len(found) == 1 and Path(found[0]).parent == base / "target/.ohm-check-graphs", found
                events = []
                for entry in s.splitlines():
                    if found[0] in entry and entry.startswith(("unlink(", "unlinkat(")) and entry.endswith(" = 0"):
                        events.append("reject-ordinary-graph-hint")
                    match = re.match(r"^(?:clone|clone3|fork|vfork)\(.* = (\d+)$", entry)
                    if match:
                        events.append(int(match[1]))
                hint_custody.append({"path":found[0],"pid":int(path.suffix[1:]),"events":events})
            maps = [m for m in re.findall(r"^mmap\(.*PROT_EXEC.*<([^<>]+/librustc_driver-[^<>]+\.so)>.* = 0x[0-9a-f]+$", s, re.M) if Path(m).exists() and Path(m).samefile(driver)]
            for line in s.splitlines():
                if not line.startswith("execve(") or not line.endswith(" = 0"):
                    continue
                image, at = decoder.raw_decode(line[7:]); args, _ = decoder.raw_decode(line[7 + at:].lstrip(", "))
                file = Path(image)
                if image.endswith("/wild-ld/ld.bfd"):
                    image_digest = sha(file)
                    assert image_digest == reg["wild"]
                    native.append([image, image_digest])
                if not file.exists() or not file.samefile(front):
                    continue
                if len(args) == 3 and args[1] in ("-Zohm-checked-private-derives", "-Zohm-checked-private-derives-v2") and args[2] == "--print=sysroot":
                    assert args[1] == option
                    assert maps
                    probes.append(int(path.suffix[1:]))
                if "--crate-name" in args and "--out-dir" in args:
                    assert maps
                    crate = args[args.index("--crate-name") + 1]
                    assert crate in ("dep", "app")
                    flags = set(args) & {"-Zohm-checked-private-derives", "-Zohm-checked-private-derives-v2"}
                    assert flags == ({option} if active and crate == "dep" else set())
                    true.append({"crate": crate, "pid": int(path.suffix[1:]), "argv": args, "maps": maps})
            path.with_suffix(path.suffix + ".gz").write_bytes(gzip.compress(body, compresslevel=1, mtime=0))
            path.unlink()
        if option is None or explicit_off or wrapper is not None:
            assert not probes, (name, probes)
        elif len(probes) != 1:
            assert len(probes) == 2 and command == "check" and len(hint_custody) == 1, (name, probes, hint_custody)
            relevant = [event for event in hint_custody[0]["events"] if event in probes or event == "reject-ordinary-graph-hint"]
            assert sorted(e for e in relevant if isinstance(e, int)) == sorted(probes) and relevant[1] == "reject-ordinary-graph-hint", relevant
        elf = None
        if command == "build":
            exe, = [Path(r["executable"]) for r in raw if r.get("executable") and r.get("target", {}).get("name") == "app"]
            assert subprocess.run([exe], env=effective, check=True, capture_output=True).stdout == b""
            elf = sha(exe)
            if not (snaps / elf).exists():
                shutil.copyfile(exe, snaps / elf)
            assert (snaps / elf).read_bytes()[:4] == b"\x7fELF" and sha(snaps / elf) == elf
        caches = {str(p.relative_to(base)): [identity(p), sha(p)] for key in ("target", "shared") for p in (base / key).rglob(".rustc_info.json")}
        info = {"argv": argv, "true": true, "probes": probes, "native": native, "elf": elf, "meta": str(meta),
                "metadata_sha256": digest, "public": pub, "rustc_info": caches, "driver": list(identity(driver)),
                "hint_custody": hint_custody, "nominal": sorted(r["target"]["name"] for r in raw if r.get("reason") == "compiler-artifact" and not r["fresh"])}
        save(result / "observed.json", info)
        return info

    for index, (client, role) in enumerate(reg["switch_order"]):
        label = f"{index:02d}-{client}-{role}"
        d = proof / label; d.mkdir()
        bind(client, role)
        assert sha(driver) == reg["driver"][role]
        active = (role == "C" and client == "aware") or (role == "P" and client == "fixed" and "secondary" in reg)
        tested = {}
        for label, source in (("old", None), ("edit", "dep-hidden-edited.rs"), ("unchanged", None), ("repair", "dep-hidden-old.rs")):
            if source:
                time.sleep(1.04)
                hidden.write_bytes((fixture / source).read_bytes())
            data = visit(role, client, active, d, label, "check")
            roster = sorted(x["crate"] for x in data["true"])
            if label in ("edit", "repair"):
                assert roster == (["dep"] if active else ["app", "dep"]), (label, client, role, roster)
            if label == "unchanged":
                assert not roster
            tested[label] = data
        assert (tested["old"]["public"] == tested["edit"]["public"]) == active
        assert tested["old"]["metadata_sha256"] == tested["repair"]["metadata_sha256"] != tested["edit"]["metadata_sha256"]
        assert len({data["meta"] for data in tested.values()}) == 1
        cells.append({"role": role, "client": client, "provider": tested["old"]["meta"], "old": tested["old"]["metadata_sha256"],
                      "edited": tested["edit"]["metadata_sha256"], "active": active})
    variants = {(c["role"], c["client"]): c for c in cells}
    for c in cells:
        assert c == variants[c["role"], c["client"]]
    assert variants["P", "aware"]["provider"] != variants["C", "aware"]["provider"]
    assert variants["C", "fixed"]["provider"] != variants["C", "aware"]["provider"]
    if "secondary" in reg:
        assert variants["P", "fixed"]["active"] and variants["P", "fixed"]["provider"] != variants["C", "aware"]["provider"]
    current = cells[-1]
    assert current["role"] == "C" and current["client"] == "aware"
    extra = proof / "check-build"; extra.mkdir()
    built = visit("C", "aware", True, extra, "build", "build")
    assert any(x["crate"] == "app" for x in built["true"]) and built["native"]
    parked = base / "preclean"; parked.mkdir()
    for key in ("target", "shared", "cargo-home"):
        (base / key).rename(parked / key); (base / key).mkdir()
    clean = visit("C", "aware", True, extra, "empty-build", "build")
    assert clean["elf"] == built["elf"] and clean["metadata_sha256"] == built["metadata_sha256"] and clean["native"]
    off = visit("C", "aware", False, extra, "explicit-defaults-off", "check", explicit_off=True)
    assert off["true"] and not off["probes"]
    wrapper = base / "workspace-wrapper"
    wrapper.write_text('#!/bin/sh\nexec "$@"\n')
    wrapper.chmod(0o755)
    wrapped = visit("C", "aware", False, extra, "workspace-wrapper", "check", wrapper=wrapper)
    assert wrapped["true"] and not wrapped["probes"]
    out = {"cells": cells, "frontend": stable_front, "driver_mtime_ns": 1_700_000_000_000_000_000,
           "native": clean["elf"], "native_rmeta": clean["metadata_sha256"], "registration": sha(args.registration)}
    save(proof / "complete.json", out)
    print(sha(proof / "complete.json"))


if __name__ == "__main__":
    main()
