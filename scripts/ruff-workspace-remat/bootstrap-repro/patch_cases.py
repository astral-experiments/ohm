import hashlib
import json
import shutil
import subprocess
from pathlib import Path

work = Path.cwd()
config = json.loads((work / "inputs.json").read_text())
rust_tree = Path(config["rust"])
originals = Path(config["sources"])
llvm = Path(config["llvm"])
sdk = Path(config["sdk"])
llvm_library = Path(config["library"])
wrapper = rust_tree / "compiler/rustc_llvm/llvm-wrapper/OhmRegisterCoalescer.cpp"
base = work / "product-cases"
base.mkdir()
hash_bytes = lambda b: hashlib.sha256(b).hexdigest()
hash_file = lambda f: hash_bytes(f.read_bytes())
result = {}


def run_case(
    name,
    arm,
    mode="gnu",
    macro=False,
    expected_exit=0,
    run_native=False,
    reuse=None,
    source=originals,
):
    case = base / (reuse or name)
    case.mkdir(exist_ok=True)
    tools = case / ("tools-" + name)
    tools.mkdir()
    for n in ("as", "ld", "sh", "uname", "env", "readlink", "sed"):
        x = Path("/usr/bin") / n
        if x.is_file():
            (tools / n).symlink_to(x)
    if mode == "gnu":
        (tools / "patch").symlink_to("/usr/bin/patch")
    elif mode == "reject":
        (tools / "patch").write_text("#!/bin/sh\nexit 37\n")
        (tools / "patch").chmod(0o755)
    env = {
        "PATH": str(tools),
        "HOME": str(case),
        "OUT_DIR": str(case),
        "TARGET": "x86_64-unknown-linux-gnu",
        "HOST": "x86_64-unknown-linux-gnu",
        "OPT_LEVEL": "0",
        "DEBUG": "false",
        "LLVM_RUSTC_OHM_COALESCER_SOURCE": str(source),
        "OHM_QA_LLVM_INCLUDE": str(llvm / "include"),
        "OHM_QA_WRAPPER": str(wrapper),
        "LC_ALL": "C",
    }
    out = case / (name + "-fallback.o")
    if run_native:
        env["OHM_QA_FALLBACK_OBJECT"] = str(out)
    private = case / ("private-cwd-" + name)
    dest = private / "llvm-wrapper/ohm-register-coalescer/RegisterCoalescer.patch"
    dest.parent.mkdir(parents=True)
    shutil.copy2(
        rust_tree
        / "compiler/rustc_llvm/llvm-wrapper/ohm-register-coalescer/RegisterCoalescer.patch",
        dest,
    )
    before = sorted(
        str(x.relative_to(private)) for x in private.rglob("*") if x.is_file()
    )
    cmd = [work / "product-target/debug/ohm-private-optional-patch", arm]
    child = subprocess.run(
        cmd, cwd=private, env=env, check=False, capture_output=True, timeout=8
    )
    stdout = child.stdout.decode()
    stderr = child.stderr.decode()
    flags = [l for l in stdout.splitlines() if l.startswith("QA_FLAGS=")]
    body = case / "ohm-register-coalescer/RegisterCoalescer.cpp"
    files = {
        str(x.relative_to(private)): hash_file(x)
        for x in private.rglob("*")
        if x.is_file()
    }
    receipt = {
        "private_input": before,
        "private_after": files,
        "code": child.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "output_size": body.stat().st_size if body.exists() else None,
        "output_sha256": hash_file(body) if body.is_file() else None,
        "flags": flags,
    }
    result[name] = receipt
    assert child.returncode == expected_exit and (
        (len(flags) == 1 and ("-DLLVM_RUSTC_OHM_COALESCER" in flags[0]) == macro)
        if expected_exit == 0
        else not flags
    ), receipt
    if run_native:
        symbols = subprocess.check_output(["nm", "-u", out], text=True).split()
        assert symbols == ["U", "LLVMCreatePassManager"], symbols
        elf = case / (name + "-native")
        subprocess.run(
            [
                "/usr/bin/cc",
                "-O0",
                "-Werror",
                "-I",
                llvm / "include",
                work / "original-manager.c",
                out,
                llvm_library,
                "-Wl,-rpath," + str(sdk / "lib"),
                "-o",
                elf,
            ],
            check=True,
            capture_output=True,
            timeout=10,
        )
        native = subprocess.run([elf], check=True, capture_output=True, timeout=4)
        assert (
            native.stdout
            == b"stock-manager: allow=false,true; changed=false; typed-return=i32 2026\n"
        )
        receipt.update(
            fallback_object=hash_file(out),
            fallback_undefined=symbols,
            native_stdout=native.stdout.decode(),
            native_sha=hash_file(elf),
        )
    if arm == "new":
        rejects = [
            path for path in case.rglob("*") if path.name.endswith((".rej", ".orig"))
        ]
        assert not rejects, rejects
    return receipt


old = run_case("old-good", "old", macro=True)
new = run_case("new-good", "new", macro=True, reuse="prior-good")
assert (
    old["output_sha256"] == new["output_sha256"]
    and old["output_size"] == new["output_size"]
)
ref = run_case("old-missing", "old", mode="missing", expected_exit=101)
assert "could not apply the Ohm LLVM patch" in ref["stderr"]
for name, mode, reuse in [
    ("new-missing", "missing", None),
    ("new-rejected", "reject", None),
    ("new-missing-after-success", "missing", "prior-good"),
]:
    receipt = run_case(name, "new", mode=mode, run_native=True, reuse=reuse)
    assert "using LLVM's original register coalescer" in receipt["stdout"]
bad = base / "bad-original"
bad.mkdir()
(bad / "RegisterCoalescer.cpp").write_text("int fixture;\n")
shutil.copy2(originals / "RegisterCoalescer.h", bad / "RegisterCoalescer.h")
receipt = run_case("actual-patch-did-not-apply", "new", source=bad, run_native=True)
assert "could not apply the LLVM patch" in receipt["stdout"]
(work / "patch-cases.json").write_text(json.dumps(result, indent=2) + "\n")
print(
    len(result),
    "cases, patched bytes",
    new["output_size"],
    new["output_sha256"],
    "fallback object",
    receipt["fallback_object"],
)
