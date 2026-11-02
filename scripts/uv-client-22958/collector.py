"""Capture exact current Cargo/kernel outputs and every actual compiler metadata input."""

from pathlib import Path
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import tomllib

import service as s

m = s.m


def checked_run(args, d, env=None, cwd=None):
    d.mkdir()
    env = dict(m.ENV if env is None else env)
    with (d / "cargo.stdout").open("xb") as so, (d / "cargo.stderr").open("xb") as se:
        v = subprocess.run(
            list(map(str, args)),
            cwd=cwd or m.SRC,
            env=env,
            stdout=so,
            stderr=se,
            timeout=1200,
        )
    m.save(d / "invocation.json", dict(argv=list(map(str, args)), rc=v.returncode))
    assert v.returncode == 0, (
        d,
        v.returncode,
        (d / "cargo.stderr").read_bytes()[-800:],
    )


def source(state):
    target = s.case[state]
    a = s.case["A"]
    b = s.case["B"]
    git = lambda *v: m.sha_git(m.SRC, *v)
    assert (
        git("rev-parse", "HEAD").decode().strip() == a
        and not git("diff", "--cached", "--name-only")
        and not git("ls-files", "--others", "--exclude-standard")
    )
    changes = git("diff", "--name-only").decode().splitlines()
    assert changes in ([], s.case["files"])
    if bool(changes) != (state == "B"):
        cmd = (
            ["git", "-C", str(m.SRC), "apply", "--whitespace=nowarn"]
            + (["--reverse"] if state == "A" else [])
            + [str(s.HERE / "edit.patch")]
        )
        subprocess.run(cmd, env=m.ENV, check=True)
    assert git("diff", "--name-only").decode().splitlines() == (
        s.case["files"] if state == "B" else []
    )
    with tempfile.TemporaryDirectory(prefix="immutable-uv-index-", dir=m.HOME) as d:
        env = dict(m.ENV, GIT_INDEX_FILE=str(Path(d) / "index"))
        cmd = lambda *x: subprocess.check_output(["git", "-C", m.SRC, *x], env=env)
        cmd("read-tree", a)
        cmd("add", "-u", "--")
        tree = cmd("write-tree").decode().strip()
    assert (
        tree == s.case["trees"][state]
        and git("rev-parse", target + "^{tree}").decode().strip() == tree
    )
    assert m.filesha(m.SRC / "Cargo.lock") == s.case["cargo_lock"]
    return dict(
        revision=target,
        tree=tree,
        head=a,
        eight=s.case["files"],
        lock=s.case["cargo_lock"],
    )


def initialize(w, bank):
    assert not m.ROOT.exists()
    m.ROOT.mkdir()
    m.CARGO_HOME.mkdir()
    m.HOME.mkdir()
    bank.mkdir()
    donor = w / "uv-source"
    v = lambda *args: subprocess.run(
        list(map(str, args)), env=m.ENV, check=True, stdout=subprocess.DEVNULL
    )
    v("git", "init", "-q", m.SRC)
    v(
        "git",
        "-C",
        m.SRC,
        "fetch",
        "-q",
        "--no-tags",
        "--depth=64",
        donor.as_uri(),
        "HEAD",
        "refs/tags/0.13.6:refs/tags/0.13.6",
    )
    v("git", "-C", m.SRC, "checkout", "-q", "-b", "ordinary-origin", s.case["A"])
    git = lambda *x: m.sha_git(m.SRC, *x).decode().strip()
    assert (
        git("rev-parse", "FETCH_HEAD") == s.case["B"]
        and git("rev-parse", s.case["B"] + "^") == s.case["A"]
    )
    assert git("rev-parse", "refs/tags/0.13.6^{}") == s.case["tag_commit"]
    described = {}
    for st in ("A", "B"):
        ref = s.case[st]
        full = git("describe", "--tags", "--long", "--abbrev=40", ref)
        native = git("describe", "--tags", "--long", ref)
        prefix, abbrev = native.rsplit("-g", 1)
        assert 7 <= len(abbrev) <= 40 and ref.startswith(abbrev)
        assert (
            full == prefix + "-g" + ref
            and git("describe", "--tags", "--long", "--abbrev=8", ref)
            == s.case["describe"][st]
        )
        described[st] = dict(
            actual_native=native, full=full, normalized_record=s.case["describe"][st]
        )
    assert source("A")["tree"] == s.case["trees"]["A"]
    assert m.filesha(s.HERE / "edit.patch") == s.case["source_patch"]
    source("B")
    source("A")
    return dict(
        tag="0.13.6",
        tag_commit=s.case["tag_commit"],
        checked_out=s.case["A"],
        descriptions=described,
    )


def registry():
    bankdata = gzip.decompress((s.HERE / "registry.json.gz").read_bytes())
    assert m.digest(bankdata) == s.case["registry_sha"]
    bank = json.loads(bankdata)
    lock = {
        p["name"] + "@" + p["version"]: p["checksum"]
        for p in tomllib.loads((m.SRC / "Cargo.lock").read_text())["package"]
        if "source" in p
    }
    assert len(bank) == 654 and bank.keys() == lock.keys()
    reg = m.CARGO_HOME / "registry"
    (cache,) = (reg / "cache").iterdir()
    (index,) = (reg / "index").iterdir()
    by = {}
    assert cache.name == index.name
    for key, v in bank.items():
        name, ver = key.rsplit("@", 1)
        archive = cache / (name + "-" + ver + ".crate")
        assert (
            archive.stat().st_size == v["archive_bytes"]
            and m.filesha(archive) == lock[key] == v["archive_sha256"]
        )
        ip = index / v["index_relative"]
        if ip not in by:
            by[ip] = [
                json.loads(a)
                for a in ip.read_bytes().split(bytes(1))
                if a.startswith(b"{")
            ]
        (r,) = [x for x in by[ip] if x.get("name") == name and x.get("vers") == ver]
        assert (
            r["cksum"] == lock[key] and m.digest(m.canon(r)) == v["index_record_sha256"]
        )
    return dict(archives=len(bank), names=len(by), identity=m.digest(bankdata))


def graph():
    raw = subprocess.check_output(
        [*s.CHECK, "--unit-graph", "-Zunstable-options"],
        cwd=m.SRC,
        env=m.ENV,
        timeout=180,
    )
    shape = s.old.scope.structural(
        json.loads(raw), m.SRC, m.CARGO_HOME / "registry/src"
    )
    expected = json.loads(gzip.decompress((s.HERE / "unit-graph.json.gz").read_bytes()))
    assert (
        shape == expected
        and s.old.scope.digest(shape) == s.case["graph_digest"]
        and len(shape["units"]) == 543
    )
    return dict(
        actual_sha256=m.digest(raw), normalized=s.case["graph_digest"], units=543
    )


def kernel(d, warm):
    from scoped import DRIVER

    d.mkdir()
    ev = DRIVER.EVENTS
    ev["capture"](d, s.CHECK, m.ENV, str(m.SRC), ev["file_id"](m.RUSTC))
    k = ev["decode"](m.read(d / "kernel-events.json"))
    assert k["exits"][k["root"]] == 0
    forms = {}
    for im in k["images"]:
        argv = im.get("argv", [])
        if "--crate-name" not in argv or not any(v.startswith("--emit") for v in argv):
            continue
        assert im["file"] == ev["file_id"](m.RUSTC) and k["exits"][im["pid"]] == 0
        name = argv[argv.index("--crate-name") + 1]
        forms.setdefault(name, []).append(argv)
    assert not warm or (
        set(forms) == {"uv_client", "uv_configuration"}
        and all(len(l) == 1 for l in forms.values())
    )
    if warm is False:
        expected = [
            u["target"]["name"].replace("-", "_")
            for u in json.loads(
                subprocess.check_output(
                    [*s.CHECK, "--unit-graph", "-Zunstable-options"],
                    cwd=m.SRC,
                    env=m.ENV,
                )
            )["units"]
            if u["mode"] != "run-custom-build"
        ]
        from collections import Counter

        seen = Counter({n: len(x) for n, x in forms.items()})
        diff = seen - Counter(expected)
        assert (
            not Counter(expected) - seen
            and sum(diff.values()) == 3
            and all(n.startswith("autocfg_") for n in diff)
        )
    m.save(d / "forms.json", forms)
    for f in ("stdout", "stderr"):
        os.link(d / f, d / ("cargo." + f))
    return forms


def store(path, blobs):
    raw = path.read_bytes()
    h = m.digest(raw)
    p = blobs / (h + ".gz")
    if not p.exists():
        p.write_bytes(gzip.compress(raw, compresslevel=2, mtime=0))
    return [len(raw), h]


def externs(a):
    for ix, arg in enumerate(a):
        v = (
            a[ix + 1]
            if arg == "--extern"
            else arg[9:]
            if arg.startswith("--extern=")
            else ""
        )
        if "=" in v:
            f = Path(v.split("=", 1)[1])
            assert f.is_absolute() and f.is_file()
            yield f


def products(d, forms, blobs):
    root = m.TARGET
    names = set(s.case["workspace_packages"])
    work = {}
    for f in (root / "debug").rglob("libuv_*.rmeta"):
        if f.name[3:].split("-")[0].replace("_", "-") in names:
            work[str(f.relative_to(root))] = store(f, blobs)
    assert len(work) == 39 and set(forms) == {"uv_client", "uv_configuration"}
    deps = {
        n: {str(f): store(f, blobs) for f in sorted(set(externs(a)))}
        for n, a in forms.items()
    }
    assert {n: len(v) for n, v in deps.items()} == {
        "uv_client": 64,
        "uv_configuration": 30,
    }
    decl = {}
    for n, a in forms.items():
        out = Path(a[a.index("--out-dir") + 1])
        assert (
            out.is_relative_to(root / "debug/build" / n.replace("_", "-"))
            and out.name == "out"
        )
        decl[n] = {
            str(f.relative_to(root)): store(f, blobs)
            for f in sorted(out.rglob("*"))
            if f.is_file()
        }
        assert any(k.endswith(".rmeta") for k in decl[n])
    suffix = {
        str(f.relative_to(root)): store(f, blobs)
        for f in root.rglob("*.public-api-hash")
        if f.is_file()
    }
    assert suffix
    z = dict(workspace=work, externs=deps, declared=decl, all_public_sidecars=suffix)
    m.save(d / "products.json", z)
    return z


def comparable_argv(argv):
    """Keep the full vector, abstracting only Cargo's locally proven 64-bit per-unit salts."""
    prefix = str(m.TARGET / "debug/build") + "/"
    result = []
    for original in argv:
        arg = re.sub(
            re.escape(prefix) + r"([^/]+)/[0-9a-f]{16}/",
            r"{build}/\1/{Cargo-unit-salt}/",
            original,
        )
        arg = re.sub(
            r"(?<=/)(lib[a-zA-Z_0-9]+)-[0-9a-f]{16}(?=\.(?:rlib|rmeta|so))",
            r"\1-{Cargo-unit-salt}",
            arg,
        )
        arg = re.sub(
            r"^(extra-filename=-|metadata=)[0-9a-f]{16}$",
            r"\1{Cargo-unit-salt}",
            arg,
        )
        result.append(arg)
    return result


def streams(d):
    err = (d / "cargo.stderr").read_text()
    normalized, count = re.subn(
        r"(?m)^(    Finished `dev` profile \[unoptimized \+ debuginfo\] target\(s\)) in [^\r\n]+$",
        r"\1",
        err,
    )
    assert (
        count == 1
        and "    Checking uv-configuration " in err
        and "    Checking uv-client " in err
    )
    return [m.filesha(d / "cargo.stdout"), m.digest(normalized.encode())]
