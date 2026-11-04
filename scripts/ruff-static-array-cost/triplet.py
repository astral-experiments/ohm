"""Typed census and prespecified comparisons for three real rustc programs on Ruff #29261."""
import hashlib
import os
from fractions import Fraction
from pathlib import Path
import re
import statistics
import struct
import stat

ARMS = ("F5", "C5", "C7")
MODES = ("check", "build")
FIELDS = ("target_rustc", "whole_edit", "empty_target_rustc", "cold", "empty", "unchanged")
PHF_HEADERS = ("pub static NAME2CODE_DISP: &[(u16, u16)] = &[", "pub static NAME2CODE_CODE: &[char] = &[")
PILOTS = {"H1": ["F5", "C5", "C7"], "H2": ["C7", "C5", "F5"]}
CONFIRM = {
    "B1": ["F5","C5","C7"], "B2": ["C5","C7","F5"], "B3": ["C7","F5","C5"],
    "B4": ["C7","C5","F5"], "B5": ["C5","F5","C7"], "B6": ["F5","C7","C5"],
}

def census(data):
    """Consume every emitted pair and Rust char in the two genuine hash tables."""
    text = data.decode()
    arrays = []
    for header in PHF_HEADERS:
        formats = (header, header.replace(": &[", ": &'static ["))
        if sum(text.count(form) for form in formats) != 1:
            raise ValueError("Missing or repeated generated array")
        found = next(form for form in formats if form in text)
        array = text.split(found, 1)[1].split("];", 1)
        if len(array) != 2:
            raise ValueError("Unterminated generated array")
        body = array[0].strip()
        if not body.endswith(","):
            raise ValueError("Unterminated generated literal list")
        arrays.append(body)
    pair = re.compile(r"\(\s*([0-9]+),\s*([0-9]+)\s*\)\s*,\s*")
    char = re.compile(r"'([^'\\\n\r]|\\(?:['\"\\nrt0]|x[0-9A-Fa-f]{2}|u\{[0-9A-Fa-f_]+\}))'\s*,\s*")
    answer = {}
    for name, body, pattern in zip(("u16_pairs","chars"), arrays, (pair,char)):
        digest = hashlib.sha256()
        offset = count = 0
        while offset < len(body):
            m = pattern.match(body, offset)
            if m is None:
                raise ValueError(f"Unsupported {name} token at {offset}")
            if name == "u16_pairs":
                words = [int(v) for v in m.groups()]
                if max(words) > 65535:
                    raise ValueError("u16 overflow")
                digest.update(struct.pack("<HH", *words))
            else:
                token = m[1]
                if len(token) == 1:
                    value = ord(token)
                elif token.startswith(r"\u{"):
                    value = int(token[3:-1].replace("_", ""), 16)
                elif token.startswith(r"\x"):
                    value = int(token[2:], 16)
                    if value > 127:
                        raise ValueError("Non-ASCII byte escape")
                else:
                    value = ord({"0":"\0", "r":"\r", "n":"\n", "t":"\t", "'":"'", '"':'"', "\\":"\\"}[token[1]])
                if value > 0x10ffff or 0xd800 <= value <= 0xdfff:
                    raise ValueError("Non-scalar Rust char")
                digest.update(struct.pack("<I", value))
            count += 1
            offset = m.end()
        if count < 1024:
            raise ValueError("Outside the compiler's bulk array size")
        answer[name] = {"rows": count, "little_endian_payload_sha256": digest.hexdigest()}
    return answer

def storage(roots):
    """Scan both delivered roots unmetered, charging each regular inode once."""
    found = {}
    for name, root in roots.items():
        assert root.is_dir()
        for folder, dirs, files in os.walk(root):
            dirs.sort()
            for file in sorted(files):
                p = Path(folder) / file
                s = p.lstat()
                if stat.S_ISREG(s.st_mode):
                    state = (s.st_size, s.st_blocks * 512)
                    key = (s.st_dev, s.st_ino)
                    row = found.setdefault(key, [*state, []])
                    assert tuple(row[:2]) == state
                    row[2].append(name + "/" + str(p.relative_to(root)))
    rows = [{"dev": key[0], "ino": key[1], "logical": v[0], "allocated": v[1], "paths": sorted(v[2])}
            for key,v in sorted(found.items())]
    return {"files": len(rows), "logical":sum(r["logical"] for r in rows),
            "allocated":sum(r["allocated"] for r in rows), "inodes":rows}

def judge(cohort):
    """Apply the frozen gates to already authenticated counter/storage originals."""
    phase = len(cohort)
    assert phase in (2, 6)
    wanted = PILOTS if phase == 2 else CONFIRM
    assert set(cohort) == set(wanted)
    assert all(row["order"] == wanted[block] for block,row in cohort.items())
    assert len({r["boot"] for r in cohort.values()}) == phase
    contrasts = {}
    vetoes = []
    for left,right in (("F5","C7"),("C5","C7"),("F5","C5")):
        comparison = {}
        for mode in MODES:
            for key in FIELDS:
                pairs = [(r["results"][left][mode][key], r["results"][right][mode][key])
                         for r in cohort.values()]
                assert all(a > 0 and b > 0 for a,b in pairs)
                changes = [(a-b)/a for a,b in pairs]
                comparison[f"{mode}/{key}"] = {"pairs":pairs, "min":min(changes),
                    "median":statistics.median(changes), "max":max(changes)}
                if right == "C7" and key in ("cold","unchanged") and all(
                        b-a > 10_000_000 and 20*(b-a) > a for a,b in pairs):
                    vetoes.append(f"{left}/{right} {mode}/{key} common-path regression")
        contrasts[f"{left}/{right}"] = comparison
    for mode in MODES:
        for stage in ("ordinary-edit","unchanged","empty-new"):
            for unit in ("logical","allocated"):
                for left in ("F5","C5"):
                    pairs = [(r["storage"][left][mode][stage][unit],r["storage"]["C7"][mode][stage][unit])
                             for r in cohort.values()]
                    if all(b-a > 1024*1024 and 100*(b-a) > 2*a for a,b in pairs):
                        vetoes.append(f"{left}/C7 {mode}/{stage}/{unit} storage regression")
    def reduced(key, num, denom):
        entry = contrasts[key]["check/target_rustc"]
        if phase == 2:
            return all(denom*(a-b) >= num*a for a,b in entry["pairs"])
        exact = [Fraction(a-b, a) for a,b in entry["pairs"]]
        return min(exact) > 0 and statistics.median(exact) >= Fraction(num, denom)
    whole_favorable = all(contrasts[c]["check/whole_edit"]["min"] > 0 for c in ("F5/C7","C5/C7"))
    material = (reduced("F5/C7",1,3) and reduced("C5/C7",1,10) and reduced("F5/C5",1,5)
                and whole_favorable and not vetoes)
    ratios = [f/c for f,c in contrasts["F5/C7"]["check/target_rustc"]["pairs"]]
    exact_two = all(f > 2*c for f,c in contrasts["F5/C7"]["check/target_rustc"]["pairs"])
    return {"phase":"pilot" if phase==2 else "confirmation", "contrasts":contrasts, "vetoes":vetoes,
            "whole_check_both_favorable":whole_favorable, "admit_six":phase==2 and material,
            "confirmed_material":phase==6 and material, "all_cumulative_strictly_over_two":exact_two,
            "confirmed_twofold":phase==6 and material and exact_two,
            "twofold_exact_two_sided_sign_p":2/64 if phase==6 and exact_two else None,
            "cumulative_ratio_min_median_max":[min(ratios),statistics.median(ratios),max(ratios)]}
