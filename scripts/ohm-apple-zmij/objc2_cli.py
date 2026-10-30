"""Trace the actual macOS ty build across Ruff's literal response-file fix."""

import argparse
import json
import subprocess
import tomllib
from pathlib import Path

from dyld import check as check_dyld
from execs import ExecTrace
from fixed_crc import evidence as native_receipt
from local_dev import observe
import cgu_inputs
import cli_images
from measure import capture, fresh, native_rows, retire, select
from prepare import prepare_ruff
from study import MISSING, RECHECK, check_host, compress_bytes, digest, env_for, git, need, save, sdk_id, sha, text_git
from verbs import macho_text

OLD = "4710e1aa962b13720cf64aa84eb279c5333896d7"
NEW = "915bb2b4bf9ae7eee47cf55646bbfebae254a23b"
TREES = {OLD: "81560f51b2974feba14a187071ced7f1a86a8f1a", NEW: "77cc553e8be94195bb5737a8ffda775c577ca113"}
LOCK = {OLD: "3a079a64dd1783c6177fc86ca98238a65f4bc56e3e7a1ac8eb9cae2c5eba4ad9",
        NEW: "23e8dbc9a2f451fa819d63da20a9d3ca24de8b2ebda59c99930a8c0edc4044c7"}
OBJC2 = "b7c2599ce0ec54857b29ce62166b0ed9b4f6f1a70ccc9a71165b6154caca8c05"
SOURCES = {"lib.rs": "f885891640bf8d9db339a63130cdef0f2c9bd660bcbf7c818c415e23e7e74a0b",
           "rc/retained.rs": "deaa939673ac1b7bf3d2c40b77a4d86fd06b805b301b1bdca10a220ed4e1b551",
           "runtime/retain_release_fast.rs": "0abc01b25d42902d7083cebed12b0fb1a72b9733679c7892fe7c3ebbeea36b6e"}
BAD = "ohm_objc2_response_file_missing"
CMD = ["cargo", "+ohm", "build", "-p", "ty", "--bin", "ty", "--locked", "--offline", "-j4", "--message-format=json"]
ARGS = ["check", "--output-format", "concise", "@list.py", "--", "@outer.args"]
CASES = {"@list.py": "value: int = 'literal'", "list.py": "other.py\n",
         "@package/main.py": "value: int = 'directory'", "package": "other.py\n",
         "other.py": "", "outer.args": "@inner.args\n", "inner.args": "@package\n"}
NEW_STDOUT = (
    '@list.py:1:14: error[invalid-assignment] Object of type `Literal["literal"]` is not assignable to `int`\n'
    '@package/main.py:1:14: error[invalid-assignment] Object of type `Literal["directory"]` is not assignable to `int`\n'
    'Found 2 diagnostics\n'
).encode()
PLAN = [("cold", OLD), ("edit", NEW), ("repeat-1", NEW), ("repeat-2", NEW), ("invalid", NEW), ("repair", NEW)]


class CliTrace(ExecTrace):
    def command(self, argv, **kwargs):
        return super().command(argv, timeout=2100, **kwargs)


def identity(repo):
    need(text_git(repo, "rev-parse", "HEAD") == OLD and text_git(repo, "rev-parse", NEW+"^") == OLD, "wrong Ruff commits")
    registries = []
    for rev in (OLD, NEW):
        lock = git(repo, "show", rev+":Cargo.lock")
        need(text_git(repo, "rev-parse", rev+"^{tree}") == TREES[rev] and digest(lock) == LOCK[rev], "wrong Ruff source")
        registries.append({(p["name"], p["version"], p["source"]): p["checksum"]
                           for p in tomllib.loads(lock.decode())["package"] if "checksum" in p})
    need(registries[0] == registries[1] and registries[0]["objc2", "0.6.3", "registry+https://github.com/rust-lang/crates.io-index"] == OBJC2,
         "registry resolution differs")
    test = git(repo, "show", NEW+":crates/ty/tests/cli/file_selection.rs")
    need(b"fn response_files_preserve_literal_at_paths()" in test and all(line in test for line in NEW_STDOUT.splitlines()), "Ruff's CLI snapshot changed")


def checkout(repo, rev, invalid):
    git(repo, "restore", "--source", rev, "--staged", "--worktree", "--", ".")
    need(text_git(repo, "write-tree") == TREES[rev] and not git(repo, "diff", "--name-only")
         and sha(repo/"Cargo.lock") == LOCK[rev] and text_git(repo, "rev-parse", "HEAD") == OLD, "Ruff tree drift")
    if invalid:
        with (repo/"crates/ty/src/lib.rs").open("ab") as stream:
            stream.write(("\npub const OHM_ERROR: usize = " + BAD + ";\n").encode())


def audit_objc2(units, work, out):
    libs = [u for u in units if u["target"]["name"] == "objc2" and u["target"]["kind"] == ["lib"]]
    evidence = []
    for index, unit in enumerate(libs):
        src = Path(unit["target"]["src_path"])
        need(all(sha(src.parent/name) == checksum for name, checksum in SOURCES.items()), "unexpected objc2 registry source")
        archive, = [Path(f) for f in unit["filenames"] if f.endswith(".rlib")]
        depname = archive.stem.removeprefix("lib") + ".d"
        unique = {(p.stat().st_dev, p.stat().st_ino): p for d in (work/"target", work/"shared") for p in d.rglob(depname)}
        dep, = unique.values()
        raw = dep.read_bytes()
        need(b"objc2-0.6.3/src/" in raw, "unrelated objc2 dep-info")
        compress_bytes(out/("objc2-"+str(index)+".dep.gz"), raw)
        evidence.append({"archive": str(archive), "sha256": sha(archive), "features": unit["features"], "fresh": unit["fresh"],
                         "source": str(src), "dep": digest(raw), "hard": MISSING in raw, "recheck": RECHECK in raw})
    need(evidence and len({a["archive"] for a in evidence}) == len(evidence), "missing or duplicate objc2 artifact")
    return evidence


def witness(root, out, path, rev):
    actual = subprocess.run([str(path), *ARGS], cwd=root/"literal-inputs",
                            env={"XDG_CONFIG_HOME": str(root/"empty-xdg")}, capture_output=True, timeout=150)
    compress_bytes(out/"ty-stdout.gz", actual.stdout)
    compress_bytes(out/"ty-stderr.gz", actual.stderr)
    save(out/"ty-exit.json", actual.returncode)
    program = macho_text(path)
    need(cli_images.keep(root, path.read_bytes()) == program["raw"], "returned CLI differs from held bytes")
    want = (0, b"All checks passed!\n") if rev == OLD else (1, NEW_STDOUT)
    need((actual.returncode, actual.stdout) == want and actual.stderr == b"", f"wrong CLI behavior {actual.returncode}: {actual.stdout!r} {actual.stderr!r}")
    return program | {"exit": actual.returncode, "stdout": digest(actual.stdout), "stderr": digest(actual.stderr)}


def phase(root, work, sdk, env, out, step, rev, trace, prior=None):
    ok = step != "invalid"
    code, stdout, stderr, events, streams = capture(CMD, root/"ruff", env, out, trace)
    need(code == (0 if ok else 101), f"wrong Cargo exit {code}: {stderr[-600:]!r}")
    msgs = [json.loads(line) for line in stdout.splitlines()]
    need(msgs[-1] == {"reason": "build-finished", "success": ok}, "incomplete Cargo verdict")
    units = [m for m in msgs if m["reason"] == "compiler-artifact"]
    objc2 = audit_objc2(units, work, out)
    if step in ("cold", "clean", "edit"):
        emitters = observe(events, work, sdk, {"ty"}, out)
        if step in ("cold", "clean"):
            need(any("--crate-type" in e["argv"] and e["argv"][e["argv"].index("--crate-type")+1] == "bin" for e in emitters), "missing incremental ty binary compiler")
    native = native_rows(events, sdk)
    need(native["scope"] == "kernel-exec" and native["cargo"] == 1 and all(l["stock"] for l in native["linkers"]), "foreign Cargo or linker")
    need(native["full"].count("objc2") == sum(not u["fresh"] for u in objc2), "typed/physical objc2 disagreement")
    binaries = [u for u in units if u["target"]["name"] == "ty" and u["target"]["kind"] == ["bin"] and
                not u["profile"]["test"] and u["executable"]]
    links = []
    for linker in native["linkers"]:
        target, = [p for opt, p in zip(linker["argv"], linker["argv"][1:]) if opt == "-o"]
        name = Path(target).name
        if name == "ty" or name.startswith("ty-") and len(name) == 19 and all(c in "0123456789abcdef" for c in name[3:]):
            links.append(target)
    product = None
    if ok:
        binary, = binaries
        path = Path(binary["executable"]).resolve(strict=True)
        need(path.samefile(work/"target/debug/ty"), "Cargo returned another program")
        product = witness(root, out, path, rev)
        for name in links:
            candidate = Path(name)
            need(candidate.is_file() and (candidate.samefile(path) or sha(candidate) == product["raw"]), "native link output does not match returned ty")
        if step in ("cold", "clean", "edit"):
            need(len(links) == 1 and "ty" in native["full"], "expected a genuine ty link")
    else:
        errors = [m["message"] for m in msgs if m["reason"] == "compiler-message"]
        need(not binaries and not links and any((e.get("code") or {}).get("code") == "E0425" and BAD in e["message"] for e in errors), "missing edited error")
    row = {"step": step, "rev": rev, "code": code, "command": CMD, "streams": streams, "native": native,
           "units": len(units), "dirty": sorted(u["target"]["name"] for u in units if not u["fresh"]),
           "objc2": objc2, "links": links, "product": product}
    if ok:
        if links:
            output, = links
            linker, = [l["argv"] for l in native["linkers"] if
                       [b for a,b in zip(l["argv"],l["argv"][1:]) if a=="-o"] == [output]]
            proof = cgu_inputs.witness(root, out, path.read_bytes(), output, linker=linker)
        else:
            need(prior is not None and product["raw"] in prior, "no earlier physical linker for this exact CLI")
            proof = prior[product["raw"]]
            save(out/"prior-cgu-proof.json", {"raw": proof["raw"], "recipe": proof["recipe"],
                                             "observed_link": proof["linker_argv"]})
        if prior is not None:
            prior[product["raw"]] = proof
        row["cgu"] = {k: proof[k] for k in ("output", "raw", "same_path_image", "cross_path_image", "modules")}
    save(out/"verified.json", row)
    native_receipt(work, out, row)
    print(step, rev[:8], "full", len(native["full"]), "link-only", len(native["link_only"]), "ld", len(native["linkers"]),
          "ty links", len(links), "objc2", native["full"].count("objc2"), flush=True)
    return row


def installation(root, role, trace, prefix):
    prefix = prefix/role
    work = root/"objc2-work"
    work.mkdir(exist_ok=True)
    sdk = select(root, role)
    env = env_for(work, sdk)
    before = sdk_id(sdk, env)
    save(prefix/"development-environment.json",{k:digest(v.encode()) for k,v in sorted(env.items())})
    save(prefix/"installation.json", before)
    check_dyld(root, role, sdk, prefix/"dyld")
    results = {}
    for group, steps in (("clean-old", [("clean", OLD)]), ("clean-new", [("clean", NEW)]), ("visits", PLAN)):
        check_host(root, 28)
        fresh(work, root/"seed")
        results[group] = {}
        prior = {}
        previous = None
        for label, rev in steps:
            state = (rev, label == "invalid")
            if previous != state:
                checkout(root/"ruff", *state)
            results[group][label] = phase(root, work, sdk, env, prefix/group/label, label, rev, trace, prior)
            previous = state
        retire(work)
    refs = {rev: results[group]["clean"] for rev, group in ((OLD, "clean-old"), (NEW, "clean-new"))}
    comparisons = {label: cgu_inputs.same_product(row["product"],refs[row["rev"]]["product"],row["cgu"],refs[row["rev"]]["cgu"])
                   for label, row in results["visits"].items() if row["product"]}
    save(prefix/"comparison.json", comparisons)
    need(refs[OLD]["product"]["raw"] != refs[NEW]["product"]["raw"] and before == sdk_id(sdk, env), "missing real edit or compiler changed")
    counts = {label: {"rustc": len(row["native"]["full"]), "link_only": len(row["native"]["link_only"]),
                    "ld": len(row["native"]["linkers"]), "ty_ld": len(row["links"]),
                    "objc2": row["native"]["full"].count("objc2")} for label, row in results["visits"].items()}
    return counts, comparisons


def mechanism(root):
    fixture = root/"literal-inputs"
    fixture.mkdir()
    (root/"empty-xdg").mkdir()
    for name, contents in CASES.items():
        path = fixture/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)
    trace = CliTrace()
    try:
        trace.ready()
        prefix = root/"receipts/objc2-cli"
        orders = {}
        for order in ("PC", "CP"):
            results = {role: installation(root, role, trace, prefix/order) for role in order}
            physical = {role: counts for role, (counts, _comparisons) in results.items()}
            checks = {role: comparisons for role, (_counts, comparisons) in results.items()}
            need(all(all(c.values()) for c in checks.values()), "warm ty differs from an independent empty build")
            for role in order:
                for label, _rev in PLAN:
                    proof = json.loads((prefix/order/role/"visits"/label/"verified.json").read_text())
                    need(all(v["hard"] == (role=="P") and v["recheck"] == (role=="C")
                             for v in proof["objc2"]), "unexpected objc2 dep-info classification")
            cross = {}
            for source in ("clean-old", "clean-new"):
                roots = {r: json.loads((prefix/order/r/source/"clean/verified.json").read_bytes()) for r in order}
                p, c = [roots[r]["cgu"] for r in "PC"]
                need(p["cross_path_image"] == c["cross_path_image"] and p["modules"] == c["modules"],
                     "physical cross-compiler complete CLI or root objects differ beyond verified paths")
                cross[source] = p["cross_path_image"]
            orders[order] = {"physical": physical, "clean": checks, "cross": cross}
            save(prefix/(order+"-closed.json"), orders[order])
        save(prefix/"mechanism.json", {"orders": orders, "timing": None, "command": CMD})
    finally:
        trace.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("seed", "mechanism"))
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    if args.mode == "seed":
        prepare_ruff(root, OLD, NEW, identity)
        crate, = (root/"seed/registry/cache").glob("*/objc2-0.6.3.crate")
        need(sha(crate) == OBJC2, "wrong objc2 archive")
    else:
        mechanism(root)
