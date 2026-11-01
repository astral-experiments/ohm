"""Check explicit source names and physical worktree destinations on each native host."""

import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qualify import BIND, CHILD, PARENT, checksum, guard, need, save, verify_live

EXPLICIT = "/ohm-requested-sources"
INTERNAL = "/ohm-workspace/v7"
GOOD = "file!()\n"
BAD = '{ compile_error!(concat!("requested source ", file!())); "unreachable" }\n'
MAIN = 'fn main() { let path = include!(concat!(env!("CARGO_MANIFEST_DIR"), "/src/location.rs")); println!("{path}|29"); }\n'


def run(out, name, args, cwd, env):
    phase = out / name
    phase.mkdir()
    save(phase / "invocation.json", {"argv": list(map(str, args)), "cwd": str(cwd), "env": env})
    p = subprocess.run(args, cwd=cwd, env=env, capture_output=True, timeout=90)
    for key, data in [("stdout", p.stdout), ("stderr", p.stderr)]:
        (phase / (key + ".gz")).write_bytes(gzip.compress(data, mtime=0))
    save(phase / "exit.json", p.returncode)
    return p


def add(root, out, env, cargo, invalid, fixed):
    name = "alias" if invalid else "valid"
    donor = root / name / "donor"
    (donor / "src").mkdir(parents=True)
    (donor / "Cargo.toml").write_text(
        '[package]\nname="path_witness"\nversion="0.1.0"\nedition="2021"\n'
    )
    (donor / "src/main.rs").write_text(MAIN)
    (donor / "src/location.rs").write_text(GOOD)

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=donor, env=env)

    def entries():
        return sorted(
            os.fsdecode(s[9:])
            for s in git("worktree", "list", "--porcelain", "-z").split(b"\0")
            if s.startswith(b"worktree ")
        )

    git("init", "-q", "--template=", "-b", "seed-fixture")
    git("add", "Cargo.toml", "src/main.rs", "src/location.rs")
    git("-c", "user.name=Ohm QA", "-c", "user.email=qa@example.invalid", "commit", "-qm", "seed inputs")
    need(
        Path(os.fsdecode(git("rev-parse", "--path-format=absolute", "--git-common-dir")).strip())
        == donor / ".git",
        "foreign Git root",
    )
    alias = donor.parent / "alias"
    alias.symlink_to(donor, target_is_directory=True)
    need(alias.resolve(strict=True) == donor and not (donor / "missing").exists(), "wrong link topology")
    before = entries()
    need(before == [str(donor)], "existing registration")
    dest = "../alias/missing/../nested" if invalid else "../sibling"
    phase = "register-" + name
    p = run(
        out,
        phase,
        [
            cargo,
            "+ohm",
            "worktree",
            "add",
            "--detach",
            "--target-dir",
            donor.parent / "new-target",
            dest,
            "HEAD",
        ],
        donor,
        env,
    )
    after = entries()
    nested = (donor / "nested/.git").is_file()
    sibling = donor.parent / "sibling"
    row = dict(argument=dest, before=before, after=after, nested=nested, status=p.returncode)
    save(out / phase / "ledger.json", row)
    if invalid:
        clean = (
            p.returncode == 101
            and before == after
            and not nested
            and b"new worktree must be outside the source worktree" in p.stderr
        )
        new_entries = set(after) - set(before)
        historical = (
            p.returncode in (0, 101)
            and nested
            and len(new_entries) == 1
            and len(after) == 2
            and Path(next(iter(new_entries))).samefile(donor / "nested")
        )
        need(clean or (not fixed and historical), "invalid registration or unrelated refusal")
    else:
        need(
            p.returncode == 0
            and not nested
            and after == sorted(before + [str(sibling)])
            and (sibling / ".git").is_file(),
            "valid sibling registration failed",
        )
        need((sibling / "src/location.rs").read_text() == GOOD, "incorrect sibling")
    return row, sibling


def build_case(root, out, env, cargo, src, spelling, fixed):
    case = out / spelling
    case.mkdir()
    work = root / spelling
    work.mkdir()
    env = dict(env, CARGO_TARGET_DIR=str(work / "target"), CARGO_BUILD_BUILD_DIR=str(work / "shared"))
    if spelling != "default":
        flag = "--remap-path-prefix=" if spelling == "attached" else "--remap-path-prefix\x1f"
        env["CARGO_ENCODED_RUSTFLAGS"] = flag + str(src) + "=" + EXPLICIT
    loc = src / "src/location.rs"
    states = {}
    try:
        for name, source in [("build", GOOD), ("repeat", GOOD), ("invalid", BAD), ("repair", GOOD)]:
            if source != loc.read_text():
                loc.write_text(source)
            p = run(case, name, [cargo, "+ohm", "build", "--offline", "--message-format=json"], src, env)
            js = [json.loads(line) for line in p.stdout.splitlines()]
            ok = name != "invalid"
            need(
                js[-1] == {"reason": "build-finished", "success": ok}
                and p.returncode == (0 if ok else 101),
                "unexpected Cargo verdict " + name,
            )
            item = {"status": p.returncode, "source": checksum(loc)}
            if ok:
                (unit,) = [
                    v
                    for v in js
                    if v["reason"] == "compiler-artifact" and v["target"]["name"] == "path_witness"
                ]
                binary = Path(unit["executable"])
                need(
                    binary == work / "target/debug/path_witness" and unit["fresh"] == (name == "repeat"),
                    "wrong compiler-artifact",
                )
                body = run(case, name + "-native", [binary], root, env)
                suffix = "/src/location.rs|29\n"
                need(
                    body.returncode == 0 and not body.stderr and body.stdout.decode().endswith(suffix),
                    "wrong native file! result",
                )
                prefix = body.stdout.decode().removesuffix(suffix)
                digest = checksum(binary)
                need(0 < binary.stat().st_size < 16 << 20, "oversized native output")
                target = out / "bodies" / (digest + ".gz")
                if not target.exists():
                    target.write_bytes(gzip.compress(binary.read_bytes(), mtime=0))
                item.update(prefix=prefix, elf=digest, bytes=binary.stat().st_size, fresh=unit["fresh"])
            else:
                (msg,) = [
                    v["message"]
                    for v in js
                    if v["reason"] == "compiler-message" and v["message"]["level"] == "error"
                ]
                text = msg["message"]
                need(
                    text.startswith("requested source ") and text.endswith("/src/location.rs"),
                    "unrelated source rejection",
                )
                prefix = text.removeprefix("requested source ").removesuffix("/src/location.rs")
                spans = [v["file_name"] for v in msg["spans"] if v["is_primary"]]
                need(
                    spans == [prefix + "/src/location.rs"], "diagnostic source span differs from file!()"
                )
                item.update(prefix=prefix, message=text, primary_span_files=spans)
            expected = INTERNAL if spelling == "default" else EXPLICIT
            need(
                prefix == expected or (not fixed and spelling != "default" and prefix == INTERNAL),
                "incorrect source prefix in " + name,
            )
            states[name] = item
            save(case / name / "verdict.json", item)
    finally:
        loc.write_text(GOOD)
    need(
        len({v["prefix"] for v in states.values()}) == 1
        and states["build"]["elf"] == states["repeat"]["elf"]
        and (sys.platform == "darwin" or states["repair"]["elf"] == states["build"]["elf"]),
        "repeat or repaired source and executable disagree",
    )
    states["repair"]["same_image_as_build"] = states["repair"]["elf"] == states["build"]["elf"]
    save(case / "repair/verdict.json", states["repair"])
    return states


def role(root, out, sdk, proxy, expected, fixed, darwin):
    root.mkdir()
    out.mkdir()
    (out / "bodies").mkdir()
    home = root / "user"
    (home / "rustup/toolchains").mkdir(parents=True)
    (home / "rustup/toolchains/ohm").symlink_to(sdk.resolve(strict=True), target_is_directory=True)
    (home / "rustup/settings.toml").write_text('version = "12"\nprofile = "minimal"\n')
    (home / "registry").mkdir()
    env = {
        "PATH": str(proxy) + os.pathsep + os.environ["PATH"],
        "HOME": str(home),
        "RUSTUP_HOME": str(home / "rustup"),
        "CARGO_HOME": str(home / "registry"),
        "CARGO_NET_OFFLINE": "true",
        "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "CARGO_TARGET_DIR": str(root / "donor-target"),
        "CARGO_BUILD_BUILD_DIR": str(root / "shared"),
    }
    if darwin:
        env["LLVM_PROFILE_FILE"] = str(root / "worktree-%m.profraw")
        if os.environ.get("SDKROOT"):
            env["SDKROOT"] = os.environ["SDKROOT"]
    versions = {}
    for name in ("rustc", "cargo"):
        selected = Path(
            subprocess.check_output(
                ["rustup", "which", "--toolchain", "ohm", name], env=env, text=True
            ).strip()
        )
        live = run(out, name + "-version", [proxy / name, "+ohm", "-vV"], root, env)
        need(
            live.returncode == 0
            and checksum(selected) == expected[name]["sha256"]
            and live.stdout.decode().strip() == expected[name]["version"],
            "wrong physical " + name,
        )
        versions[name] = {
            "sha256": checksum(selected),
            "version": live.stdout.decode().strip(),
            "path": str(selected),
        }
    (driver,) = (sdk / "lib").glob("librustc_driver-*")
    need(checksum(driver) == expected["driver"]["sha256"], "wrong native driver")
    alias, _ = add(root, out, env, proxy / "cargo", True, fixed)
    sibling, src = add(root, out, env, proxy / "cargo", False, fixed)
    cases = {
        name: build_case(root, out, env, proxy / "cargo", src, name, fixed)
        for name in ("attached", "split", "default")
    }
    result = {
        "versions": versions,
        "driver": checksum(driver),
        "alias": alias,
        "sibling": sibling,
        "source": str(src),
        "cases": cases,
    }
    save(out / "complete.json", result)
    return result


def main():
    _, repo, reports, tmp, host = guard()
    verify_live(repo)
    link = tmp / "release-link-smoke"
    prior = json.loads((reports / "slot-link-smoke/complete.json").read_bytes())
    need(
        prior["qualified"] and prior["host"] == host and shutil.disk_usage(tmp).free > 4 << 30,
        "missing actual native roles",
    )
    rec = reports / "slot-worktree-paths"
    rec.mkdir()
    states = {}
    with tempfile.TemporaryDirectory(prefix="ohm-release-worktree-", dir=tmp) as t:
        root = Path(t).resolve()
        for key, sdk in [("historical", link / "historical/sdk"), ("rebased", link / "sdk")]:
            versions = prior["results"][key]["versions"]
            rust = CHILD if key == "rebased" else PARENT
            cargo = (
                BIND["trees"]["src/tools/cargo"]
                if key == "rebased"
                else "4591cf45cc10abb19d2456c40b99606e08167f29"
            )
            need(
                "commit-hash: " + rust in versions["rustc"]["version"].splitlines()
                and "commit-hash: " + cargo in versions["cargo"]["version"].splitlines(),
                "foreign native source pair",
            )
            role(
                root / key,
                rec / key,
                sdk,
                link / "proxies",
                versions,
                key == "rebased",
                host.startswith("aarch64-"),
            )
            states[key] = checksum(rec / key / "complete.json")
    save(rec / "complete.json", {"host": host, "qualified": True, "roles": states})


if __name__ == "__main__":
    main()
