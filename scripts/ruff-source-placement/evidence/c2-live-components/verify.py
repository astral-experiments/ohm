"""Verify every actual counter, continuous-live native wire and paired CGU without an SDK."""
import argparse
import hashlib
import json
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sha = lambda data: hashlib.sha256(data).hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


def read_archive(path):
    result = {}
    with tarfile.open(path, "r:gz") as archive:
        for member in archive:
            require(member.isfile() and member.name not in result and member.size < 24 << 20, "unexpected archive member")
            result[member.name] = archive.extractfile(member).read()
    return result


def verify(data_dir):
    checks = (data_dir / "SHA256SUMS").read_text().splitlines()
    for line in checks:
        digest, filename = line.split("  ", 1)
        require(Path(filename).name == filename and sha((data_dir / filename).read_bytes()) == digest, filename)
    data = json.loads((data_dir / "corpus.json").read_bytes())
    require(data["source_TU_SHA256"] == "ec8919787fde3c79f161bc93ac2daf766cf3573157dd00a171a05765d929eadd"
            and data["signed_LLVM_SHA256"] == "43bac9749e539cd5988a4d5452b64582cf07ac9e7c059fde29c7bee76e106c51"
            and data["signed_originals_zip"] == "53ede61bc14ac8e524813b6cac9d1cfbbcd595b5380fae363e681406aa7b404b", "different source, runtime or ordinary capture")
    cases = data["source_controls"]
    for name in ("definition-only", "definition-and-call"):
        p, c = cases[name]["16"], cases[name]["32"]
        require(p["key"] != c["key"] and p["native"] == 16 and c["native"] == 32, "observable allocation-size collision")
    require(all(v["native"] == (1 << 64) - 1 for v in cases["no-allocsize"].values()), "changed no-attribute semantic guard")
    loop = data["loop_metadata_controls"]
    require(all(loop[f"observable-loop-position-{i}"]["post"] is None for i in (5, 6))
            and loop["ordinary-loop-hint-5"]["post"] == loop["ordinary-loop-hint-6"]["post"] is not None,
            "unsupported loop-metadata position admitted or bare hint refused")
    packets = read_archive(data_dir / "observations.tar.gz")
    used = set()
    def opened(name):
        used.add(name)
        return packets[name]
    eligible = []
    per_lane = {"policy": {}, "parse": {}}
    for key, unit in sorted(data["CGUs"].items()):
        live = []
        reparse = []
        for role in ("old", "new"):
            row = unit[role]
            native = opened(f"wire/{role}/{key}.osp")
            require(native.startswith(b"OSP\x01") and native[36:].startswith(b"CGU-GLOBAL-LINES\x01"), key)
            require(len(native) == data["wire_lengths"][role][key] and sha(native) == row["live_wire_sha256"] and native[4:36].hex() == row["key"] and sha(native[36:]) == row["placements"], "incorrect live FFI wire")
            require(row["key"] != row["reparsed_key"], "live and reparsed producer confused")
            live.append(row["key"])
            reparse.append(row["reparsed_key"])
        equal = live[0] == live[1]
        require(equal == unit["equal"] == (reparse[0] == reparse[1]), "incorrect relational assertion")
        if equal:
            eligible.append(key)
    require(len(data["CGUs"]) == 21 and len(eligible) == 16, "wrong original CGUs or expected hits")
    totals = {}
    for mode, traces in data["profiles"].items():
        by_unit = per_lane[mode]
        primary = sorted(data["CGUs"])
        schedule = [(mode, unit) for unit in primary] + [(mode + "-repeat", primary[i]) for i in (20, 10, 0)]
        require([(t["cohort"], t["unit"]) for t in traces] == schedule, "different original or repeated score order")
        for row in traces:
            unit = row["unit"]
            key = f"trace/{row['cohort']}/{unit}.out"
            original = opened(key)
            require(sha(original) == row["portable_sha256"], "changed physical counter projection")
            lines = original.splitlines()
            require(lines.count(b"creator: callgrind-3.22.0") == lines.count(b"events: Ir") == 1, "different event")
            commands = [v[5:].split() for v in lines if v.startswith(b"cmd: ")]
            require(len(commands) == 1 and commands[0] == [v.encode() for v in row["subject"]], "different guest argv")
            endings = [int(v.split()[1]) for v in lines if v.startswith(b"totals: ")]
            require(endings == [row["count"]], "unverified instructions")
            expected = data["CGUs"][unit]["new"]
            require(row["output_key"] == expected["key" if mode == "policy" else "reparsed_key"]
                    and row["input_sha"] == expected["input" if mode == "policy" else "O1"], "wrong physical source or key")
            if row["cohort"] == mode:
                by_unit[unit] = row
            else:
                original_row = by_unit[unit]
                require(row["subject"] == original_row["subject"] and row["count"] == original_row["count"], "reverse repetition differs")
        totals[mode] = sum(o["count"] for o in by_unit.values())
    require(set(packets) == used and len(used) == 42 + 48, "unread or absent physical evidence")
    require(sum(data["policy_components"].values()) == totals["policy"], "overlap in producer cost")
    machine = sum(data["CGUs"][k]["machine_only_Ir"] for k in eligible)
    full = sum(v["entire_backend_Ir"] for v in data["CGUs"].values())
    residual = full - machine + totals["policy"] + data["native_product_Ir"]
    require([totals["policy"], totals["parse"], machine, full, residual] == [8909198327, 3109017091, 60436240766, 120906271208, 69753154409], "incorrect endpoint")
    print(f"16/21 matches; 42 live wires, 48 original profiles. Live collector {totals['policy']:,} Ir; separate parser {totals['parse']:,} Ir. Projected backend {full/residual:.6f}x.")


if __name__ == "__main__":
    cli = argparse.ArgumentParser()
    cli.add_argument("--directory", type=Path, default=HERE)
    verify(cli.parse_args().directory)
