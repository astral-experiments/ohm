"""Replay both first full-execution rejections against immutable original GitHub archives."""

import ast, gzip, hashlib, json, subprocess, sys, tempfile
from pathlib import Path
from zipfile import ZipFile
import argparse

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("original23", type=Path)
parser.add_argument("original24", type=Path)
parser.add_argument(
    "llvm", type=Path, help="signed kit libLLVM.so for independent BLAKE3"
)
args = parser.parse_args()
PILOT = Path(__file__).resolve().parents[2]
M = PILOT.parent
sys.path[:0] = [str(PILOT), str(M / "workspace-link-proof")]
from native_fallback import check
import coordinator


def sha(x):
    return hashlib.sha256(x).hexdigest()


hasher = coordinator.Blake3(args.llvm)
source = (M / "e2e-existing-output/donor.py").read_bytes()
tree = ast.parse(source)
func = next(
    fn
    for fn in tree.body
    if isinstance(fn, ast.FunctionDef) and fn.name == "provider_file"
)
code = next(
    c.value.args[0].value
    for c in func.body
    if isinstance(c, ast.Expr)
    and isinstance(c.value, ast.Call)
    and isinstance(c.value.func, ast.Attribute)
    and c.value.func.attr == "write_text"
)
with tempfile.TemporaryDirectory() as d:
    t = Path(d)
    (t / "guard.s").write_text(code)
    subprocess.run(
        ["/usr/bin/as", "--64", "-o", t / "guard.o", t / "guard.s"], check=True
    )
    subprocess.run(["/usr/bin/ar", "crD", t / "libutil.a", t / "guard.o"], check=True)
    archive = (t / "libutil.a").read_bytes()
    assert (
        subprocess.check_output(["/usr/bin/ar", "t", t / "libutil.a"]) == b"guard.o\n"
    )
    obj = subprocess.check_output(
        ["/usr/bin/objdump", "-dr", "libutil.a"], cwd=t
    ).decode()
    assert (
        "<zzQA>:" in obj
        and "<qa_force_exit>:" in obj
        and "$0x53,%edi" in obj
        and "syscall" in obj
    )
provider = {
    "bytes": len(archive),
    "blake3": hasher.digest([archive]),
    "sha256": sha(archive),
}
assert provider == {
    "bytes": 1094,
    "blake3": "6155742e854e1274d63647f3d0137dd6fa9cabaefb4ab9c23e8a8bf6eeb4510c",
    "sha256": "a83083cb94eedabc22eb859b71a97adf67b48f6860849d958d1e0ad028b7a273",
}
answer = {
    "provider": provider,
    "original_asm": code,
    "provider_source_sha256": sha(source),
    "objdump": obj,
    "cases": {},
}
spec = [
    (
        23,
        41737649726,
        "b793f66dcaa3d935abca0fc2d5d9fd6de9737da7c3e3c1b05836581ffe481c7f",
        "four",
    ),
    (
        24,
        41737656295,
        "cd34338da0ad5cb2812ac7f87baea7f93d97e49196ac448fb82cc0a7781d5505",
        "earlier",
    ),
]
role = "/ty_server/f5c6198f896cf7b0/out/e2e-f5c6198f896cf7b0"
for rel, rid, zh, mode in spec:
    tag = "C-native-" + mode
    p = {23: args.original23, 24: args.original24}[rel]
    with p.open("rb") as f:
        assert hashlib.file_digest(f, "sha256").hexdigest() == zh
    with ZipFile(p) as z:

        def read(n):
            x = z.read(n)
            return gzip.decompress(x) if n.endswith(".gz") else x

        def j(n):
            return json.loads(read(n))

        act = j(tag + "/physical-decisions.json")["actors"][role]
        body = read(tag + "/actor-" + act["pid"] + ".tsv.gz").decode()
        mut = j(tag + "-actual-change.json")
        op = coordinator.rows(body)
        (em,) = op["EMITTED"]
        inv = j(tag + "/inventory.json.gz")
        assert em[-1].endswith("/" + inv["binary"]) and inv["binary"].endswith(role)
        elf = inv["executables"][inv["binary"]]["elf"]
        assert elf["bytes"] == int(em[2])
        actual = {
            "identity": list(map(int, em[:3])),
            "blake3": em[3],
            "path": em[4],
            "sha256": elf["sha256"],
        }
        prev = j("C-exec-edit-receipt.json.gz")["published"][role]
        proof = check(act, body, mut, provider, actual, prev)
        cases = []

        def refuse(name, a=act, b=body, m=mut, p=provider, e=actual, old=prev):
            try:
                check(a, b, m, p, e, old)
            except (AssertionError, ValueError, KeyError):
                cases.append(name)
                return
            raise AssertionError(name)

        for k, v in [
            ("allowed", True),
            ("response", "verify"),
            ("action", "fresh"),
            ("pid", "999999999"),
            ("from_full_stage", tag),
            ("key", act["prior"]["key"]),
        ]:
            refuse("forged " + k, a={**act, k: v})
        for field in ("EMITTED", "VERIFIED", "ACTUAL-GROUP"):
            refuse(
                "missing " + field,
                b="\n".join(
                    l
                    for l in body.splitlines()
                    if not l.startswith(field + "\t") and l != field
                ),
            )
        refuse("forged accepted old output", b=body + "\nACCEPT\tforged\n")
        refuse(
            "unselected libutil",
            b="\n".join(
                l
                for l in body.splitlines()
                if not (l.startswith("USED\t") and l.endswith("/raw-dylibs/libutil.a"))
            ),
        )
        refuse("wrong opened provider bytes", p={**provider, "blake3": "e" * 64})
        refuse(
            "wrong output identity",
            e={**actual, "identity": [0, 0, actual["identity"][2]]},
        )
        refuse(
            "opposite output semantic family",
            old=actual["sha256"] if mode == "four" else "e" * 64,
        )
        if mode == "four":
            refuse(
                "three changed bytes",
                m={**mut, "changed_offsets": mut["changed_offsets"][:3]},
            )
        out = (
            read(tag + "-native/stdout").decode()
            if tag + "-native/stdout" in z.namelist()
            else None
        )
        if mode == "earlier":
            assert (
                "test commands::debug_command ... ok" in out
                and "1 passed; 0 failed;" in out
            )
        assert tag + "-verdict.json" not in z.namelist()
        phases = {}
        for name in ("edit", "warm1", "warm2", "warm3"):
            rows = {}
            for arm in "PC":
                phase = arm + "-" + name
                clock = j(phase + "/hardware.json")
                both = j(phase + "-receipt.json.gz")
                assert (
                    clock == both["meter"]
                    and clock["status"] == 0
                    and clock["enabled"] == clock["running"] > 0
                )
                rows[arm] = {"meter": clock}
                if arm == "C":
                    ds = j(phase + "/physical-decisions.json")
                    assert ds["commit"] and ds["exit"] == 0
                    hits = sorted(
                        k for k, v in ds["actors"].items() if v["action"] == "fresh"
                    )
                    assert hits == sorted(both["fresh_roles"])
                    rows[arm].update(
                        {
                            k: both[k]
                            for k in (
                                "actions",
                                "held_allocated",
                                "native_bytes_consumed",
                                "signed_output_reads_for_donor",
                                "metadata_bytes",
                            )
                        }
                    )
            phases[name] = rows
        import component_epochs

        signed = component_epochs.gather(z, "P-exec-warm")
        all_roles = {
            k.removesuffix(" StockWild"): v["instructions_raw"]
            for k, v in signed["native_roles"].items()
        }
        selected = {
            Path(k).name for k in json.loads((PILOT / "accepted-48.json").read_bytes())
        }
        assert (
            len(selected) == 48
            and len(all_roles) == 50
            and selected <= all_roles.keys()
            and signed["all_unscaled_exact"]
        )
        eligible = sum(all_roles[k] for k in selected)
        assert (
            sum(all_roles.values())
            == signed["domain_clocks"]["StockWild"]["instructions_raw"]
        )
        component_bound = {
            "outer": signed["outer"],
            "all_eligible_stock_wild": eligible,
            "cost_without_those_48": signed["outer"][0] - eligible,
            "excluded_wild": sum(all_roles.values()) - eligible,
            "unassigned_child_gap": signed["unsigned_observer_gap"],
            "disjoint_domains": signed["domain_clocks"],
        }
        ordinary_to_trace = {}
        for phase in ("C-warm3", "C-exec-warm"):
            dr = j(phase + "/physical-decisions.json")["actors"]
            ordinary_to_trace[phase] = {k: v["parts"] for k, v in dr.items()}
        a, b = ordinary_to_trace.values()
        assert len(a) == len(b) == 48 and all(
            [k for k in a[r] if a[r][k] != b[r][k]] == ["context"] for r in b
        )
        assert (
            "complete.json" not in z.namelist()
            and "P-empty-new-receipt.json.gz" not in z.namelist()
        )
        answer["cases"][rel] = {
            "ordinary_phases": phases,
            "cost_census": component_bound,
            "changed_contexts_in_separate_trace": 48,
            "run": rid,
            "zip_sha256": zh,
            "phase": tag,
            "physical_output": proof,
            "exercised_negatives": cases,
            "challenge": mut,
            "native_stdout": out,
            "physical_elf_sections": elf["sections"],
            "provider_source_original": mode,
        }
print(json.dumps(answer, indent=2, sort_keys=True))
