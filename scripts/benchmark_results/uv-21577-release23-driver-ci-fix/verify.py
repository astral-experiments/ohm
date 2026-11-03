#!/usr/bin/env python3
"""Offline source, ELF, relocation, bitcode and metadata checks. No Git checkout required."""

import argparse, ctypes, hashlib, json, os, re, struct, subprocess, tarfile, tempfile
from pathlib import Path

D = Path(__file__).resolve().parent
P = "9b63803c29b00106e2eeb544b2387a6e8a8cba1f"
C = "a325fe305ae1d6f037ffc0223036b89228bbd6e6"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git_blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def need(ok, why):
    if not ok:
        raise ValueError(why)


def parse_elf(data):
    need(
        data[:6] == b"\x7fELF\x02\x01"
        and struct.unpack_from("<HH", data, 16) == (1, 62),
        "expected little-endian x86-64 relocatable ELF",
    )
    off = struct.unpack_from("<Q", data, 40)[0]
    size, n, strings = struct.unpack_from("<HHH", data, 58)
    need(size == 64 and 0 < strings < n, "bad section table")
    sections = [
        struct.unpack_from("<IIQQQQIIQQ", data, off + i * size) for i in range(n)
    ]

    def content(s):
        return data[s[4] : s[4] + s[5]]

    def st(table, index):
        return table[index : table.index(b"\0", index)].decode()

    names = content(sections[strings])
    named = [st(names, s[0]) for s in sections]
    sym = next(s for s in sections if s[1] == 2)
    symbols = []
    symbol_names = content(sections[sym[6]])
    for i in range(0, sym[5], sym[9]):
        name, info, other, idx, value, sz = struct.unpack_from(
            "<IBBHQQ", data, sym[4] + i
        )
        symbols.append((st(symbol_names, name), idx, value, sz))
    rel = []
    for number, s in enumerate(sections):
        if s[1] in (4, 9):
            for i in range(0, s[5], s[9]):
                _, info = struct.unpack_from("<QQ", data, s[4] + i)
                rel.append((named[s[7]], symbols[info >> 32][0]))
    code = {
        named[i]: content(s) for i, s in enumerate(sections) if s[1] == 1 and s[2] & 4
    }
    return code, symbols, rel, n, sum(s[1] in (4, 9) for s in sections)


def llvm_ir(libpath, raw):
    lib = ctypes.CDLL(str(libpath))
    P = ctypes.c_void_p
    S = ctypes.c_char_p

    def f(n, r, *t):
        fn = getattr(lib, n)
        fn.restype = r
        fn.argtypes = t
        return fn

    ctx = f("LLVMContextCreate", P)()
    buf = f("LLVMCreateMemoryBufferWithMemoryRangeCopy", P, S, ctypes.c_size_t, S)(
        raw, len(raw), b"owning-module"
    )
    module = P()
    need(
        f("LLVMParseBitcodeInContext2", ctypes.c_int, P, P, ctypes.POINTER(P))(
            ctx, buf, ctypes.byref(module)
        )
        == 0,
        "invalid LLVM bitcode",
    )
    msg = f("LLVMPrintModuleToString", P, P)(module)
    try:
        return ctypes.string_at(msg)
    finally:
        f("LLVMDisposeMessage", None, P)(msg)
        f("LLVMDisposeModule", None, P)(module)
        f("LLVMDisposeMemoryBuffer", None, P)(buf)
        f("LLVMContextDispose", None, P)(ctx)


def run(args):
    m = json.loads((D / "manifest.json").read_bytes())
    data = {}
    need(
        m["hardware_only_on_source"] == P and m["source"]["child"]["commit"] == C,
        "source lineage",
    )
    for archive in m["archives"]:
        fn = D / archive["archive"]
        need(
            fn.stat().st_size == archive["compressed_bytes"]
            and digest(fn.read_bytes()) == archive["sha256"],
            "archive identity " + fn.name,
        )
        with tarfile.open(fn, "r:xz") as tar:
            for e in tar:
                need(
                    e.isreg() and e.name in m["members"] and e.name not in data,
                    "unexpected member",
                )
                r = tar.extractfile(e).read()
                need(
                    m["members"][e.name] == {"bytes": len(r), "sha256": digest(r)},
                    "member " + e.name,
                )
                data[e.name] = r
    need(set(data) == set(m["members"]), "incomplete")
    for k in ("parent", "child"):
        need(git_blob(data[k + ".rs"]) == m["source"][k]["git_blob"], "actual Git blob")
    a = b"    if let Some(path) = &target {"
    b = b"                && let Ok(receipt) = path\n"
    before = data["parent.rs"]
    need(before.count(a) == before.count(b) == 1, "ambiguous source")
    need(
        before.replace(a, a.replace(b"(path)", b"(_path)")).replace(
            b, b.replace(b"= path", b"= _path")
        )
        == data["child.rs"],
        "more than two tokens",
    )
    need(
        data["parent.o"] == data["child.o"]
        and digest(data["parent.o"])
        == m["linux"]["case"]["products"]["parent"]["sha256"],
        "native objects differ",
    )
    ec, syms, rel, sc, rc = parse_elf(data["parent.o"])
    mc, ms, mr, _, _ = parse_elf(data["swapped.o"])
    diff = [s for s in ec if ec[s] != mc[s]]
    expected = m["linux"]["sensitivity"]["different_executable_sections"]
    need(
        set(ec) == set(mc)
        and len(diff) == len(expected) == 1
        and diff[0] == expected[0]["section"],
        "negative control",
    )
    sym = diff[0].removeprefix(".text.")
    need(any(x[0] == sym and x[3] == len(ec[diff[0]]) for x in syms), "owning symbol")
    need(
        digest(ec[diff[0]]) == expected[0]["original"]
        and digest(mc[diff[0]]) == expected[0]["mutated"],
        "wrong negative body",
    )
    need(
        (sc, rc, sum(map(len, ec.values()))) == (9114, 3375, 1371710),
        "wrong native geometry",
    )
    for label in ("parent", "child"):
        _, names, fixups, *_ = parse_elf(data[label + "-caller.o"])
        need(
            any(n[0] == sym and n[1] == 0 for n in names)
            and any(
                s == ".text.downstream_constructor" and n == sym for s, n in fixups
            ),
            "external caller missing an actual relocation",
        )
        need(
            digest(data[label + "-caller.o"])
            == m["consumer"]["observations"][label]["object_sha256"],
            "external witness",
        )
    need(
        data["parent-caller.o"] == data["child-caller.o"]
        and data["parent-caller.ll"] == data["child-caller.ll"],
        "external fixed-input mismatch",
    )
    for ext, key in [("bc", "llvm_bitcode"), ("rmeta", "rust_metadata")]:
        a, b = (data[k + "." + ext] for k in ("parent", "child"))
        need(len(a) == len(b), "length mismatch")
        amount = sum(x != y for x, y in zip(a, b))
        need(amount == m["llvm"]["physical_differing_bytes"][key], "byte disagreement")
    if args.llvm:
        dump = {}
        for k in ("parent", "child"):
            ir = llvm_ir(args.llvm, data[k + ".bc"])
            need(
                digest(ir) == m["llvm"]["ir"][k + "_sha256"],
                "LLVM module rendering drift; use the producing LLVM 22.1",
            )
            dump[k] = ir.splitlines(keepends=True)
        changed = [
            (n, x, y)
            for n, (x, y) in enumerate(zip(dump["parent"], dump["child"]), 1)
            if x != y
        ]
        need(
            len(changed) == 2 and len(dump["parent"]) == len(dump["child"]) == 559800,
            "extra IR differences",
        )
        for k in dump:
            rows = m["llvm"]["srcloc"][k]["rows"]
            defs = {r["definition"].encode(): r for r in rows if "definition" in r}
            for r in rows:
                need(
                    dump[k][r["line"] - 1].strip().decode() == r["text"],
                    "IR source-location evidence",
                )
            needles = list(defs)
            count = 0
            normalized = []
            for line in dump[k]:
                if any(line.startswith(i + b" = ") for i in needles):
                    normalized.append(line.split(b" = ", 1)[0] + b" = <position>\n")
                else:
                    for node in needles:
                        if re.search(re.escape(node) + rb"(?![0-9])", line):
                            need(
                                b"!srcloc " + node in line and b"asm " in line,
                                "metadata used beyond inline assembly srcloc",
                            )
                            count += 1
                    normalized.append(line)
            need(
                count == 8
                and digest(b"".join(normalized))
                == m["llvm"]["srcloc"][k]["all_ir_except_two_srcloc_payloads_sha256"],
                "full IR normalization",
            )
    if args.stage0:
        env = os.environ | {"RUSTC_BOOTSTRAP": "1"}
        need(
            digest(args.stage0.read_bytes())
            == m["compilation"]["stage0_launcher_sha256"],
            "wrong stage0",
        )
        with tempfile.TemporaryDirectory() as scratch:
            t = Path(scratch)
            f = t / "librustc_codegen_ssa.rmeta"
            for k in ("parent", "child"):
                f.write_bytes(data[k + ".rmeta"])
                r = subprocess.check_output([args.stage0, "-Zls=root", f], env=env)
                need(
                    digest(r) == m["metadata_root"][k]["sha256"],
                    "physical metadata header",
                )
            for k, q in m["target_probe"].items():
                f = t / "probe.rs"
                f.write_text(q["source"])
                for row in q["target_results"]:
                    res = subprocess.run(
                        [
                            args.stage0,
                            "--crate-name",
                            "ohm_cfg_351",
                            "--edition=2024",
                            "--crate-type=lib",
                            "--target=" + row["target"],
                            "--emit=metadata",
                            "-o",
                            t / "probe.rmeta",
                            f,
                        ],
                        env=env,
                        capture_output=True,
                    )
                    need(
                        res.returncode == row["returncode"]
                        and (b"unused variable: `path`" in res.stderr)
                        == (res.returncode != 0),
                        "target-specific unused variable",
                    )
    print(
        f"Verified 3 native objects, {sc:,} sections, {rc:,} relocation sections, 2 caller objects, 2 bitcode and 2 rmeta inputs."
    )
    print(
        "Only the device/inode mutant changes the native CrateInfo::new section (26,887 bytes)."
    )
    print(
        "Binary bitcode differs at 38 bytes and rmeta at 365 bytes. Hardware source 9b63803c. Follow-up source a325fe30."
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--llvm",
        type=Path,
        help="decode and compare all bitcode with the producing LLVM 22.1 shared library",
    )
    ap.add_argument(
        "--stage0",
        type=Path,
        help="reread metadata and repeat the six target-specific diagnostics with the original bootstrap rustc",
    )
    run(ap.parse_args())
