"""Prove the measured Cargo invocations used the ordinary incremental developer profile."""
import os
from pathlib import Path

from study import digest, need, save, sha

HOST_ENV = ("HOME", "PATH", "USER", "LOGNAME", "TMPDIR", "SHELL", "SSL_CERT_FILE",
            "SSL_CERT_DIR", "DEVELOPER_DIR", "SDKROOT")


def environment():
    return {key: os.environ[key] for key in HOST_ENV if key in os.environ}


def products(work, directory, crate):
    directory = Path(directory).resolve(strict=True)
    need(any(directory.is_relative_to((work / area).resolve()) for area in ("target", "shared")),
         "incremental files outside the measured Cargo roots")
    sessions = []
    for product in sorted(directory.glob(crate + "-*/s-*/work-products.bin")):
        session = product.parent
        if session.name.endswith("-working"):
            continue
        graph = session / "dep-graph.bin"
        objects = sorted(p for p in session.glob("*.o") if p.is_file() and p.stat().st_size)
        if product.stat().st_size and graph.is_file() and graph.stat().st_size and objects:
            sessions.append({"path": str(session), "work_products": sha(product),
                             "graph_bytes": graph.stat().st_size, "objects": len(objects),
                             "object_names_sha256": digest("\n".join(p.name for p in objects).encode())})
    need(sessions, f"missing completed {crate} codegen session in {directory}")
    return sessions


def observe(events, work, sdk, subjects, dest):
    compiler = sdk / "bin/rustc"
    emitters = []
    for event in events:
        argv = event["argv"]
        path = Path(event["path"])
        if not path.is_file() or not path.samefile(compiler) or "--crate-name" not in argv:
            continue
        crate = argv[argv.index("--crate-name") + 1]
        if crate not in subjects or not any(a == "--emit" or a.startswith("--emit=") for a in argv):
            continue
        if any("link-only" in a for a in argv):
            continue
        emits=[a[7:] for a in argv if a.startswith("--emit=")]
        emits.extend(b for a,b in zip(argv,argv[1:]) if a=="--emit")
        if not any("link" in e.split(",") for e in emits):
            continue
        if crate=="e2e":
            need("--test" in argv,"physical e2e emitter is not a test executable")
        values = [argv[i + 1] for i, arg in enumerate(argv[:-1]) if arg == "-C"]
        values.extend(a[2:] for a in argv if a.startswith("-C") and a != "-C")
        inc = [v.split("=", 1)[1] for v in values if v.startswith("incremental=")]
        need(len(inc) == 1, f"local {crate} compiler did not receive one incremental directory")
        emitters.append({"crate": crate, "pid": event["pid"], "path": str(path), "argv": argv,
                         "directory": inc[0], "sessions": products(work, inc[0], crate)})
    need({e["crate"] for e in emitters} == set(subjects), "missing required physical Ruff compiler")
    save(dest / "development-emitters.json", emitters)
    return emitters


def verify_saved(work, evidence, dest):
    rows = [{"crate": crate, "directory": directory, "sessions": products(work, directory, crate)}
            for crate, directory in sorted({(e["crate"], e["directory"]) for e in evidence})]
    need(rows, "no measured compiler directories")
    save(dest / "development-products.json", rows)
