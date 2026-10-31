"""Read the fixed sources and reject a hardware run without the separate qualification."""

import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import zipfile

HERE = Path(__file__).resolve().parent
REG_SHA = "eeb480a3beaa80a95e69f2e36ac6438dd660fc295a453c20bf1a9922a2dbf949"
REG = json.loads((HERE / "registration.json").read_bytes())
HEX = set("0123456789abcdef")
LIB_CMD = [
    "cargo",
    "+ohm",
    "build",
    "--locked",
    "--offline",
    "-p",
    "ruff_python_ast",
    "--lib",
    "--target",
    "x86_64-unknown-linux-musl",
    "-j4",
    "--message-format=json",
]
# A later, separately reviewed data-only enrollment must bind both successful host receipts.
AUTHORIZED_CLEARANCE_SHA256 = json.loads((HERE / "permit.json").read_bytes())["clearance_sha256"]


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def digest(b):
    return hashlib.sha256(b).hexdigest()


def file_sha(p):
    with Path(p).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def write(p, x):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("x") as f:
        json.dump(x, f, indent=2, sort_keys=True)
        f.write("\n")


def opened(p):
    return json.loads(Path(p).read_bytes())


def gate(path):
    require(
        AUTHORIZED_CLEARANCE_SHA256 is not None,
        "HOLD. The external named-metadata/borrow and source-equivalence qualification and scheduling authority have not been bound.",
    )
    require(file_sha(path) == AUTHORIZED_CLEARANCE_SHA256, "wrong independent release")
    r = opened(path)
    require(
        r["approved_screen"] == REG_SHA
        and r["position_orders"] == ["PC", "CP"]
        and r["source_artifact"] == 13031197422
        and r["source_head"] == REG["source_head"]
        and set(r["required"]) == {"named_metadata_and_borrow_host", "source_equivalence"},
        "unmatched clearance",
    )
    for lane in r["required"].values():
        require(
            lane["verdict"] == "pass"
            and isinstance(lane["run"], int)
            and isinstance(lane["job"], int)
            and isinstance(lane["artifact"], int)
            and isinstance(lane["receipt_member"], str)
            and lane["receipt_member"]
            and len(lane["receipt_sha256"]) == 64
            and len(lane["head"]) == 40
            and len(lane["sha256"]) == 64
            and set(lane["head"] + lane["sha256"] + lane["receipt_sha256"]) <= HEX,
            "incomplete actual named qualification",
        )
    return r


def head(p):
    return subprocess.check_output(["git", "-C", p, "rev-parse", "HEAD"], text=True).strip()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def modules(structural, hardware, qual):
    require(file_sha(HERE / "registration.json") == REG_SHA, "registration changed")
    require(
        (head(structural), head(hardware), head(qual))
        == (REG["structural_head"], REG["counter_head"], REG["provider_head"]),
        "nonmatching input checkouts",
    )
    s = structural / "scripts/ohm-musl-pep723"
    require(file_sha(s / "SHA256SUMS") == REG["structural_sum_file"], "structural instructions")
    for line in (s / "SHA256SUMS").read_text().splitlines():
        h, n = line.split("  ", 1)
        require(file_sha(s / n) == h, n)
    for n, h in REG["counter_files"].items():
        require(file_sha(hardware / n) == h, n)
    e = REG["kernel_reader"]
    require(file_sha(qual / e["name"]) == e["sha256"], "process/FD reader")
    hw = hardware / "scripts/ohm-musl-ast-hardware"
    sys.path.insert(0, str(hw))
    import clocked, measure, products

    require(
        Path(clocked.__file__).resolve() == (hw / "clocked.py").resolve()
        and Path(measure.__file__).resolve() == (hw / "measure.py").resolve()
        and Path(products.__file__).resolve() == (hw / "products.py").resolve(),
        "ambient modules",
    )
    require(
        clocked.CMD == LIB_CMD and clocked.PHASES == ("edit", "repeat"),
        "inherited measurement boundary",
    )
    # The authenticated launcher reads its invocation from one module variable. Keep its
    # calibration and consecutive-commands implementation unchanged, and bind our test command.
    clocked.CMD = list(REG["ordinary_argv"])
    case = load("ruff_26693_structural", s / "run.py")
    ev = load("v2_process_reader", qual / e["name"])
    require(case.PLAN["normal_argv"] == clocked.CMD, "different ordinary command")
    ev.APP = case.N
    return case, clocked, measure, products, ev


def typed(data):
    events = [json.loads(x) for x in data.splitlines()]
    require(
        events and events[-1] == {"reason": "build-finished", "success": True}, "measured Cargo error"
    )
    require(
        not any(r["reason"] == "compiler-message" and r["message"]["level"] == "error" for r in events),
        "error in successful Cargo stream",
    )
    units = [m for m in events if m["reason"] == "compiler-artifact"]
    require(len(units) == 36, "36 real units")
    [root] = [
        m
        for m in units
        if m["target"]["name"] == "ruff_python_ast" and m["profile"]["test"] and m["executable"]
    ]
    require(root["target"]["kind"] == ["lib"] and root["features"] == [], "not the enrolled test")
    source = Path(root["manifest_path"]).parents[2]
    registry = None
    for r in units:
        if r["package_id"].startswith("registry+"):
            p = Path(r["manifest_path"])
            segment = [i for i in p.parents if i.name == "registry"]
            require(len(segment) == 1, "registry location")
            if registry is None:
                registry = segment[0].parent
            require(registry == segment[0].parent, "multiple registry origins")
    require(registry is not None, "no registry")

    def project(x):
        if isinstance(x, list):
            return [project(item) for item in x]
        if isinstance(x, dict):
            return {k: project(v) for k, v in x.items()}
        if isinstance(x, str):
            for before, after in [(str(source), "$RUFF"), (str(registry), "$CARGO_HOME")]:
                if x == before or x.startswith(before + "/"):
                    return after + x[len(before) :]
                if x.startswith("path+file://" + before + "/"):
                    return "path+file://" + after + x[len("path+file://" + before) :]
        return x

    rows = sorted(
        json.dumps(
            project([m["package_id"], m["target"], m["features"], m["profile"]]),
            sort_keys=True,
            separators=(",", ":"),
        )
        for m in units
    )
    dirty = sorted([m["target"]["name"], m["profile"]["test"]] for m in units if not m["fresh"])
    require(len(set(rows)) == 36, "repeated compiled unit")
    return {
        "full_typed_roster": digest("\n".join(rows).encode()),
        "dirty": dirty,
        "typed": len(rows),
    }, Path(root["executable"])


def archive_oracle(path):
    require(file_sha(path) == REG["structural_artifact"]["sha256"], "wrong original #26693 evidence")
    out = {}
    with zipfile.ZipFile(path) as z:
        raw = z.read("SHA256SUMS")
        require(
            digest(raw) == REG["structural_artifact"]["ledger"] and z.testzip() is None,
            "wrong structural archive",
        )
        sums = dict(line.split("  ", 1)[::-1] for line in raw.decode().splitlines())
        require(
            len(sums) == 450
            and set(sums) == set(z.namelist()) - {"SHA256SUMS"}
            and all(digest(z.read(n)) == h for n, h in sums.items()),
            "structural member verification",
        )
        for role in "PC":
            for visit in ["edit", "unchanged", "settled"]:
                (ld,) = json.loads(z.read(f"{role}/{visit}/native.json"))["actual_linkers"]
                require(
                    ld["path"] == "/usr/bin/ld" and ld["sha256"] == MUSL_LD_SHA256,
                    "historical GNU musl linker",
                )
        for role in "PC":
            out[role] = {
                phase: typed(gzip.decompress(z.read(f"{role}/{visit}/stdout.gz")))[0]
                for phase, visit in [("edit", "edit"), ("repeat", "unchanged")]
            }
    return out


MUSL_LD_SHA256 = "e9ceb054c12207970f2726dfc07e9a66b411602748628baf27399f02a9bbb31b"
CONTROL_SOURCE = {
    "invalid": "e4bc1ca131176cad792ac19af74c25cc9610fbed044738072b9bd537cfc68de5",
    "wrong": "4ae297ae2757dfb16bd414f48048d7489dd48163cf81812ef3f77d3210d15345",
}
