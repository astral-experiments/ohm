from study import need,digest
import struct,re
PANICS = {"token::tokens::tests::" + name for name in (
    "tokens_after_offset_inside_token", "tokens_before_offset_inside_token",
    "tokens_in_range_start_offset_inside_token", "tokens_in_range_end_offset_inside_token",
    "tokens_split_at_inside_token", "tokens_split_at_matches_before_and_after_zero_length",
)}

def macho_text(path):
    """Read the executable instructions separately from the native UUID, signatures and debug tables."""
    data = path.read_bytes()
    need(data[:8] == bytes.fromhex("cffaedfe0c000001") and struct.unpack_from("<I", data, 12)[0] == 2, "not ARM64 MH_EXECUTE")
    count, size = struct.unpack_from("<II", data, 16)
    pos = 32
    result = []
    for _ in range(count):
        cmd, end = struct.unpack_from("<II", data, pos)
        need(end >= 8 and pos + end <= 32 + size <= len(data), "corrupt Mach-O command")
        if cmd == 0x19:
            nsects = struct.unpack_from("<I", data, pos + 64)[0]
            need(72 + 80 * nsects <= end, "bad segment size")
            for i in range(nsects):
                s = pos + 72 + 80 * i
                names = [data[j:j+16].rstrip(b"\0") for j in (s, s + 16)]
                if names == [b"__text", b"__TEXT"]:
                    length, offset = struct.unpack_from("<QI", data, s + 40)
                    need(length and offset + length <= len(data), "bad executable section")
                    result.append([length, digest(data[offset:offset + length])])
        pos += end
    need(pos == size + 32 and len(result) == 1, "missing text section")
    return {"raw": digest(data), "text": result[0]}

def suite_verdicts(whole, names):
    records = []
    for line in whole.decode().splitlines():
        if not line.startswith("test ") or " ... " not in line:
            continue
        formatted, verdict = line.removeprefix("test ").rsplit(" ... ", 1)
        name = formatted.removesuffix(" - should panic")
        need((formatted != name) == (name in PANICS) and verdict == "ok", "unexpected libtest verdict: " + line)
        records.append([name, verdict])
    need(sorted(name for name, _ in records) == names, "full suite did not execute the exact inventory")
    need(PANICS <= set(names) and f"{len(names)} passed; 0 failed; 0 ignored".encode() in whole,
         "missing annotated case or wrong suite summary")
    return sorted(records)
