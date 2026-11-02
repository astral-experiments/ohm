"""Compare the two source-built compilers on ordinary full Ruff branch switches."""

from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tomllib

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ruff-indexed-check-pmu"))
import worker as m
from acquire import LOG, REG, ROOT, need, sha, json_save

WS, WORK, SRC, STATE = m.WS, m.WORK, m.SRC, m.STATE
NATIVE = WS / "oracle/scripts/ohm-packed-ruff"
sys.path.insert(0, str(NATIVE / "full-cli"))
import native
sys.path.insert(0, str(HERE))
import qualified

CASE, = REG["source"]
CMD = ["cargo", "+ohm", "build", "-p", "ruff", "--bin", "ruff", "--locked", "--offline", "-j4", "--message-format=json"]
BRANCH = {"A": "historical-parent", "B": "historical-feature"}
PARSER = Path("crates/ruff_python_parser/src/lib.rs")
BAD = b"\nconst ohm_branch_switch_invalid: () = 1u32;\n"
OWNERS = ("ruff_workspace", "ruff_linter")


def setup():
    need(os.environ["GITHUB_REF"] == "refs/heads/charlie/qa-upstream-mono-ruff-20261102"
         and os.environ["GITHUB_EVENT_NAME"] == "workflow_dispatch"
         and os.environ["GITHUB_RUN_ATTEMPT"] == "1"
         and os.environ["GITHUB_SHA"] == os.environ["REVIEWED_HEAD"], "unenrolled pilot")
    WORK.mkdir()
    for path, rev in [(WS / "qa", os.environ["REVIEWED_HEAD"]), (WS / "collector", REG["collector"]),
                      (WS / "oracle", "bd7b58765ae44b21a1c9273b3ff0be8e923adc47")]:
        need(m.git(path, "rev-parse", "HEAD") == rev and not m.git(path, "status", "--porcelain"), "unexpected checkout")
    for rev, tree in zip(("A", "B"), CASE["trees"], strict=True):
        path = WS / ("ast-" + rev)
        need(m.git(path, "rev-parse", "HEAD", "HEAD^{tree}").splitlines() == [CASE[rev], tree], "wrong Ruff tree")
    m.run(["git", "clone", "-q", "--no-hardlinks", "--no-tags", "--no-checkout", WS / "ast-B", SRC])
    need(m.git(SRC, "rev-parse", CASE["B"] + "^") == CASE["A"]
         and m.git(SRC, "diff", "--name-status", "--no-renames", CASE["A"], CASE["B"]).splitlines() == CASE["changes"],
         "different Ruff edit")
    for rev in ("A", "B"):
        m.git(SRC, "branch", BRANCH[rev], CASE[rev])
    (ROOT / "harness").mkdir()
    shutil.copyfile(NATIVE / "harness/consumer.rs", ROOT / "harness/consumer.rs")
    physical = {}
    for cpu in sorted(os.sched_getaffinity(0)):
        topology = Path("/sys/devices/system/cpu") / f"cpu{cpu}/topology"
        pair = tuple((topology / name).read_text().strip() for name in ("physical_package_id", "core_id"))
        physical.setdefault(pair, cpu)
    cpus = list(physical.values())[:4]
    need(len(cpus) == 4, "need four physical cores")
    os.sched_setaffinity(0, cpus)
    json_save(LOG / "cpu.json", dict(cpus=cpus, boot=Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                                     cpuinfo=Path("/proc/cpuinfo").read_text()))
    (m.RUSTUP / "toolchains").mkdir(parents=True)
    (m.RUSTUP / "settings.toml").write_text('version = "12"\nprofile = "minimal"\n')
    m.PROXIES.mkdir()
    rustup = Path(shutil.which("rustup")).resolve(strict=True)
    for n in ("cargo", "rustc", "rustup"):
        (m.PROXIES / n).symlink_to(rustup)
    for n in ("cargo-home", "temp"):
        (WORK / n).mkdir()
    env = dict(HOME=str(WORK / "home"), RUSTUP_HOME=str(m.RUSTUP), RUSTUP_AUTO_INSTALL="0",
               CARGO_HOME=str(WORK / "cargo-home"), CARGO_NET_OFFLINE="true", CARGO_CACHE_AUTO_CLEAN_FREQUENCY="never",
               CARGO_TARGET_DIR=str(STATE / "target"), CARGO_BUILD_BUILD_DIR=str(STATE / "build"),
               PATH=str(m.PROXIES) + ":/usr/bin:/bin", TMPDIR=str(WORK / "temp"), LC_ALL="C",
               CARGO_TERM_COLOR="never", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null",
               SSL_CERT_FILE="/etc/ssl/certs/ca-certificates.crt")
    selected = m.set_arm("P", env)
    need(m.calibrate(selected) == "native", "hardware count unavailable")
    for rev in ("B", "A"):
        switch(rev)
        online = dict(selected)
        del online["CARGO_NET_OFFLINE"]
        m.run(["cargo", "+ohm", "fetch", "--locked"], cwd=SRC, env=online, timeout=600)
        locked = tomllib.loads((SRC / "Cargo.lock").read_text())["package"]
        verified = {}
        for dep in locked:
            if dep.get("source", "").startswith("registry+"):
                name = f'{dep["name"]}-{dep["version"]}.crate'
                archive, = (WORK / "cargo-home/registry/cache").glob("*/" + name)
                need(sha(archive) == dep["checksum"], "different dependency " + name)
                verified[name] = dep["checksum"]
        need(verified, "no registry inputs")
        json_save(LOG / ("crates-" + rev + ".json"), verified)
    json_save(LOG / "environment.json", env)
    return env


def switch(rev):
    m.git(SRC, "checkout", "-q", BRANCH[rev])
    need(m.git(SRC, "rev-parse", "HEAD") == CASE[rev] and not m.git(SRC, "status", "--porcelain"), "unrelated tree")


def fresh():
    if STATE.exists():
        m.clear_state()
    for name in ("target", "build"):
        (STATE / name).mkdir(parents=True)


def allocations():
    inodes = {}
    for owner in ("target", "build"):
        for path in (STATE / owner).rglob("*"):
            if path.is_file() and not path.is_symlink():
                st = path.stat()
                inodes[st.st_dev, st.st_ino] = st.st_blocks * 512
    return dict(files=len(inodes), bytes=sum(inodes.values()))


def current(owner, exclude=()):
    dirs = {p.resolve() for p in STATE.rglob("dep-graph.bin")
            if p.parent.parent.name.startswith(owner + "-") and p.parent.name.startswith("s-")
            and not p.parent.name.endswith("-working")}
    new = {p.parent for p in dirs} - set(exclude)
    need(len(new) == 1, ("ambiguous completed incremental session", owner, sorted(map(str, new))))
    return new.pop()


def pin_outputs(stack):
    old = {}
    for owner in OWNERS:
        session = current(owner)
        files = {}
        for path in session.glob("*.o"):
            raw = stack.enter_context(path.open("rb"))
            identity = os.fstat(raw.fileno())
            digest = hashlib.file_digest(raw, "sha256").hexdigest()
            files[path.name] = (raw, [identity.st_dev, identity.st_ino, identity.st_size], digest)
            raw.seek(0)
        need(len(files) > 20, ("no native CGU donors", owner))
        old[owner] = session, files
    return old


def measure_outputs(old):
    report = {}
    for owner, (prior, files) in old.items():
        present = {p.parent for p in STATE.rglob("dep-graph.bin") if p.parent.parent.name.startswith(owner + "-")}
        session = current(owner, (prior,)) if present - {prior} else prior
        new = {p.name: p for p in session.glob("*.o")}
        need(new and set(files) & set(new), ("no common CGUs", owner))
        rows = {}
        for name in sorted(set(files) | set(new)):
            pinned = files.get(name)
            path = new.get(name)
            previous, digest = None, None
            if pinned:
                raw, previous, digest = pinned
                need(hashlib.file_digest(raw, "sha256").hexdigest() == digest, "original donor mutated during build")
            now = path.stat() if path else None
            final = [now.st_dev, now.st_ino, now.st_size] if now else None
            rows[name] = dict(previous=previous, current=final,
                              same_inode=bool(previous and final and previous[:2] == final[:2]),
                              before_sha256=digest, after_sha256=sha(path) if path else None)
            need(not rows[name]["same_inode"] or rows[name]["before_sha256"] == rows[name]["after_sha256"],
                 "same donor acquired different bytes")
        report[owner] = dict(prior=str(prior), current=str(session), objects=rows)
    return report


def cargo(env, folder, rev, counted, *, invalid=False, cold=False):
    folder.mkdir()
    need(shutil.disk_usage(WORK).free >= 15 << 30, "insufficient space for ordinary Ruff")
    if counted:
        result, count = m.window(folder / "clock", CMD, env, SRC, "native")
        need(count is not None, "incomplete hardware window")
    else:
        result, count = m.run(CMD, env=env, cwd=SRC, check=False, timeout=840), None
    m.dump_gz(folder, "cargo.stdout.gz", result.stdout)
    m.dump_gz(folder, "cargo.stderr.gz", result.stderr)
    rows = list(map(json.loads, result.stdout.splitlines()))
    need(rows[-1] == {"reason": "build-finished", "success": not invalid}
         and result.returncode == (101 if invalid else 0), ("wrong Cargo result", result.stderr[-1500:]))
    errors = [r for r in rows if r.get("reason") == "compiler-message" and r["message"]["level"] == "error"]
    if invalid:
        coded = [r for r in errors if r["message"].get("code")]
        need(len(coded) == 1 and coded[0]["message"]["code"]["code"] == "E0308"
             and coded[0]["target"]["name"] == "ruff_python_parser"
             and any(s["file_name"] == str(PARSER) and s["is_primary"] for s in coded[0]["message"]["spans"]),
             "wrong typed rejection")
        json_save(folder / "visit.json", dict(rev=rev, invalid=True))
        return None
    need(not errors, "successful build emitted errors")
    products = [r for r in rows if r.get("reason") == "compiler-artifact"]
    need(len(products) == 375 and (not cold or not any(r["fresh"] for r in products)), "incorrect real build inventory")
    roster = sorted((r["package_id"], r["target"]["name"], tuple(r["target"]["kind"]), tuple(r["features"]),
                     r["profile"]["test"]) for r in products)
    roster_sha = hashlib.sha256(json.dumps(roster, separators=(",", ":")).encode()).hexdigest()
    desc, paths = native.observed(rows, rev, CASE[rev], env, ROOT, SRC, STATE, folder)
    result = dict(rev=rev, roster=roster_sha, whole={k: v["whole"] for k, v in desc.items() if k in ("cli", "reader")},
                  count=count, dirty=sum(not r["fresh"] for r in products), storage=allocations())
    json_save(folder / "visit.json", result)
    return desc, paths, result


def main():
    env0 = setup()
    references = {}
    history = {}
    for role in "PC":
        fresh()
        switch("A")
        env = m.set_arm(role, env0)
        folder = LOG / ("clean-A-" + role)
        desc, paths, row = cargo(env, folder, "A", False, cold=True)
        references[role, "A"] = desc, row["roster"]
        for kind, path in paths.items():
            native.preserve(path, desc[kind], ROOT / "reference-bytes", LOG / "reference-bodies")
    for block, order in enumerate(("PC", "CP")):
        for role in order:
            name = f"{block}-{role}"
            out = LOG / name
            out.mkdir()
            env = m.set_arm(role, env0)
            fresh()
            switch("B")
            desc, paths, cold = cargo(env, out / "B", "B", True, cold=True)
            if (role, "B") not in references:
                references[role, "B"] = desc, cold["roster"]
                for kind, path in paths.items():
                    native.preserve(path, desc[kind], ROOT / "reference-bytes", LOG / "reference-bodies")
            for kind, path in paths.items():
                native.same_file(path, desc[kind], references[role, "B"][0][kind], ROOT / "reference-bytes", out / "B")
            need((desc, cold["roster"]) == references[role, "B"], "different clean B behavior")
            with ExitStack() as stack:
                old = pin_outputs(stack)
                switch("A")
                desc, paths, edit = cargo(env, out / "A", "A", True)
                objects = measure_outputs(old)
                json_save(out / "objects.json", objects)
            def exact(visit, observed, expected_roster):
                data, files, row = observed
                need((data, row["roster"]) == (references[role, "A"][0], expected_roster), "different clean native results")
                for key, path in files.items():
                    native.same_file(path, data[key], references[role, "A"][0][key], ROOT / "reference-bytes", visit)
                return row
            expected_roster = references[role, "A"][1]
            exact(out / "A", (desc, paths, edit), expected_roster)
            steady = exact(out / "unchanged", cargo(env, out / "unchanged", "A", True), expected_roster)
            parser = SRC / PARSER
            valid = parser.read_bytes()
            parser.write_bytes(valid + BAD)
            cargo(env, out / "invalid", "A", False, invalid=True)
            parser.write_bytes(valid)
            exact(out / "repair", cargo(env, out / "repair", "A", False), expected_roster)
            need(not m.git(SRC, "status", "--porcelain"), "dirty repaired Ruff")
            history[name] = dict(role=role, order=order, cold=cold["count"], edit=edit["count"],
                                 steady=steady["count"], same={k: sum(rec["same_inode"] for rec in v["objects"].values())
                                                               for k, v in objects.items()})
            json_save(out / "summary.json", history[name])
    approved = {rev: qualified.accepted(rev, references["P", rev], references["C", rev]) for rev in ("A", "B")}
    json_save(LOG / "pilot.json", dict(head=os.environ["REVIEWED_HEAD"], history=history,
             native_family_sha256=qualified.SHA256, cross_role_native_qualified=approved))
    need(all(approved.values()), "complete native outputs differ from the independently qualified reference family")



if __name__ == "__main__":
    main()
