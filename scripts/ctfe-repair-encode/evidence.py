"""Distinguish a completed pair from a failed first create and from untouched donor reads."""

import hashlib
import os
import re
import stat
import subprocess
import zlib
from pathlib import Path

DRIVER = "lib/librustc_driver-c5276fb6f0cdddb4.so"
WILD = "lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"
FILES = ("ohm-packed-dep-graph.bin", "ohm-packed-query-cache.bin")
RAWS = ("dep-graph.bin", "query-cache.bin")


def need(value, problem):
    if not value:
        raise ValueError(str(problem))


def sha(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def ident(p):
    t = p.lstat()
    need(stat.S_ISREG(t.st_mode), ("nonregular", p))
    return dict(
        dev=t.st_dev, ino=t.st_ino, links=t.st_nlink, bytes=t.st_size, blocks=t.st_blocks * 512, sha256=sha(p)
    )


def sessions(work, selectors):
    owners = {}
    result = {}
    for base in (work / "target", work / "build"):
        for parent, dirs, files in os.walk(base, followlinks=False):
            here = Path(parent)
            if here.name not in selectors or "incremental" not in here.parts:
                continue
            need(
                here.is_dir() and here.resolve() == here and here.name not in owners,
                ("ambiguous physical owner", here),
            )
            owners[here.name] = str(here)
            rows = {}
            for name in dirs:
                if not name.startswith("s-") or name.endswith("-working"):
                    continue
                path = here / name
                rows[name] = {t: ident(path / t) for t in (*FILES, *RAWS) if (path / t).is_file()}
            result[here.name] = rows
            dirs.clear()
    need(set(owners) == set(selectors), ("missing physical owners", set(selectors) - set(owners)))
    return dict(owners=owners, sessions=result)


def unpack(p, limit):
    need(p.is_file() and not p.is_symlink() and p.stat().st_size < limit, "invalid compact object")
    d = zlib.decompressobj()
    raw = d.decompress(p.read_bytes(), limit + 1)
    need(
        len(raw) <= limit and d.eof and not d.unconsumed_tail and not d.unused_data, "invalid compressed member"
    )
    return raw


def table(dir, i, packed):
    if not packed:
        raw = ident(dir / RAWS[i])
        aliases = sum(
            1 << index
            for index, name in enumerate((RAWS[i], "ohm-build-" + RAWS[i], "ohm-check-" + RAWS[i]))
            if (dir / name).is_file() and os.path.samefile(dir / name, dir / RAWS[i])
        )
        need(raw["links"] >= aliases.bit_count(), "invalid alias count")
        with (dir / RAWS[i]).open("rb") as f:
            need(f.read(4) == b"RSIC", "invalid raw table")
        return {"raw": raw, "body_sha256": raw["sha256"], "body_bytes": raw["bytes"], "aliases": aliases}
    p = dir / FILES[i]
    raw = unpack(p, (512 << 20) + 4096)
    prefix = dir.name.rsplit("-", 1)[0].encode() + b"\0"
    need(
        raw[:2] == bytes((1, b"GQ"[i])) and raw[2] in (1, 3, 5, 7) and raw.startswith(prefix, 11),
        "wrong table header",
    )
    length = int.from_bytes(raw[3:11], "little")
    off = 11 + len(prefix)
    need(len(raw) - off == length and raw[off : off + 4] == b"RSIC", "wrong table body")
    return {
        "packed": ident(p),
        "body_bytes": length,
        "aliases": raw[2],
        "body_sha256": hashlib.sha256(memoryview(raw)[off:]).hexdigest(),
    }


def valid_object(head):
    return (
        len(head) >= 18
        and head[:4] == b"\x7fELF"
        and head[4] in (1, 2)
        and head[6] == 1
        and (head[5], bytes(head[16:18])) in ((1, b"\x01\x00"), (2, b"\x00\x01"))
    )


def objects(directory):
    result = {}
    for p in directory.iterdir():
        if p.name.startswith("ohm-packed-object-"):
            name, _, h = p.name.removeprefix("ohm-packed-object-").partition("-")
            need(
                re.fullmatch(r"[a-z0-9]{1,32}\.o", name) and re.fullmatch(r"blake3=[a-f0-9]{64}", h),
                "invalid packed object name",
            )
            data = unpack(p, (512 << 20) + 4096)
            prefix = b"OHMO1" + directory.name.rsplit("-", 1)[0].encode() + b"\0" + name.encode() + b"\0"
            need(data.startswith(prefix), "packed object belongs to different session")
            off = len(prefix) + 8
            raw = memoryview(data)[off:]
            need(
                len(raw) == int.from_bytes(data[off - 8 : off], "little") and valid_object(raw),
                "invalid packed object bytes",
            )
            b3 = os.environ.get("QA_EVIDENCE_B3SUM", "b3sum")
            check = subprocess.run([b3, "--no-names"], input=raw, stdout=subprocess.PIPE, check=True)
            need(
                "blake3=" + check.stdout.decode().strip() == h,
                "wrong authenticated BLAKE3 in packed object name",
            )
            desc = dict(
                file=p.name,
                stat=ident(p),
                packed=True,
                digest=hashlib.sha256(raw).hexdigest(),
                bytes=len(raw),
                stored=p.stat().st_size,
                blocks=512 * p.stat().st_blocks,
                blake3=h,
            )
        elif re.fullmatch(r"[a-z0-9]{1,32}\.o", p.name):
            name = p.name
            with p.open("rb") as f:
                need(valid_object(f.read(18)), "invalid raw ELF")
            d = ident(p)
            desc = dict(
                file=p.name, stat=d, packed=False, digest=d["sha256"], bytes=d["bytes"], blocks=d["blocks"]
            )
        else:
            continue
        need(name not in result, "raw/packed object collision")
        result[name] = desc
    need(result, "empty actual object set")
    return result


def physical(control, sdk, config, *, inventory=None):
    expected = list(config)
    events = {}
    images = {}
    for p in sorted(control.glob("*.cmdline")):
        role, pid = p.stem.rsplit("-", 1)
        argv = [os.fsdecode(v) for v in p.read_bytes().split(b"\0")[:-1]]
        need(role in ("rustc", "wild", "cargo") and pid not in images and argv, ("invalid observed process", p))
        key = {"rustc": "bin/rustc", "cargo": "bin/cargo", "wild": WILD}[role]
        # Rustup may set argv[0] itself. Every selected image is also checked by device/inode in the constructor.
        d, i, size, path = (control / (p.stem + ".image")).read_text().rstrip("\n").split("\t")

        def identity(member):
            if inventory is not None:
                row = inventory[member]
                return (row[1], row[2], row[4])
            st = (sdk / member).stat()
            return (st.st_dev, st.st_ino, st.st_size)

        need(
            (int(d), int(i), int(size)) == identity(key) and os.path.normpath(path) == str(sdk / key),
            "wrong kernel image identity",
        )
        images[pid] = dict(role=role, argv=argv, identity=[int(d), int(i), int(size), path])
        if role != "rustc":
            continue
        driver = sdk / DRIVER
        ds = identity(DRIVER)
        maps = (control / (p.stem + ".maps")).read_text().splitlines()
        found = []
        for m in maps:
            f = m.split(maxsplit=5)
            if len(f) != 6 or "x" not in f[1] or Path(f[5]).name != driver.name:
                continue
            dev = os.makedev(*(int(x, 16) for x in f[3].split(":")))
            need((dev, int(f[4])) == ds[:2] and os.path.normpath(f[5]) == str(driver), "wrong mapped driver")
            found.append(m)
        need(found, "authentic driver not mapped")
        images[pid]["driver_maps"] = found
        for line in (control / (p.stem + ".events")).read_text().splitlines():
            tag, idx, flags, fd, err, dev, ino, size, path = line.split("\t")
            idx, fd, err, dev, ino, size = map(int, (idx, fd, err, dev, ino, size))
            flags = int(flags, 16)
            actual = Path(path)
            owner = actual.parent.parent
            want = expected.index(str(owner)) if str(owner) in expected else -1
            need(
                idx == want
                and actual.is_absolute()
                and ".." not in actual.parts
                and tag in ("G", "Q", "g", "q", "N", "D", "U"),
                "unmatchable I/O",
            )
            need((tag in "GQNDU") == bool(flags & os.O_EXCL and flags & os.O_CREAT), "wrong create vs read")
            basename = RAWS[int(tag == "U")] if tag in ("D", "U") else FILES[int(tag.lower() == "q")]
            need(actual.name == basename and (fd >= 0) == (err == 0), "invalid libc open")
            events.setdefault(owner.name, []).append(
                dict(
                    tag=tag,
                    pid=int(pid),
                    flags=flags,
                    fd=fd,
                    error=err,
                    path=str(actual),
                    dev=dev,
                    ino=ino,
                    bytes=size,
                    index=idx,
                )
            )
    return images, events


def mapped_observer(control, images, expected, identity=None):
    ids = set()
    for pid, r in images.items():
        if r["role"] != "rustc":
            continue
        rows = (control / ("rustc-" + pid + ".maps")).read_text().splitlines()
        observed = set()
        for line in rows:
            f = line.split(maxsplit=5)
            if len(f) == 6 and "x" in f[1] and os.path.normpath(f[5]) == str(expected):
                observed.add((os.makedev(*(int(n, 16) for n in f[3].split(":"))), int(f[4])))
        need(len(observed) == 1, "diagnostic DSO missing or ambiguous on physical rustc")
        ids |= observed
    need(
        len(ids) == 1 and (identity is None or ids == {(identity["dev"], identity["ino"])}),
        "repair rustcs did not map the same authenticated diagnostic DSO",
    )
    return list(ids.pop())


def routes(before, after, images, events, selected, blocked, *, all_owners=None, extra_passthrough=()):
    import errno

    all_owners = set(all_owners or selected)
    selected = set(selected)
    result = {}
    for owner in set(events) - selected:
        extras = [e for e in events[owner] if e["tag"] in "GQN"]
        if extras:
            need(
                owner in extra_passthrough
                and len(extras) == 1
                and extras[0]["tag"] == "G"
                and extras[0]["index"] == -1
                and extras[0]["fd"] >= 0
                and not extras[0]["error"],
                "unexpected non-target create",
            )
    need(
        all(any(e["tag"] == "G" for e in events.get(o, [])) for o in extra_passthrough),
        "missing non-target sham",
    )
    creates = [e for o in selected for e in events.get(o, []) if e["tag"] == "G"]
    need(
        len(creates) == len(selected) and {Path(e["path"]).parent.parent.name for e in creates} == selected,
        "missing or extra first packed create",
    )
    placeholder = [e for rows in events.values() for e in rows if e["tag"] == "N"]
    need(
        len(placeholder) == (len(selected) if blocked else 0)
        and (
            not blocked
            or sorted((x["pid"], x["path"]) for x in placeholder)
            == sorted((x["pid"], x["path"]) for x in creates)
        )
        and all(dict(x, tag="G") in creates for x in placeholder),
        "unmatched blocked query accounting",
    )
    failures = [e for rows in events.values() for e in rows if e["error"] and e["tag"] in "GQ"]
    need(
        len(failures) == (len(selected) if blocked else 0)
        and all(e["tag"] == "G" and e["error"] == errno.EACCES and e["index"] >= 0 for e in failures),
        "unrelated writer fault",
    )
    for owner in sorted(all_owners):
        p = Path(before["owners"][owner])
        old = before["sessions"][owner]
        new = after["sessions"][owner]
        fresh = set(new) - set(old)
        need(len(fresh) == 1, ("unexpected finalized sessions", owner, fresh))
        name = fresh.pop()
        packed = owner in selected and not blocked
        need(
            set(new[name]) == set(FILES if packed else RAWS),
            ("wrong published table representation", owner, name),
        )
        reads = [e for e in events.get(owner, []) if e["tag"] in "gq"]
        reference = set()
        for e in reads:
            read = Path(e["path"])
            file = old.get(read.parent.name, {}).get(read.name)
            if not file:
                continue
            need(
                (file["dev"], file["ino"], file["bytes"]) == (e["dev"], e["ino"], e["bytes"]),
                "different open donor",
            )
            reference.add((read.parent.name, e["tag"]))
        need(
            len(reads) == 2
            and sorted(e["tag"] for e in reads) == ["g", "q"]
            and all(e["fd"] >= 0 for e in reads),
            ("donor retried, missing, or extra reads", owner, reads),
        )
        donors = {n for n, tag in reference if (n, "g") in reference and (n, "q") in reference}
        need(len(donors) == 1, ("unobserved or multiple opens of previous G/Q pair", owner, reads))
        donor = donors.pop()
        restored = [e for e in events[owner] if e["tag"] in ("D", "U")]
        reader = reads[0]["pid"]
        work = p / (name.rsplit("-", 1)[0] + "-working")
        need(
            sorted(e["tag"] for e in restored) == ["D", "U"]
            and all(
                e["pid"] == reader
                and e["fd"] >= 0
                and e["error"] == 0
                and e["bytes"] == 0
                and Path(e["path"]).parent == work
                for e in restored
            ),
            ("donor restore did not create both tables in the actually published session", owner, restored),
        )
        for src, dst in (("g", "D"), ("q", "U")):
            seq = [e["tag"] for e in events[owner]]
            need(
                seq.index(src) < seq.index(dst) and ("G" not in seq or seq.index(dst) < seq.index("G")),
                "reversed source/restore/fresh write",
            )

        def session_id(n):
            m = re.fullmatch(r"s-([0-9a-z]+)-_([a-f0-9]{16})_[0-9a-z]+-[0-9a-z]+", n)
            need(m, ("unexpected session name", n))
            return int(m[1], 36), m[2]

        _, checkout = session_id(name)
        ranked = sorted(((session_id(n), n) for n in old), reverse=True)
        same = next(n for (_, branch), n in ranked if branch == checkout)
        need(
            donor == same and len(old) == 2 and (ranked[0][1] != same) == (owner in selected),
            ("wrong selected checkout", owner, old, donor),
        )
        if owner in selected:
            writer = [e for e in creates if Path(e["path"]).parent.parent == p][0]
            need(
                Path(writer["path"]).parent.name == name.rsplit("-", 1)[0] + "-working"
                and (writer["fd"] < 0) == blocked
                and writer["index"] >= 0
                and (writer["flags"] & os.O_ACCMODE) == os.O_RDWR,
                ("wrong create/new publication", owner, writer),
            )
            queries = [e for e in events[owner] if e["tag"] == "Q"]
            need(
                len(queries) == int(not blocked)
                and all(
                    e["pid"] == writer["pid"]
                    and Path(e["path"]) == Path(writer["path"]).with_name(FILES[1])
                    and not e["error"]
                    for e in queries
                ),
                "second fresh stream after blocked first create",
            )
            if not blocked:
                for i, e in enumerate((writer, queries[0])):
                    published = new[name][FILES[i]]
                    need(
                        (e["dev"], e["ino"], e["bytes"], e["error"])
                        == (published["dev"], published["ino"], 0, 0),
                        ("fresh create did not become published pair", owner, FILES[i]),
                    )
            cmd = images[str(writer["pid"])]["argv"]
            need(
                "--crate-name" in cmd and cmd[cmd.index("--crate-name") + 1] == owner.rsplit("-", 1)[0],
                "writer did not belong to intended rustc",
            )
        need(
            all(e["pid"] == next(x["pid"] for x in reads if x["tag"] == "q") for e in reads),
            "wrong donor reader",
        )
        if owner in selected:
            need(all(e["pid"] == writer["pid"] for e in reads), "writer did not read registered donor")
        result[owner] = dict(final=name, donor=donor, packed_pair=packed)
    return result


def certify(before, after, images, events, selected, blocked, **kwargs):
    result = routes(before, after, images, events, selected, blocked, **kwargs)
    for owner, row in result.items():
        directory = Path(before["owners"][owner]) / row["final"]
        row["tables"] = [table(directory, i, row["packed_pair"]) for i in range(2)]
        row["objects"] = objects(directory)
    return result


def hooks(root, sdk):
    return dict(
        LD_PRELOAD=str(root / "logs/tools/pack-gate.so"),
        OHM_QA_PACK_CONTROL=str(root / "logs/pack-control"),
        OHM_QA_PACK_CARGO=str(sdk / "bin/cargo"),
        OHM_QA_PACK_RUSTC=str(sdk / "bin/rustc"),
        OHM_QA_PACK_WILD=str(sdk / WILD),
    )


def config(mode, paths):
    need(
        mode in ("P", "B") and 0 < len(paths) <= 32 and len(paths) == len(set(paths)),
        "invalid gate configuration",
    )
    need(
        all(
            str(Path(p)) == p
            and p.startswith("/")
            and not any(c in p for c in ("\t", "\n", "\0"))
            and ".." not in Path(p).parts
            for p in paths
        ),
        "unsafe owner path",
    )
    return mode + "\n" + "".join(p + "\n" for p in paths)


def roster(images, events, reg, command, owners):
    actual = []
    links = []
    cargos = []
    seen = set()
    for pid, row in images.items():
        a = row["argv"]
        if row["role"] == "cargo":
            need(a[1:] == command[2:], "unexpected actual Cargo argv")
            cargos.append(pid)
            continue
        if row["role"] == "wild":
            if "-o" in a:
                links.append(a[a.index("-o") + 1])
            else:
                need(
                    set(a[1:]) and set(a[1:]) <= {"-v", "--version", "--help", "--print-output-format"},
                    "unexpected Wild query",
                )
            continue
        need(
            "--crate-name" in a
            and "--crate-type" in a
            and not any("link-only" in v for v in a if v.startswith("-Z") or v.startswith("link-only")),
            "unexpected rustc query or link-only",
        )
        crate = a[a.index("--crate-name") + 1]
        kind = a[a.index("--crate-type") + 1]
        inc = [
            v.removeprefix("-C").removeprefix("incremental=")
            for v in a
            if v.removeprefix("-C").startswith("incremental=")
        ]
        touched = [n for n in owners if any(e["pid"] == int(pid) for e in events.get(n, []))]
        need(
            len(inc) == len(touched) == 1
            and Path(owners[touched[0]]).parent == Path(inc[0])
            and touched[0].rsplit("-", 1)[0] == crate
            and touched[0] not in seen,
            "wrong compiler/owner",
        )
        if crate == "ruff":
            need(
                touched == [{"bin": "ruff-11zykn1hngw9x", "lib": "ruff-1iwusb3cv61i3"}[kind]],
                "wrong CLI vs library owner",
            )
        need(
            any(x in a for x in ("ohm-branch-cache=yes", "-Zohm-branch-cache=yes"))
            and any("ohm-check-relink-inputs" in x for x in a),
            "wrong effective compiler flags",
        )
        seen.add(touched[0])
        actual.append([crate, kind])
    need(
        sorted(actual) == reg["physical_units"] and seen == set(owners) and len(cargos) == len(links) == 1,
        "wrong 16-repair-compiler/one-link shape",
    )
    return links[0]


def compiler_commands(images):
    return {
        im["argv"][im["argv"].index("--crate-name") + 1]
        + ":"
        + im["argv"][im["argv"].index("--crate-type") + 1]: im["argv"]
        for im in images.values()
        if im["role"] == "rustc"
    }


def comparison(first, second, reg):
    need(set(first) == set(second) == set(reg["selected"] + reg["other"]), "changed owner cohorts")
    rawbytes = {k: [0, 0] for k in range(2)}
    diff = []
    counts = [0, 0]
    for name in first:
        a, b = first[name], second[name]
        need(a["packed_pair"] == (name in reg["selected"]) and b["packed_pair"] is False, "wrong treatment")
        ga, gb = a["objects"], b["objects"]
        need(
            set(ga) == set(gb)
            and all(
                tuple(ga[k][f] for f in ("digest", "bytes", "packed"))
                == tuple(gb[k][f] for f in ("digest", "bytes", "packed"))
                for k in ga
            ),
            "regrouped/changed native objects: " + name,
        )
        n = sum(x["packed"] for x in ga.values())
        pair = [n, len(ga) - n]
        need(pair == reg["packed_raw_objects"][name], ("different historic object backend", name, pair))
        for i in range(2):
            counts[i] += pair[i]
        for t, (g, h) in enumerate(zip(a["tables"], b["tables"], strict=True)):
            need(
                g["aliases"] == h["aliases"] == 3 and g["body_bytes"] > 0 and h["body_bytes"] > 0,
                "changed table alias/stage",
            )
            x, y = g["body_bytes"], h["body_bytes"]
            need(
                100 * abs(x - y) <= 2 * max(x, y),
                ("different logical table workload (>2% per stream)", name, t, x, y),
            )
            rawbytes[t][0] += x
            rawbytes[t][1] += y
            if g["body_sha256"] != h["body_sha256"]:
                diff.append([name, t])
    for k, (x, y) in rawbytes.items():
        need(100 * abs(x - y) <= max(x, y), ("different logical table total (>1%)", k, x, y))
    need(counts == [748, 918], "different total object topology")
    return dict(
        objects=counts, logical_bytes=[rawbytes[i] for i in range(2)], different_table_bodies=sorted(diff)
    )
