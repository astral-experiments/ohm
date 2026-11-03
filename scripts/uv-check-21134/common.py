"""The immutable source, original ordinary arguments, stable unit paths and raw process forms."""

from pathlib import Path
import gzip, hashlib, json, os, re, runpy, shutil, subprocess, tempfile

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
read = lambda p: json.loads(p.read_bytes())


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as f:
        json.dump(value, f, sort_keys=True, indent=1)
        f.write("\n")


def require(ok, msg):
    if not ok:
        raise ValueError(msg)


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def blob(path):
    return [path.stat().st_size, sha(path)]


def canonical(v):
    return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


P = read(HERE / "protocol.json")
EN = read(HERE / "native-source.json")
S = P["workload"]
require(
    sha(HERE / "protocol.json") == "ed0bcbfd98a69014270bffaf8849d89e1490aba6fea65a92b591611dfc567549",
    "protocol",
)
ROOT = Path("/tmp/uv-workflow-search")
SRC = ROOT / "uv"
TARGET = ROOT / "target"
SDK = ROOT / "sdk"
RUSTC = SDK / "bin/rustc"
CARGO = SDK / "bin/cargo"
CHECK = [str(CARGO), *S["command"]]
ENV = read(SCRIPTS / "handwritten-panel/protocol.json")["env"]
ENV["LC_ALL"] = "C"
ENV.pop("CARGO_TERM_COLOR")
require(
    ENV["RUSTC"] == str(RUSTC)
    and ENV["CARGO_TARGET_DIR"] == str(TARGET)
    and ENV["HOME"] == str(ROOT / "home")
    and ENV["CARGO_NET_OFFLINE"] == "true"
    and not {
        "RUSTFLAGS",
        "CARGO_ENCODED_RUSTFLAGS",
        "RUSTC_BOOTSTRAP",
        "RUSTC_WRAPPER",
        "RUSTC_WORKSPACE_WRAPPER",
    }
    & ENV.keys(),
    "original environment",
)
METER = SCRIPTS / "uv-callables-21041/thread-meter"
DR = runpy.run_path(str(METER / "per_rustc.py"))
EV = DR["EVENTS"]
CLOCK = runpy.run_path(str(SCRIPTS / "uv-client-22958/blocking_clock.py"))["measure"]
normalized = runpy.run_path(str(HERE / "sessions.py"))["inventory"]


def invoke(argv, cwd=SRC, env=ENV, **opts):
    return subprocess.run(list(map(str, argv)), cwd=cwd, env=env, check=True, **opts)


def git(path, *argv, env=ENV):
    return invoke(["git", "-C", path, *argv], path, env, stdout=subprocess.PIPE).stdout


def source(d, phase, donor=None):
    a, b = S["revisions"]
    label = {"A": a, "B": b}[phase]
    if donor:
        require(not d.exists() and donor.is_dir(), "nonempty private source")
        d.mkdir()
        git(d, "init", "-q")
        git(d, "fetch", "--no-tags", "--depth=2", donor.resolve().as_uri(), b)
        git(d, "checkout", "-q", "--detach", a)
    require(
        git(d, "rev-parse", "HEAD").decode().strip() == a
        and git(d, "rev-parse", b + "^").decode().strip() == a
        and not git(d, "tag", "--list")
        and not git(d, "ls-files", "--others", "--exclude-standard"),
        "source HEAD, parent, or tag/extra files",
    )
    require(not git(d, "diff", "--cached", "--name-only"), "index differs from A")
    wanted = EN["source"][phase]
    for rel in EN["files"]:
        present = sha(d / rel)
        h = {s: EN["source"][s]["files"][rel] for s in "AB"}
        require(present in h.values(), "unexpected edit " + rel)
        if present != h[phase]:
            (d / rel).write_bytes(git(d, "show", label + ":" + rel))
        require(sha(d / rel) == h[phase], "file identity")
    for oid, tree in zip(S["revisions"], S["trees"]):
        require(git(d, "rev-parse", oid + "^{tree}").decode().strip() == tree, "Git tree")
    with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
        env = dict(ENV, GIT_INDEX_FILE=str(Path(tmp) / "checked.index"))
        git(d, "read-tree", a, env=env)
        git(d, "add", "-u", "--", env=env)
        tree = git(d, "write-tree", env=env).decode().strip()
    require(
        tree == wanted["actual_tree"] and sha(d / "Cargo.lock") == wanted["lock"], "worktree or Cargo.lock"
    )
    return {"phase": phase, "tree": tree, "commit": label, "checkout_head": a}


def package_input():
    record = read(HERE / "registry-manifest.json")
    require(record["physical_original"] == EN["registry_sha256"], "original registry")
    cache = Path(ENV["CARGO_HOME"]) / "registry/cache"
    dirs = list(cache.iterdir())
    require(len(dirs) == 1, "more than one registry cache")
    cfg = cache.parent / "index" / dirs[0].name / "config.json"
    config = read(cfg)
    original = sha(cfg) == record["original_config_sha256"]
    cdn = config.get("dl", "")
    public = (
        cdn
        in (
            "https://static.crates.io/crates",
            "https://static.crates.io/crates/{crate}/{crate}-{version}.crate",
        )
        and config.get("api") == "https://crates.io"
    )
    require(original or public, "unregistered registry source")
    for label, row in record["packages"].items():
        f = dirs[0] / label
        require(
            f.is_file() and f.stat().st_size == row["size"] and sha(f) == row["sha256"],
            "wrong archive " + label,
        )
        name = row["name"].lower()
        directory = {1: "1", 2: "2", 3: "3/" + name[0]}.get(len(name), name[:2] + "/" + name[2:4])
        index = cache.parent / "index" / dirs[0].name / ".cache" / directory / name
        data = index.read_bytes()
        require(data[:1] == b"\x03" and data[-1:] == b"\0", "registry index format")
        fields = data[5:-1].split(b"\0")
        records = [raw for v, raw in zip(fields[1::2], fields[2::2]) if v == row["version"].encode()]
        require(len(records) == 1, "ambiguous source row " + label)
        data = json.loads(records[0])
        wire = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        require(
            hashlib.sha256(wire).hexdigest() == row["full_json_sha256"] and data["cksum"] == row["sha256"],
            "changed sparse registry row " + label,
        )
    return {
        "original": EN["registry_sha256"],
        "package_count": len(record["packages"]),
        "resolved_cache": dirs[0].name,
        "source_config": sha(cfg),
        "registry_manifest": sha(HERE / "registry-manifest.json"),
    }


def surface(target=TARGET):
    raw = {str(p.relative_to(target)): blob(p) for p in sorted(target.rglob("*.rmeta"))}
    side = {str(p.relative_to(target)): blob(p) for p in sorted(target.rglob("*.public-api-hash"))}
    values, origin = normalized(raw)
    require(len(side) > 90 and len(values) > len(side), "incomplete native product inventory")
    return {"rmeta": values, "sidecars": side}, origin


def product_roster(snapshot):
    from collections import Counter

    full = {}
    for kind, items in snapshot.items():
        counts = Counter()
        for path in items:
            parts = path.split("/")
            if parts[:2] == ["debug", "build"]:
                require(
                    len(parts) >= 6 and re.fullmatch("[0-9a-f]{16}", parts[3]),
                    "unknown product owner " + path,
                )
                salt = parts[3]
                parts[3] = "{unit}"
                parts[-1] = parts[-1].replace("-" + salt + ".", "-{unit}.")
            elif parts[:2] == ["debug", "incremental"]:
                require(
                    len(parts) == 5
                    and re.fullmatch(r".+-[0-9a-z]{10,15}", parts[2])
                    and re.fullmatch(r"session-crate-hash-[0-9a-z]+", parts[3]),
                    "unknown incremental crate product " + path,
                )
                parts[2] = parts[2].rsplit("-", 1)[0] + "-{unit}"
                parts[3] = "{session-crate-hash}"
            else:
                raise ValueError("unknown canonical product " + path)
            counts["/".join(parts)] += 1
        full[kind] = dict(sorted(counts.items()))
    require(
        sum(full["rmeta"].values()) == 657 and sum(full["sidecars"].values()) == 525,
        "changed complete product roster",
    )
    return full


def retain(path, store):
    fp = sha(path)
    dst = store / (fp + ".gz")
    store.mkdir(exist_ok=True, parents=True)
    if not dst.exists():
        with path.open("rb") as inp, dst.open("xb") as out, gzip.GzipFile(
            fileobj=out, mode="wb", mtime=0, compresslevel=3, filename=""
        ) as z:
            shutil.copyfileobj(inp, z, 1 << 20)
    return [path.stat().st_size, fp]


def forms_from_tree(tree, rustc_id):
    require(tree["exits"][tree["root"]] == 0, "Cargo exited unsuccessfully")
    (cargo,) = [v for v in tree["images"] if v["pid"] == tree["root"]]
    require(
        cargo["exe"] == str(CARGO)
        and all(v["file"] == rustc_id or v["pid"] == tree["root"] for v in tree["images"]),
        "unregistered separate executable in edited/no-op Cargo",
    )
    out = {}
    all_rows = []
    for v in tree["images"]:
        if v["file"] != rustc_id:
            continue
        a = v["argv"]
        require(v["exe"] == str(RUSTC) and tree["exits"].get(v["pid"]) == 0, "rustc image or return")
        all_rows.append(v)
        if not any(t.startswith("--emit=") for t in a):
            require(
                "-vV" in a or "--print" in a or any(x.startswith("--print=") for x in a),
                "unidentified non-emitting subprocess",
            )
            continue
        require(
            a[0] == str(RUSTC)
            and a.count("--crate-name") == 1
            and a.count("--crate-type") == 1
            and a[a.index("--crate-type") + 1] == "lib",
            "unexpected emitting rustc",
        )
        name = a[a.index("--crate-name") + 1]
        require(
            name not in out and "-Zself-profile" not in " ".join(a), "duplicate compiler or extra profiling"
        )
        out[name] = a
    return out, all_rows


def kernel(dst, scalar=None):
    dst.mkdir()
    fid = EV["file_id"](RUSTC)
    EV["capture"](dst, CHECK, ENV, str(SRC), fid)
    tree = EV["decode"](read(dst / "kernel-events.json"))
    forms, rows = forms_from_tree(tree, fid)
    if scalar is not None:
        require(bool(forms) == scalar, "expected emitting edit or strictly fresh no-op")
    save(
        dst / "observed.json",
        {"command": CHECK, "root_pid": tree["root"], "rows": rows, "forms": forms, "rustc_id": fid},
    )
    return forms


def ordinary(dst):
    dst.mkdir()
    with (dst / "stdout").open("xb") as out, (dst / "stderr").open("xb") as err:
        v = CLOCK(CHECK, cwd=SRC, env=ENV, stdout=out, stderr=err)
    require(
        v["exit"] == 0 and b"Finished" in (dst / "stderr").read_bytes(),
        "ordinary Cargo failed or its raw finish is missing",
    )
    save(dst / "clock.json", v)
    return v


def fixed_seed(path, expected=None):
    require(
        shutil.disk_usage(ROOT).free >= 12 << 30 and TARGET.parent == ROOT and not TARGET.is_symlink(),
        "physical seed floor",
    )
    if expected is None:
        require(not path.exists() and TARGET.is_dir(), "new A seed")
        invoke(["tar", "--xattrs", "-I", "zstd -q -1 -T2", "-cf", path, "-C", ROOT, "target"])
        return blob(path)
    require(blob(path) == expected, "modified prior A seed")
    if TARGET.exists():
        shutil.rmtree(TARGET)
    invoke(["tar", "--xattrs", "-I", "zstd -dq", "-xf", path, "-C", ROOT])
    require(TARGET.is_dir(), "restored A")


def independent_role_sources(control, treatment):
    require(
        control in ("R", "F") and treatment == "G" and P["roles"]["G"]["parent"] == P["roles"]["F"]["rust"],
        "role scope",
    )
