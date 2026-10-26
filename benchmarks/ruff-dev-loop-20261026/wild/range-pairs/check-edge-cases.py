"""Compare every byte of representative and malformed ELF links to the released Wild recipe."""

import argparse, hashlib, json, os, struct, subprocess
from pathlib import Path


def fields(data):
    (off,) = struct.unpack_from("<Q", data, 40)
    sz, n, st = struct.unpack_from("<HHH", data, 58)
    sections = [struct.unpack_from("<IIQQQQIIQQ", data, off + i * sz) for i in range(n)]
    names = sections[st][4]
    return {
        data[names + x[0] : data.index(b"\0", names + x[0])].decode(): x
        for x in sections
    }


def run():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("control", type=Path)
    p.add_argument("candidate", type=Path)
    p.add_argument("out", type=Path)
    a = p.parse_args()
    a.out.mkdir(parents=True)
    a.out = a.out.resolve()
    control = a.control.resolve()
    candidate = a.candidate.resolve()
    os.chdir(a.out)
    base = """.section .text.start,"ax",@progbits
.global _start
_start: call live_fn; mov $60, %eax; xor %edi,%edi; syscall
.section .text.live,"ax",@progbits
.global live_fn
live_fn: .fill 12,1,0x90; ret
.section .text.dead,"ax",@progbits
unused: .fill 12,1,0x90; ret
"""
    pair = """.quad .text.live, .text.live+12
.quad .text.dead, .text.dead+12
"""
    cases = {
        "normal": pair,
        "mixed_named": pair + ".quad live_fn, live_fn+1\n",
        "overlapping": pair + ".reloc 8, R_X86_64_64, live_fn+5\n",
        "mixed_width": pair + ".long .text.live+2, .text.live+5\n",
        "unpaired": pair + ".quad .text.live+1\n",
        "different_symbols": pair + ".quad .text.live, .text.dead+6\n",
    }
    results = []
    for name, values in cases.items():
        text = (
            base
            + '.section .debug_ranges,"",@progbits\n'
            + values
            + '\n.section .debug_loc,"",@progbits\n'
            + values
            + '\n.section .note.GNU-stack,"",@progbits\n'
        )
        asm = Path(name + ".s")
        obj = Path(name + ".o")
        asm.write_text(text)
        subprocess.run(["as", "--64", "-o", obj, asm], check=True)
        for tag, options in [
            ("gc", ["--gc-sections"]),
            ("all", ["--no-gc-sections"]),
            ("relocatable", ["-r"]),
            ("compressed", ["--gc-sections", "--compress-debug-sections=zlib"]),
        ]:
            output = Path(name + "-" + tag + ".elf")
            hashes = []
            for arm in [control, candidate]:
                cmd = [arm, "--no-fork", "--threads=1", *options, "-o", output, obj]
                p = subprocess.run(cmd, capture_output=True)
                assert p.returncode == 0, (p.args, p.stderr)
                data = output.read_bytes()
                hashes.append(hashlib.sha256(data).hexdigest())
                if name == "normal" and tag in ["gc", "all"]:
                    h = fields(data)
                    for s in [".debug_ranges", ".debug_loc"]:
                        section = h[s]
                        lower, upper, dead_low, dead_high = struct.unpack_from(
                            "<QQQQ", data, section[4]
                        )
                        assert lower and upper - lower == 12
                        if tag == "gc":
                            assert (dead_low, dead_high) == (1, 1), (
                                name,
                                s,
                                dead_low,
                                dead_high,
                            )
                        else:
                            assert dead_low and dead_high - dead_low == 12
            assert hashes[0] == hashes[1], (name, tag, hashes)
            results.append({"case": name + "-" + tag, "sha256": hashes[0]})
    # Force a malformed offset in a late pair, after valid absolute writes in the same section.
    data = bytearray(Path("normal.o").read_bytes())
    h = fields(data)[".rela.debug_ranges"]
    struct.pack_into("<Q", data, h[4] + 2 * 24, 1 << 46)
    struct.pack_into("<Q", data, h[4] + 3 * 24, (1 << 46) + 8)
    obj = Path("bad.o")
    obj.write_bytes(data)
    exits = []
    for arm in [control, candidate]:
        proc = subprocess.run(
            [arm, "--no-fork", "--threads=1", "--gc-sections", "-o", "bad.elf", obj],
            capture_output=True,
        )
        exits.append(proc.returncode)
        assert proc.returncode != 0
        assert (
            "range" in proc.stderr.decode().lower()
            or "bounds" in proc.stderr.decode().lower()
        ), proc.stderr
    assert exits[0] == exits[1], exits
    results.append({"case": "malformed-offset", "exit": exits[0]})
    Path("results.json").write_text(json.dumps(results, indent=2) + "\n")
    print(len(results), "cases passed")


if __name__ == "__main__":
    run()
