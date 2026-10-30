"""Capture literal checked-input Rust compiler verdicts on the observed compact_str barrier."""
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ohm-aarch64-linux"))
import runtime as rt
from study import MISSING, RECHECK, digest, need, save, sha

NEW = ("compact_input", "compact_modifier", "compact_options", "compact_output", "compact_two_operands", "compact_file")
PRIOR = ("ordinary", "general_only", "vector_only", "scalar_modifier", "vector_modifier", "spaced",
         "input_only", "late", "discarded", "options", "separate", "instruction", "file", "escape", "raw", "global")
def run(role):
    root = rt.LOG / ("direct-" + role)
    work = rt.ROOT / ("direct-" + role)
    work.mkdir()
    env = rt.environment()
    src = work / "gnu_aarch64.rs"
    shutil.copyfile(HERE / src.name, src)
    (work / "payload.bin").write_bytes(b"\0"*4)
    cmd = ["rustc", "+ohm", src.name, "--crate-type=rlib", "--target", rt.TARGET,
           "-Zohm-check-relink-inputs", "--emit=link,dep-info=-"]
    result = {}
    for cfg in PRIOR + NEW:
        p = rt.record([*cmd, "--cfg", cfg], root / cfg, work, env)
        got = [MISSING in p.stdout, RECHECK in p.stdout]
        allowed = (role != "unextended276" and cfg in PRIOR[:3]) or (role == "extended" and cfg == "compact_input")
        need(got == [not allowed, allowed], f"unexpected {role}/{cfg}: {got}")
        result[cfg] = [*got, digest(p.stdout), sha(work / "libgnu_aarch64.rlib")]
    (work / "payload.bin").unlink()
    for cfg in ("file", "escape", "compact_file"):
        (work / "libgnu_aarch64.rlib").unlink(missing_ok=True)
        rc = rt.record([*cmd,"--cfg",cfg],root/("missing-"+cfg),work,env,1)
        need(b"payload.bin" in rc.stderr and not (work/"libgnu_aarch64.rlib").exists(), "missing true codegen input was accepted")
    save(root/"complete.json", {"expected_old_hard":role != "extended","source":sha(src),"actual":result,
                                "candidate_native":sha(rt.SDK/"bin/rustc"),"missing":["file","escape","compact_file"]})
if __name__=="__main__":
    role,=sys.argv[1:]
    need(role in ("base","extended","unextended276"),"bad role")
    run(role)
