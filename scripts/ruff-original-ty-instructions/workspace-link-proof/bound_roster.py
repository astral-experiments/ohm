"""Join the actual in-order per-request search decisions and the typed, loaded input-array."""

import hashlib
import json
from pathlib import Path
import re
import stat


def grammar(a, spec):
    if len(a) != len(spec["grammar"]):
        return False
    for slot, (v, t) in enumerate(zip(a, spec["grammar"])):
        if not v.isascii() or any(c.isspace() or c in ("@", "\0", "?") for c in v):
            return False
        if t == "<static-gnu-wild>":
            good = v.endswith(
                "/lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"
            )
        elif t == "<unused-gcc-lto-resolution>":
            good = re.fullmatch(r"-plugin-opt=-fresolution=/tmp/cc[A-Za-z0-9]+\.res", v)
        elif t == "<registered-output>":
            good = v.endswith(spec["suffix"])
        elif t == "<library-search-dir>":
            good = v.startswith("-L/")
        elif t.startswith("<input:"):
            good = v.startswith("/") and v.endswith(t[len("<input:") : -1])
        else:
            good = v == t
        if not good:
            return False
    return True


def opt(s):
    return None if s == "None" else json.loads(re.fullmatch(r"Some\((.*)\)", s)[1])


def receive(data, spec, *, need_new=True):
    groups = {}
    live = {}
    requests = []
    opened = {}
    unclaimed = []
    bad = []
    for line in data.splitlines():
        f = line.split("\t")
        if f[0] != "OHMLOOK":
            groups.setdefault(f[0], []).append(f[1:])
            continue
        k, pid, tid = f[1:4]
        v = f[4:]
        key = (pid, tid)
        if k == "B":
            m = re.fullmatch(r"(File|Lib|Search|Framework)\((.*)\)", v[0])
            assert m and key not in live
            r = {
                "type": m[1],
                "value": json.loads(m[2]),
                "parent": opt(v[1]),
                "first": opt(v[2]),
                "modifiers": v[3],
                "position": int(v[4]),
                "probes": [],
            }
            live[key] = r
            requests.append(r)
        elif k == "A":
            raise ValueError("auxiliary path outside the enrolled link")
        elif k == "P":
            path, err, mode = json.loads(v[0]), int(v[1]), int(v[2])
            assert err >= 0 and (
                (err == 0 and stat.S_ISREG(mode)) or (err > 0 and mode == 0)
            )
            (live[key]["probes"] if key in live else unclaimed).append(
                [path, err, mode]
            )
        elif k == "E":
            r = live.pop(key)
            r["selected"] = opt(v[0])
        elif k == "O":
            path = json.loads(v[0])
            assert path not in opened
            opened[path] = tuple(map(int, v[1:]))
        elif k == "X":
            bad.append(v)
        else:
            raise AssertionError(k)
    assert not live and not bad and not groups.get("WARNING")
    args = [json.loads(x) for i, x in groups["ARG"]]
    assert [int(i) for i, _ in groups["ARG"]] == list(range(spec["argc"]))
    symbol = spec["symbols_position"]
    count = spec["direct_requests"]
    assert grammar(args, spec)
    assert (
        len(args) == spec["argc"]
        and args[5] == "--build-id"
        and args[18] == "-o"
        and args[23].startswith("-L")
        and args[symbol].endswith("/symbols.o")
    )
    target = args[19]
    tmp = str(Path(args[symbol]).parent)
    assert (
        Path(tmp).parent == Path(target).parent
        and re.fullmatch(r"rustc[0-9A-Za-z]{6}", Path(tmp).name)
        and args[23] == "-L" + tmp + "/raw-dylibs"
        and re.fullmatch(r"-plugin-opt=-fresolution=/tmp/cc[A-Za-z0-9]+\.res", args[4])
    )

    def normalize(v):
        if v is None:
            return None
        if v == tmp:
            return "<rustc-input-root>"
        if v.startswith(tmp + "/"):
            return "<rustc-input-root>/" + v[len(tmp) + 1 :]
        return v

    all_frozen = {
        r[-1]: (int(r[0]), int(r[1]), int(r[2]), r[3]) for r in groups["FROZEN"]
    }
    assert len(all_frozen) == len(groups["FROZEN"]) == len(opened) == len(
        groups["USED"]
    ) == count + 7 and set(opened) == set(all_frozen)
    assert len(opened) == len(requests) and {r["selected"] for r in requests} == set(
        opened
    )
    assert all(r["parent"] is None or r["parent"] in opened for r in requests)
    used = []
    for i, r in enumerate(groups["USED"]):
        pos, num, hash_, mods, path = r
        assert (
            int(pos) == i
            and opened[path] == all_frozen[path][:3]
            and (int(num), hash_) == all_frozen[path][2:]
        )
        used.append([normalize(path), int(num), hash_, mods])
    good_args = args.copy()
    good_args[4] = "-plugin-opt=-fresolution=<unused-native-plugin-option>"
    good_args[23] = "-L<rustc-input-root>/raw-dylibs"
    good_args[symbol] = "<rustc-input-root>/symbols.o"
    for r in requests:
        for field in ("value", "parent", "first", "selected"):
            r[field] = normalize(r[field])
        r["probes"] = [[normalize(p), e, m] for p, e, m in r["probes"]]
    positions = [(r["parent"] or "", r["position"]) for r in requests]
    assert len(set(positions)) == len(positions) == count + 7
    assert len(unclaimed) == 1 and unclaimed[0][0] == target
    assert sorted(r["position"] for r in requests if r["parent"] is None) == list(
        range(count)
    )
    sorted_requests = sorted(requests, key=lambda r: (r["parent"] or "", r["position"]))
    digest = lambda x: hashlib.sha256(
        json.dumps(x, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    context = {
        k: groups.get(k, [])
        for k in ("CWD", "TYPED", "ADMISSION", "ENVKEY", "DOMAINS", "GROUPINPUT")
    }
    if need_new:
        assert (
            len(context["CWD"])
            == len(context["TYPED"])
            == len(context["ADMISSION"])
            == 1
        )
        assert sorted(x[0] for x in context["ENVKEY"]) == sorted(
            x[0] for x in groups["ENV"]
        )
    else:
        context = {"CWD": groups["CWD"]}
    top = sorted(
        (r for r in requests if r["parent"] is None), key=lambda r: r["position"]
    )
    direct = [
        ("Lib", a[2:]) if a.startswith("-l") else ("File", normalize(a))
        for i, a in enumerate(args)
        if i in spec["regular_positions"] or a.startswith("-l")
    ]
    assert [(r["type"], r["value"]) for r in top] == direct
    parts = {
        "argv": good_args,
        "requests": sorted_requests,
        "native_inputs": used,
        "unclaimed_probes": unclaimed,
        "context": context,
    }
    ids = {k: digest(x) for k, x in parts.items()}
    return {
        "key": digest(ids),
        "parts": ids,
        "inputs": len(used),
        "bytes": sum(u[1] for u in used),
        "requests": len(requests),
        "denied_lookups": sum(e != 0 for r in requests for _, e, _ in r["probes"]),
        "context": context,
    }, args
