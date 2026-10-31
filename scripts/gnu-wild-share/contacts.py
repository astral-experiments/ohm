"""Small real GNU linker and adversarial original-ledger contacts, outside Ruff."""

import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from kernel import SELECTORS, arguments, classify, dump, identity, require, snapshot
from calibration import observer_args, raw_visit


def real(out, rustc, wild, binary):
    cc = Path(shutil.which("cc"))
    c2 = subprocess.check_output([cc, "-print-prog-name=collect2"], text=True).strip()
    ids = {n: identity(p) for n, p in zip(SELECTORS, (rustc, cc, c2, wild))}
    dump(out / "selectors.json", ids)
    src = out / "tiny.c"
    src.write_text("int main(void){return 42;}\n")
    subprocess.run([cc, "-c", src, "-o", out / "root.o"], check=True)
    roles = {a: str(out / a) for a in ("first", "second")}
    args = [
        sys.executable,
        "-IS",
        "-c",
        'import subprocess,sys; cc,b,obj,*outs=sys.argv[1:]; ps=[subprocess.Popen([cc,"-B"+b,"-fuse-ld=bfd",obj,"-o",o]) for o in outs]; sys.exit(max(p.wait() for p in ps))',
        cc,
        wild.parent,
        out / "root.o",
        *roles.values(),
    ]
    trace = out / "trace"
    trace.mkdir()
    raw_visit(
        trace, observer_args(binary, trace, "topology", ids, args), os.environ, out
    )
    report = classify(snapshot(trace, "topology", ids), roles, "native")
    for app in roles.values():
        require(subprocess.run([app]).returncode == 42, "wrong linked executable")
    dump(
        out / "result.json",
        {
            "roles": roles,
            "native": {k: identity(v) for k, v in roles.items()},
            "topology": report,
        },
    )
    return ids, roles, trace


def reject(action):
    try:
        action()
    except (ValueError, KeyError, IndexError):
        return
    raise AssertionError("mutation was admitted")


def mutate(out, ids, roles, source):
    from copy import deepcopy

    original = snapshot(source, "topology", ids)
    bad = deepcopy(original)
    first, second = [r for r in bad["rows"] if r["name"] == "wild"]
    second["argv"][second["argv"].index("-o") + 1] = arguments(first["argv"], "-o")
    reject(lambda: classify(bad, roles, "native"))
    bad = deepcopy(original)
    first, second = [r for r in bad["rows"] if r["name"] == "wild"]
    bad["chains"][second["pid"]].insert(1, first["pid"])
    reject(lambda: classify(bad, roles, "native"))
    for label, file, change in [
        (
            "forged-physical",
            "exec.tsv",
            lambda s: (
                "\n".join(
                    (
                        "\t".join(line.split("\t")[:5] + ["0", line.split("\t")[6]])
                        if line.split("\t")[2] == "4"
                        else line
                    )
                    for line in s.splitlines()
                )
                + "\n"
            ),
        ),
        (
            "missing-event",
            "samples.tsv",
            lambda s: "\n".join(s.splitlines()[:-1]) + "\n",
        ),
        ("incomplete-family", "tasks.tsv", lambda s: s[: s.rfind("exit\t")]),
        (
            "multiplex",
            "samples.tsv",
            lambda s: (
                "\n".join(
                    "\t".join(l.split("\t")[:3] + ["0", "24", "400", "1000", "997"])
                    for l in s.splitlines()
                )
                + "\n"
            ),
        ),
    ]:
        temp = out / label
        shutil.copytree(source, temp)
        f = temp / file
        f.write_text(change(f.read_text()))
        reject(
            lambda: snapshot(temp, "tree" if label == "multiplex" else "topology", ids)
        )
    dump(
        out / "negative.json",
        {
            "rejected": [
                "duplicated output",
                "nested second Wild",
                "wrong physical image",
                "missing PMU FD",
                "incomplete family",
                "multiplex",
            ]
        },
    )


if __name__ == "__main__":
    folder, compiler, wild, binary = map(lambda p: Path(p).resolve(), sys.argv[1:])
    folder.mkdir()
    ids, roles, raw = real(folder, compiler, wild, binary)
    mutate(folder, ids, roles, raw)
