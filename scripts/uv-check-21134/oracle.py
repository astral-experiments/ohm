"""Compare native package products and decode the seven source-qualified inherent implementations."""

from pathlib import Path
import gzip, hashlib, os, runpy, shutil, struct, subprocess, sys, tarfile, tempfile
from common import ENV, HERE, P, ROOT, RUSTC, S, SCRIPTS, blob, git, read, require, save, sha
import dispatch_wire as wire
import private_wire

SPEC = read(HERE / "physical-oracles.json")


def toolkit(root, store):
    parent = SCRIPTS / "uv-client-22958"
    case = read(parent / "case.json")
    root.mkdir()
    with tarfile.open(parent / "metadata-kit.tar.xz") as t:
        members = t.getmembers()
        require(len(members) == len(case["toolkit"]) == len({a.name for a in members}), "metadata readers")
        for f in members:
            require(
                f.isfile() and not f.name.startswith("/") and ".." not in Path(f.name).parts,
                "unsafe metadata member",
            )
            b = t.extractfile(f).read()
            require(hashlib.sha256(b).hexdigest() == case["toolkit"][f.name], "toolkit member")
            p = root / f.name
            p.parent.mkdir(exist_ok=True, parents=True)
            p.write_bytes(b)
    entry = root / case["kit_module"]
    (entry.parent / "blobs").symlink_to(store.resolve(), target_is_directory=True)
    dec = runpy.run_path(str(entry))
    r = runpy.run_path(str(root / "work/uv-workflow-search/rdr_snapshot.py"))
    dec["GEN"]["configure"](r)
    wire.RDR = r
    wire.rmeta = lambda p: rmeta(p, r)
    return dec, r


def rmeta(path, r):
    b = path.read_bytes()
    h = r["Reader21"](b, struct.unpack_from("<Q", b, 8)[0]).read()
    ids = r["sig"].di.keyed(b, h)
    labels = r["crate"](path)["rows"]
    stable = int(h["stable_crate_id"], 16).to_bytes(8, "little").hex()
    keys = [stable + x.hex() for x in ids]
    require(
        len(keys) == len(set(keys)) == len(labels) and all(k[16:] in labels for k in keys),
        "native definition keys",
    )
    return b, h, keys, {k: r["label"](labels, k[16:]) for k in keys}


def geometry(data, p, Reader):
    rd = Reader(data, p)
    tag = rd.byte()
    kind = tag & 3
    n = tag >> 3
    if kind == 3:
        require(1 <= n <= 8, "span shorthand size")
        at = int.from_bytes(rd.raw(n), "little")
        return geometry(data, p - at if tag & 4 else at, Reader)
    context = 0 if tag & 4 else rd.u()
    if kind == 2:
        return None
    lo = rd.u()
    ln = n if n < 31 else rd.u()
    file = rd.u()
    foreign = rd.u() if kind == 1 else None
    return kind, context, lo, ln, file, foreign


def identities(rmeta_path, r, source, phase):
    data, h, ids, labels = rmeta(rmeta_path, r)
    require(h["crate_name"] == "uv_python", "wrong producer")
    table = lambda n: r["sig"].di.rows(data, h["tables"][n])
    pos = lambda n: [int.from_bytes(x, "little") for x in table(n)]
    files = pos("source_map")
    offsets = sorted(set(filter(None, files))) + [h["root"]]
    (file,) = [
        i
        for i, k in enumerate(files)
        if k and b"crates/uv-python/src/discovery.rs" in data[k : offsets[offsets.index(k) + 1]]
    ]
    impls = table("inherent_impls")
    children = table("associated_item_or_field_def_ids")
    spans = pos("def_span")
    found = {}
    Reader = r["sig"].Reader

    def arr(t, i):
        if i >= len(t):
            return []
        k = int.from_bytes(t[i][::2], "little")
        n = int.from_bytes(t[i][1::2], "little")
        if not n:
            return []
        require(k > 0 and n < 2000, "impossible list")
        reader = Reader(data, k)
        return [reader.u() for _ in range(n)]

    def loc(i):
        if i >= len(spans) or not spans[i]:
            return None
        z = geometry(data, spans[i], Reader)
        if not z or (z[0], z[1], z[4], z[5]) != (0, 0, file, None):
            return None
        lo, n = z[2:4]
        require(0 <= lo < lo + n <= len(source), "source span")
        return lo, lo + n

    forms = {(v["type"], v[phase + "_line"]): v for v in SPEC["blocks"]}
    for i, key in enumerate(ids):
        for j in arr(impls, i):
            span = loc(j)
            if span is None:
                continue
            x = (labels[key].split("::")[-1], source[: span[0]].count(b"\n") + 1)
            if x not in forms:
                continue
            v = forms[x]
            end = source.index(b"\n}\n", span[0]) + 2
            block = source[span[0] : end]
            require(
                hashlib.sha256(block).hexdigest() == v["sha256"] and len(block) == v["bytes"],
                "wrong handwritten source block",
            )
            members = {}
            for k in arr(children, j):
                name = labels[ids[k]].split("::")[-1]
                require(name not in members, "ambiguous associated item")
                members[name] = ids[k]
                if name in v["pub"]:
                    z = loc(k)
                    require(z and span[0] < z[0] < end, "method is not in its enrolled source block")
            require(
                set(v["pub"]) <= members.keys() and x[0] not in found, "ambiguous or missing public method"
            )
            found[x[0]] = {
                "impl": ids[j],
                "receiver": key,
                "members": members,
                "source": v["sha256"],
                "native_path": labels[ids[j]],
            }
    require(
        len(found) == 7 and sum(len(x["members"]) for x in found.values()) == 60,
        "seven native impls and sixty actual items",
    )
    return {"crate": h["stable_crate_id"], "rmeta": blob(rmeta_path), "blocks": found}


def compare_owners(a, b, c, role):
    require(
        b["crate"] == c["crate"] == a["crate"]
        and b["blocks"] == c["blocks"]
        and a["blocks"].keys() == b["blocks"].keys(),
        "warm/cold native identity",
    )
    for name, x in a["blocks"].items():
        y = b["blocks"][name]
        require(
            x["receiver"] == y["receiver"]
            and x["source"] == y["source"]
            and x["members"].keys() == y["members"].keys(),
            "wrong matched source block",
        )
        if role == "G":
            require(
                x["impl"] == y["impl"] and x["members"] == y["members"],
                "G displaced an enrolled native impl or item: " + name,
            )
        elif role == "F":
            require(
                x["impl"] != y["impl"] and all(x["members"][n] != y["members"][n] for n in x["members"]),
                "matched F no longer shows the old shift",
            )


def compare_native(left, right, store, decoder, r, headers, role):
    require(
        left["sidecars"] == right["sidecars"] and left["rmeta"].keys() == right["rmeta"].keys(),
        "incompatible native product set or public hash",
    )
    out = {}
    headers.mkdir(exist_ok=True, parents=True)
    for path, a in left["rmeta"].items():
        b = right["rmeta"][path]
        if a == b:
            continue
        name = (
            Path(path).parts[2].rsplit("-", 1)[0]
            if path.startswith("debug/incremental/")
            else Path(path).name[3:].split("-")[0]
        )
        pair = a[1] + "." + b[1]
        if pair in out:
            continue
        v = decoder["check_delta"](a, b, name)
        require(all(v["checks"].values()), "native definitions/expansions/dependencies/CTFE: " + name)

        def content(fp):
            data = gzip.decompress((store / (fp[1] + ".gz")).read_bytes())
            require([len(data), hashlib.sha256(data).hexdigest()] == fp, "original native payload")
            return data

        imgs = []
        header = []
        for fp in (a, b):
            z = content(fp)
            imgs.append(z)
            f = headers / (fp[1] + ".rmeta")
            f.write_bytes(z)
            raw = subprocess.run(
                [RUSTC, "-Zls=root", f], env=dict(ENV, RUSTC_BOOTSTRAP="1"), capture_output=True, check=True
            )
            f.unlink()
            require(raw.stdout and not raw.stderr, "native -Zls=root")
            header.append(hashlib.sha256(raw.stdout).hexdigest())
        require(header[0] == header[1], "native crate header")
        supplemental = None
        moved = set(v["physical_moved"])
        registered = bool(moved) and moved <= set(SPEC["known_differing"].get(name, ()))
        if not v["exact_complete_bytes"] and not registered:
            if not moved:
                require(name == "uv_dispatch", "unexplained wire changed: " + name)
            if not moved and role == "F":
                supplemental = [wire.convert(imgs[0], imgs[1]), wire.convert(imgs[1], imgs[0])]
                require(
                    supplemental[0]["reconstructed"] == b[1] and supplemental[1]["reconstructed"] == a[1],
                    "incomplete wire proof",
                )
            else:
                tables = decoder["L"]["M"]
                supplemental = private_wire.both(*imgs, decoder["Z"]["ROOT"], tables["di"], tables["keys"])
                require(
                    supplemental["crate"] == name
                    and supplemental["raw"] == [{"bytes": size, "sha256": digest} for size, digest in (a, b)]
                    and [row["reconstructed_sha256"] for row in supplemental["both_directions"]] == [b[1], a[1]],
                    "incomplete bidirectional native metadata proof: " + name,
                )
        out[pair] = {"crate": name, "typed": v, "native_header": header[0], "exact_wire": supplemental}
    return {"all_public": len(left["sidecars"]), "all_metadata": len(left["rmeta"]), "nonliteral": out}
