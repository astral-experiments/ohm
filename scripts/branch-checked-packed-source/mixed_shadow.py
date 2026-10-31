"""Carry an actual old writer's B into the independently selected native reader at one cache path."""

from objects import digest, dump, escrow, file_sha, need, unpack
from physical import observe
import subprocess

MODES = ("honest", "identical", "conflict", "corrupt")


def trial(root, report, env, sdk, driver, activate, ids, consumer):
    report.mkdir()
    work = root / ("shadow-work-" + consumer)
    work.mkdir()
    src = work / "checkout/main.rs"
    (src.parent / ".git").mkdir(parents=True)
    program = work / "program"
    cache = work / "incremental"
    env = env | {"CARGO_MANIFEST_DIR": str(src.parent)}

    def switch(branch, v):
        (src.parent / ".git/HEAD").write_text("ref: refs/heads/" + branch + "\n")
        code = "#![allow(dead_code)]\n" + "".join(
            f"pub fn f{i}(x: u32) -> u32 {{ x.wrapping_add({i}) }}\n" for i in range(384)
        )
        code += f'static DATA: [u8; 32768] = [{v}; 32768];\nfn main() {{ println!("{{}}", f0(std::hint::black_box(&DATA)[0].into())); }}\n'
        src.write_text(code)

    def visit(label, role):
        activate(role)
        args = [
            "rustc",
            "+ohm",
            "checkout/main.rs",
            "--crate-name",
            "branch_tables",
            "-Zohm-check-relink-inputs",
            "-Zohm-shared-stages",
            "-C",
            "incremental=" + str(cache),
            "-C",
            "codegen-units=1",
            "-o",
            "program",
            "-Zohm-branch-cache=yes",
        ]
        program.unlink(missing_ok=True)
        result = observe(args, work, env, report, label, sdk / driver, ids[role]["source"])
        (report / (label + ".stderr")).write_bytes(result.stderr)
        need(result.returncode == 0, result.stderr[-2000:])
        runtime = subprocess.run([program], cwd=work, env=env, capture_output=True, timeout=10)
        (report / (label + ".runtime")).write_bytes(runtime.stdout)
        need(runtime.returncode == 0 and not runtime.stderr, "unexpected native ELF exit")
        h = escrow(report / "elf", file_sha(program), program.read_bytes())
        row = {
            "role": role,
            **ids[role],
            "source_body": file_sha(src),
            "elf": h,
            "output": int(runtime.stdout),
        }
        dump(report / (label + ".json"), row)
        return row

    switch("b", 29)
    ref = visit("empty-B", consumer)
    need(ref["output"] == 29, "independent B must print 29")
    cache.rename(work / "empty")
    out = {}
    for mode in MODES:
        switch("a", 17)
        a = visit(mode + "-old-A", "old")
        (aa,) = [p for p in cache.glob("*/*") if p.is_dir()]
        switch("b", 29)
        b = visit(mode + "-old-B", "old")
        (side,) = cache.glob("*/*/ohm-packed-object-*")
        obj, body = unpack(side.read_bytes(), side.name, side.parent.name)
        other = (aa / obj).read_bytes()
        need(
            a["output"] == 17
            and b["elf"] == ref["elf"]
            and b["source_body"] == ref["source_body"]
            and len(other) == len(body)
            and b"\x11" * 8192 in other
            and b"\x1d" * 8192 in body
            and other != body
            and not (side.parent / obj).exists(),
            "unmatched normal old A and B objects",
        )
        sc = side.read_bytes()
        for name, data in (("side", sc), ("A", other), ("B", body)):
            escrow(report / "inputs", mode + "-" + name, data)
        if mode in {"identical", "conflict"}:
            (side.parent / obj).write_bytes(body if mode == "identical" else other)
        if mode == "corrupt":
            side.write_bytes(b"invalid object stream")
        mark = side.parent / "bad-object-sentinel"
        mark.write_text("discard")
        switch("a", 17)
        ret_a = visit(mode + "-return-A", "old")
        need(ret_a["elf"] == a["elf"], "A return changed")
        switch("b", 29)
        returned = visit(mode + "-read-B", consumer)
        markers = [p for p in cache.glob("*/*/bad-object-sentinel")]
        stale = consumer == "old" and mode == "conflict"
        expected = a if stale else ref
        kept = mode == "honest" or (consumer == "old" and mode in {"identical", "conflict"})
        need(
            returned["elf"] == expected["elf"]
            and returned["output"] == expected["output"]
            and bool(markers) == kept
            and len(markers) <= 1
            and returned["source_body"] == ref["source_body"],
            "foreign fallback, result or discarded marker in " + mode,
        )
        out[mode] = {
            "A": a["elf"],
            "B": b["elf"],
            "returned": returned["elf"],
            "output": returned["output"],
            "marker": kept,
            "packed": side.name,
            "session": side.parent.name,
            "raw_A": digest(other),
            "raw_B": digest(body),
            "sidecar": digest(sc),
        }
        cache.rename(work / ("closed-" + mode))
    dump(
        report / "complete.json",
        {"producer": "old", "consumer": consumer, "empty_B": ref["elf"], "cases": out},
    )
