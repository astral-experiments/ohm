"""Qualify one genuine executable example against a clean build and a real GNU linker."""
import ast
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from factory import build, need, save, sha

HERE = Path(__file__).resolve().parent
EXAMPLE = "struct_name_as_context"
PACKAGE = "ruff_annotate_snippets"
WILD = "lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"
BRANCH = "refs/heads/charlie/qa-ruff-example-replay-20261102"
RENDERER = "17981f5b807be81496282dd5a58e579e71586962"
SEED = "46d28e8bff1c6b52f3e7b7bc13192019e964a7da"


def compressed(path, data):
    with path.open("xb") as stream:
        stream.write(gzip.compress(data, compresslevel=4, mtime=0))


def select(root, binaries, arm):
    dest = root / "sdk/bin/cargo"
    new = dest.with_suffix(".next")
    shutil.copy2(binaries[arm], new)
    new.replace(dest)
    need(sha(dest) == sha(binaries[arm]), "installed Cargo")


def reset(env, seed, w):
    for name in ("CARGO_TARGET_DIR", "CARGO_BUILD_BUILD_DIR", "CARGO_HOME"):
        path = Path(env[name])
        need(path.parent.name == "slot" and not path.is_symlink(), "owned sample slot")
        if path.exists():
            shutil.rmtree(path)
    w.registry(env, seed)


def sdk_executions(trace, root):
    rows = []
    wild = root / "distribution" / WILD
    compiler = root / "distribution/bin/rustc"
    cargo = root / "sdk/bin/cargo"
    for entry in sorted(trace.glob("exec.*")):
        for raw in entry.read_bytes().splitlines():
            if not raw.startswith(b'execve("') or not raw.endswith(b" = 0"):
                continue
            file = Path(os.fsdecode(raw.split(b'", [', 1)[0][8:]))
            if not file.is_absolute() or not file.is_file():
                continue
            kind = ("wild" if file.samefile(wild) else "rustc" if file.samefile(compiler) else
                    "cargo" if file.samefile(cargo) else None)
            if kind:
                line = raw.decode()
                args = ast.literal_eval(line[line.index("["):line.rindex("], ") + 1])
                rows.append({"kind":kind, "pid":int(entry.suffix[1:]), "path":str(file), "args":args,
                             "exec_sha256":hashlib.sha256(raw).hexdigest()})
    need(sum(r["kind"] == "cargo" for r in rows) == 1, "physical selected Cargo executed")
    return rows


def footprint(env):
    files = []
    seen = set()
    for key in ("CARGO_TARGET_DIR", "CARGO_BUILD_BUILD_DIR"):
        base = Path(env[key])
        for path in base.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            stat = path.stat()
            cookie = (stat.st_dev, stat.st_ino)
            if cookie in seen:
                continue
            seen.add(cookie)
            kind = ("rlink" if path.suffix == ".rlink" else
                    "manifest" if path.name.endswith(".rlink-cache.json") else
                    "object" if any(s.endswith(".rlink-objects") for s in path.parts) else "other")
            files.append((kind, stat.st_size, stat.st_blocks * 512))
    return {name: [len(sub), sum(x[1] for x in sub), sum(x[2] for x in sub)]
            for name, sub in ((name, [row for row in files if row[0] == name])
                              for name in ("rlink", "manifest", "object", "other"))}


def execute(root, src, env, out, args, *, error=None, trace=False, clock=None):
    out.mkdir()
    need(clock is None or not trace, "tracing excluded from hardware interval")
    cmd = ["cargo", "+ohm", *args, "--locked", "--offline", "-j4", "--message-format=json"]
    actual = cmd
    if trace:
        logs = out / "trace"
        logs.mkdir()
        actual = ["strace", "-ff", "-qq", "-s", "262144", "-e", "trace=execve",
                  "-o", str(logs / "exec"), *cmd]
    if clock:
        actual = [clock, out / "clock.json", *cmd]
    result = subprocess.run(actual, cwd=src, env=env, capture_output=True, timeout=1800)
    compressed(out / "stdout.gz", result.stdout)
    compressed(out / "stderr.gz", result.stderr)
    rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    good = error is None
    need((result.returncode == 0) == good and rows and
         rows[-1] == {"reason":"build-finished", "success":good},
         (out.name, result.returncode, result.stderr[-2000:], result.stdout[-2000:]))
    if clock:
        j = json.loads((out / "clock.json").read_bytes())
        need(j["code"] == result.returncode and j["event_errno"] == 0 and
             j["enabled"] == j["running"] > 0 and j["instructions"] > 0, "unscaled inherited hardware clock")
    diagnostics = [row["message"] for row in rows if row.get("reason") == "compiler-message"]
    if error == "E0308":
        need(any((msg.get("code") or {}).get("code") == "E0308" for msg in diagnostics), "real type error")
    if error == "provider":
        text = result.stderr + b"\n" + b"\n".join((msg.get("rendered") or "").encode() for msg in diagnostics)
        need(b"libutil.so" in text and any(s in text.lower() for s in
             (b"error", b"invalid", b"unrecognized")), ("malformed provider error", text[-3500:]))
    execs = sdk_executions(logs, root) if trace else []
    if trace:
        # Preserve every original process stream in the archive, including failed PATH searches.
        import tarfile
        with tarfile.open(out / "kernel-execs.tar.gz", "w:gz", compresslevel=3) as archive:
            archive.add(logs, arcname="trace")
        shutil.rmtree(logs)
    products = []
    executables = {}
    for row in rows:
        if row.get("reason") != "compiler-artifact":
            continue
        kind = row["target"]["kind"]
        name = row["target"]["name"]
        products.append([row["package_id"], name, kind, row["profile"]["test"], row["fresh"]])
        if row.get("executable"):
            file = Path(row["executable"])
            need(file.is_file() and file.resolve().is_relative_to(root) and
                 file.read_bytes()[:4] == b"\x7fELF", "private real ELF")
            executables["/".join([*kind, name, str(row["profile"]["test"])])] = [str(file), sha(file), file.stat().st_size]
    proof = {"argv":cmd, "returncode":result.returncode, "products":sorted(products),
             "executables":executables, "execs":execs, "storage":footprint(env)}
    save(out / "result.json", proof)
    return proof


def example_execs(proof, mode):
    compilers = [r["args"] for r in proof["execs"] if r["kind"] == "rustc" and
                 "--crate-name" in r["args"] and r["args"][r["args"].index("--crate-name")+1] == EXAMPLE]
    links = [r["args"] for r in proof["execs"] if r["kind"] == "wild" and "-o" in r["args"] and
             Path(r["args"][r["args"].index("-o")+1]).name == EXAMPLE]
    need(len(compilers) == len(links) == 1, ("one physical example rustc and Wild", len(compilers), len(links)))
    args, = compilers
    relink = "link-only" in args and any(a.endswith(".rlink") for a in args)
    need(mode is None or relink == (mode == "relink"), (mode, "observed relink", relink, args[:12]))
    return relink


def emitted(proof, src, env, token=None):
    file, digest, size = proof["executables"]["example/" + EXAMPLE + "/False"]
    need(sha(Path(file)) == digest, "compiler record still refers to the same file")
    ran = subprocess.run([file], cwd=src, env=env, capture_output=True, timeout=30, check=True)
    need(b"functions are not allowed in struct definitions" in ran.stdout + ran.stderr, "typed original example")
    markers = [line for line in ran.stderr.splitlines() if line.startswith(b"OHM_NATIVE_")]
    need(markers == ([token.encode()] if token else []), ("native constructor", token, markers))
    return [digest, size, hashlib.sha256(ran.stdout).hexdigest(), hashlib.sha256(ran.stderr).hexdigest()]


def oracle(w, out, src, env, state):
    result = w.oracle(out, src, env, state)
    slot = Path(env["CARGO_TARGET_DIR"]).parent
    for name in ("oracle-target", "oracle-shared"):
        path = slot / name
        need(slot.name == "slot" and path.is_dir() and not path.is_symlink(), "owned behavior check")
        shutil.rmtree(path)
    return result


def set_provider(directory, state):
    target = directory / "libutil.so"
    if state == "absent":
        if target.exists():
            target.unlink()
    elif state == "bad":
        target.write_bytes(b"OHM deliberately malformed registered libutil input\n")
    else:
        obj = directory / (state + ".o")
        if not obj.exists():
            source = '#include <unistd.h>\n__attribute__((constructor)) static void report(void) {\n'
            source += '  (void)write(2, "' + state + '\\n", sizeof("' + state + '\\n") - 1);\n}\n'
            subprocess.run(["cc", "-fPIC", "-x", "c", "-c", "-o", obj, "-"],
                           input=source.encode(), check=True)
        target.write_text("INPUT(" + str(obj) + ")\n")


def gate(root, src, env, out, w, seed, binaries):
    source = src / ("crates/" + PACKAGE + "/examples/" + EXAMPLE + ".rs")
    original = source.read_bytes()
    shadow = root / "native-shadow"
    shadow.mkdir()
    # GCC adds this ordinary native search directory to its real command line.
    # Holding it stable also allows a higher-priority provider to appear between commands.
    native_env = {**env, "LIBRARY_PATH":str(shadow)}
    args = ["build", "-p", PACKAGE, "--example", EXAMPLE]
    patch = Path(w.__file__).parent / "renderer.patch"
    winners = {}
    for arm in ("parent", "candidate"):
        select(root, binaries, arm)
        reset(env, seed, w)
        s = out / arm
        s.mkdir()
        set_provider(shadow, "absent")
        w.git(src, "apply", "--reverse", patch)
        w.sources(src, "old")
        cold = execute(root, src, native_env, s / "cold-old", args, trace=True)
        example_execs(cold, "full")
        old_image = emitted(cold, src, native_env)
        old_oracle = oracle(w, s / "old-behavior", src, native_env, "old")
        w.git(src, "apply", patch)
        w.sources(src, "corrected")
        edited = execute(root, src, native_env, s / "edit", args)
        unchanged = execute(root, src, native_env, s / "unchanged", args, trace=True)
        mode = "full" if arm == "parent" else "relink"
        example_execs(unchanged, mode)
        image = emitted(unchanged, src, native_env)
        need(emitted(edited, src, native_env) == image, "edit and unchanged image")
        source.write_bytes(original + b'\nconst _: u32 = "ohm type error";\n')
        execute(root, src, native_env, s / "rust-error", args, error="E0308")
        source.write_bytes(original)
        repaired = execute(root, src, native_env, s / "rust-repair", args, trace=True)
        example_execs(repaired, None)
        need(emitted(repaired, src, native_env) == image, "Rust repair result")
        initial = {}
        for step, state in (("first-provider","OHM_NATIVE_A"), ("replace-provider","OHM_NATIVE_B")):
            set_provider(shadow, state)
            value = execute(root, src, native_env, s / step, args, trace=True)
            example_execs(value, mode)
            initial[state] = emitted(value, src, native_env, state)
        need(initial["OHM_NATIVE_A"] != initial["OHM_NATIVE_B"], "provider changed runtime and binary")
        set_provider(shadow, "bad")
        failed = execute(root, src, native_env, s / "malformed", args, error="provider", trace=True)
        example_execs(failed, mode)
        set_provider(shadow, "OHM_NATIVE_B")
        value = execute(root, src, native_env, s / "provider-repair", args, trace=True)
        example_execs(value, None)
        need(emitted(value, src, native_env, "OHM_NATIVE_B") == initial["OHM_NATIVE_B"], "native repair")
        clean = {}
        for state in ("bad", "OHM_NATIVE_A", "OHM_NATIVE_B", "absent"):
            set_provider(shadow, state)
            reset(env, seed, w)
            value = execute(root, src, native_env, s / ("clean-" + state), args,
                            error="provider" if state == "bad" else None, trace=True)
            example_execs(value, "full")
            if state != "bad":
                expected = image if state == "absent" else initial[state]
                got = emitted(value, src, native_env, None if state == "absent" else state)
                need(got == expected, ("independent clean native bytes and outputs", state))
                clean[state] = got
        corrected_oracle = oracle(w, s / "corrected-behavior", src, native_env, "corrected")
        winners[arm] = {"old_image":old_image,"new_image":image,"providers":clean,
                        "old_oracle":old_oracle,"corrected_oracle":corrected_oracle}
    need(winners["parent"]["providers"] == winners["candidate"]["providers"] and
         winners["parent"]["old_image"] == winners["candidate"]["old_image"], "matched executable behavior")
    save(out / "qualified.json", winners)


def main():
    need(os.environ["GITHUB_REPOSITORY"] == "astral-experiments/ohm" and os.environ["GITHUB_REF"] == BRANCH
         and os.environ["GITHUB_RUN_ATTEMPT"] == "1" and os.environ["GITHUB_SHA"] == os.environ["REVIEWED_HEAD"],
         "reviewed nonrelease workflow")
    ws = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
    for folder, expected in (("enrolled", os.environ["GITHUB_SHA"]), ("seed", SEED), ("historical", RENDERER)):
        need(subprocess.check_output(["git","-C",ws / folder,"rev-parse","HEAD"]).decode().strip() == expected,
             "physical source checkout " + folder)
    sys.path.insert(0, str(ws / "historical/scripts/gnu-example-ceiling"))
    import workload as w
    root = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True) / "ruff-example-replay"
    root.mkdir()
    out = root / "evidence"
    out.mkdir()
    binaries = build(root, ws, out)
    select(root, binaries, "parent")
    src = w.source(root)
    env = w.env_for(root)
    seed = w.prepare_registry(root, src, env, out)
    gate(root, src, env, out, w, seed, binaries)
    save(out / "terminal.json", {"schema":1,"sha":os.environ["GITHUB_SHA"],"run":os.environ["GITHUB_RUN_ID"],
         "boot":Path("/proc/sys/kernel/random/boot_id").read_text().strip(), "source":w.REG["ruff"],
         "edit":w.REG["edit"],"binaries":{name:sha(p) for name,p in binaries.items()},
         "sdk_rustc":sha(root/"distribution/bin/rustc"),"sdk_wild":sha(root/"distribution"/WILD)})


if __name__ == "__main__":
    main()
