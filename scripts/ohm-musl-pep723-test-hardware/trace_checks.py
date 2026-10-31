"""Exercise the terminal trace reader with historical physical argv and a synthetic syscall topology."""

import copy
import io
import json
from pathlib import Path
import tarfile
import score
import support as q


def fixture(z, role, phase):
    visit = "unchanged" if phase == "repeat" else phase
    observed = json.loads(z.read(f"{role}/{visit}/native.json"))
    rustc = observed["rustcs"][0]["argv"][0]
    cargo = str(Path(rustc).with_name("cargo"))
    driver = str(Path(rustc).parents[1] / "lib/librustc_driver-test.so")
    tools = {
        "cc": "/usr/bin/cc",
        "collect2": "/usr/libexec/gcc/x86_64-linux-gnu/13/collect2",
        "ld": "/usr/bin/ld",
    }
    witness = {
        "physical_subject": {
            "cargo": {"path": cargo},
            "rustc": {"path": rustc},
            "driver": {"path": driver, "sha256": q.REG["roles"]["driver"][role][0]},
        },
        "tools": {k: {"path": v} for k, v in tools.items()},
    }
    kernel = {"all_exec": [], "cargo": {"pid": 10}, "opaque_rustc_thread_exits": [[50]]}
    lines = {}

    def emit(pid, line):
        lines.setdefault(pid, []).append(line)

    def execution(pid, image, argv):
        kernel["all_exec"].append({"pid": pid, "image": image, "argv": argv})
        emit(pid, f"execve({json.dumps(image)}, {json.dumps(argv)}, 0x1 /* env */) = 0")

    def clone(parent, child):
        emit(parent, "clone(child_stack=NULL, flags=SIGCHLD <unfinished ...>")
        emit(parent, f"<... clone resumed>) = {child}")

    execution(10, cargo, [cargo, *q.REG["ordinary_argv"][2:]])
    for i, r in enumerate(observed["rustcs"], 20):
        clone(10, i)
        execution(i, rustc, r["argv"])
        emit(i, f'openat(AT_FDCWD, "{driver}", O_RDONLY) = 3<{driver}>')
        if r["crate"] == "ruff_python_ast":
            app = i
    for j, (name, image) in enumerate(tools.items(), 30):
        clone(app if j == 30 else j - 1, j)
        argv = observed["actual_linkers"][0]["argv"] if name == "ld" else [image]
        execution(j, image, argv)
    emit(app, "clone3({flags=CLONE_THREAD|CLONE_VM}, 88) = 50")
    emit(50, "???( <unfinished ...>")
    for pid in lines:
        emit(pid, "+++ exited with 0 +++")
    return lines, kernel, witness


def archive(lines):
    storage = io.BytesIO()
    with tarfile.open(fileobj=storage, mode="w:gz") as out:
        for pid, records in sorted(lines.items()):
            payload = "".join(f"1234.{100000+i} {r}\n" for i, r in enumerate(records)).encode()
            info = tarfile.TarInfo("pid." + str(pid))
            info.size = len(payload)
            out.addfile(info, io.BytesIO(payload))
    return storage.getvalue()


def exercise(z, refused):
    cases = []
    for role in "PC":
        for phase in ("edit", "repeat"):
            lines, kernel, witness = fixture(z, role, phase)
            score.native_trace(archive(lines), kernel, witness, role, phase)
            cases.append(role + "/" + phase)
    bad = []
    original, kernel, witness = fixture(z, "C", "repeat")
    for label, edit in [
        ("linker absent", lambda x: x.pop(32)),
        (
            "wrong loaded driver",
            lambda x: x[20].__setitem__(1, x[20][1].replace("driver-test", "driver-different")),
        ),
        ("actual thread status missing", lambda x: x[50].pop()),
        ("unclassified detach", lambda x: x[50].__setitem__(0, "???( <detached ...>")),
        (
            "mixed process masquerades as rustc thread",
            lambda x: x[20].__setitem__(-2, "clone3({flags=CLONE_VM}, 88) = 50"),
        ),
        ("unfinished execve", lambda x: x[20].insert(-1, "execve( <unfinished ...>")),
        (
            "linker under wrong parent",
            lambda x: (
                x[31].remove("<... clone resumed>) = 32"),
                x[31].remove("clone(child_stack=NULL, flags=SIGCHLD <unfinished ...>"),
                x[10].insert(-1, "vfork() = 32"),
            ),
        ),
    ]:
        lines = copy.deepcopy(original)
        edit(lines)
        bad.append(
            refused(lambda: score.native_trace(archive(lines), kernel, witness, "C", "repeat"), label)
        )
    return {
        "actual_original_compiler_ld_argv_with_synthetic_process_topology": cases,
        "invalid_topology_refusals": bad,
    }
