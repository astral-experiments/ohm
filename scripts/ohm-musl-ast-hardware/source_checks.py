"""Read only the genuine prior #285 whole-AST archive and verify the consuming modules import at the pinned Git revision."""

import argparse
import gzip
import io
from unittest import mock
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile
from collections import Counter

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import clocked as c, products, measure, ingress


def structural(path):
    with zipfile.ZipFile(path) as z, tempfile.TemporaryDirectory() as t:
        c.require(z.testzip() is None, "baseline ZIP CRC")
        prefix = "musl-ast/receipts/build/"
        term = json.loads(z.read(prefix + "terminal.json"))
        c.require(term["cmd"] == c.CMD and term["full_byte_gate_passed"], "previous true normal AST")
        results = {}
        for name in ("old", "edited", "unchanged", "second-unchanged", "empty", "repair"):
            base = prefix + name + "/"
            k = json.loads(z.read(base + "kernel.json"))
            observed = measure.terminal_native(k)
            messages = [json.loads(l) for l in gzip.decompress(z.read(base + "stdout.gz")).splitlines()]
            graph = products.product(messages)[0]
            expected = term["visits"][name]
            c.require(
                graph["count"] == expected["typed"]
                and graph["count"] - len(graph["dirty"]) == expected["typed_fresh"],
                name,
            )
            census = Counter(k["path"] for k in k["link_tools"])
            if name in ("old", "empty"):
                c.require(
                    len(observed["full_rustcs"]) == 39
                    and sorted(census.values()) == [8, 8, 8]
                    and sorted(Path(p).name for p in census) == ["cc", "collect2", "ld.bfd"],
                    name,
                )
                c.require(any(n.endswith("/wild-ld/ld.bfd") for n in census), name)
            else:
                c.require(
                    observed["full_rustcs"]
                    == sorted(
                        expected["emitted"][i][0]
                        for i in range(len(expected["emitted"]))
                        if not expected["emitted"][i][3]
                    ),
                    name,
                )
            tmp = Path(t) / "events.tar.gz"
            tmp.write_bytes(z.read(base + "execs.tar.gz"))
            products.complete_execs(tmp)
            rows, resumed = products.signed_exec.read_execs(gzip.decompress(z.read(base + "client-exec.gz")))
            (ld,) = [q for q in rows if Path(q[1]).name in ("ld", "ld.bfd", "ld.lld", "wild")]
            inputs = [Path(a).name for a in ld[2] if not a.startswith("-") and "/self-contained/" in a]
            c.require(
                set(inputs) == {"rcrt1.o", "crti.o", "crtbeginS.o", "crtendS.o", "crtn.o"}
                and ld[1] == "/usr/bin/ld",
                name,
            )
            results[name] = {
                "full": len(observed["full_rustcs"]),
                "host": len(observed["host_full"]),
                "target": len(observed["target_full"]),
                "wild": sum(v for p, v in census.items() if "/wild-ld/" in p),
                "graph": graph["count"],
                "visitor_ld": ld[1],
                "visitor_crt_operands": inputs,
                "actual_visitor_sha256": term["outputs"][name]["client"]["sha256"],
            }
        bad = [json.loads(l) for l in gzip.decompress(z.read(prefix + "invalid/stdout.gz")).splitlines()]
        messages = [
            m for m in bad if m.get("reason") == "compiler-message" and m["message"]["level"] == "error"
        ]
        codes = [
            (m["target"]["name"], m["message"]["code"]["code"], [s["file_name"] for s in m["message"]["spans"]])
            for m in messages
        ]
        c.require(
            any(
                n == "ruff_python_ast"
                and v == "E0425"
                and any("crates/ruff_python_ast/src/visitor.rs" in s for s in spans)
                for n, v, spans in codes
            ),
            codes,
        )
        return {
            "source_run": 41166655409,
            "archive": c.file_sha(path),
            "behavior": results,
            "bad_actual": codes,
        }


def distinct_surfaces(archive):
    # An unscored fixture keeps the original typed P stdout's three dirty units but changes the
    # synthetic C kernel to zero full and one link-only rustc. The reader must preserve both facts.

    with zipfile.ZipFile(archive) as z:
        prefix = "musl-ast/receipts/build/"
        source = json.loads(z.read(prefix + "terminal.json"))
        fixed = {
            "build-markers.json": {
                "empty": {n: ["hard", "fixture"] for n in ("zmij", "compact_str", "ruff_python_ast")}
            },
            "qualified-ordinary.json": {"role": "C", "structural": {"build": True, "fixture_only": True}},
        }
        plain = {"role": "C", "all": {}}
        streams = {}
        for phase, flank in (("edit", "edited"), ("repeat", "unchanged")):
            raw = gzip.decompress(z.read(prefix + flank + "/stdout.gz"))
            messages = [json.loads(x) for x in raw.splitlines()]
            names = [
                [m["package_id"], m["target"]["name"], m["fresh"]]
                for m in messages
                if m["reason"] == "compiler-artifact"
            ]
            plain["all"][phase] = {"cmd": c.CMD, "exit": 0, "fresh": names}
            streams["ordinary/" + phase + "/stdout.jsonl.gz"] = gzip.compress(raw, mtime=0)
            k = json.loads(z.read(prefix + flank + "/kernel.json"))
            if phase == "repeat":
                k["rustcs"] = k["rustcs"][:1]
                k["rustcs"][0]["link_only"] = True
                source["visits"][flank]["emitted"] = [
                    [k["rustcs"][0]["crate"], ["x86_64-unknown-linux-musl"], "hard", True]
                ]
            fixed["build/" + flank + "/kernel.json"] = k
        fixed["ordinary/terminal.json"] = plain
        fixed["build/terminal.json"] = source

        def check():
            out = io.BytesIO()
            with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as f:
                for key, v in fixed.items():
                    f.writestr(key, json.dumps(v))
                for n, payload in streams.items():
                    f.writestr(n, payload)
            data = out.getvalue()
            item = {
                "name": "musl-285-ordinary-C",
                "id": 1,
                "expired": False,
                "size_in_bytes": len(data),
                "digest": "sha256:" + c.sha(data),
                "workflow_run": {"id": ingress.SOURCE_RUN, "head_sha": ingress.SOURCE_HEAD},
            }
            with mock.patch.object(ingress, "request", return_value=data):
                return ingress.reopen([item], "C", c.sha(data))

        result = check()
        c.require(
            len(result["typed"]["repeat"]["dirty"]) == 3
            and not result["native"]["repeat"]
            and len(result["link_only_native"]["repeat"]) == 1,
            "inferred kernel execution from typed freshness",
        )
        altered = plain["all"]["repeat"]["fresh"][0]
        altered[2] = not altered[2]
        try:
            check()
        except RuntimeError:
            pass
        else:
            raise AssertionError("forged typed projection accepted")
        return {
            "synthetic": True,
            "dirty_typed_units": 3,
            "full_rustc": 0,
            "link_only_rustc": 1,
            "wrong_typed_projection_rejected": True,
        }


def imports(repo, rev, *, provider=False):
    # The actual checkout on hosted Actions is full. The devbox uses a sparse donor.
    # Materialize only the small relevant Python sources and four data files, using this exact commit.
    scripts = [
        "ohm-aarch64-linux/runtime.py",
        "ohm-aarch64-linux/qualify.py",
        "ohm-apple-zmij/study.py",
        "ohm-gnu-ty-input-census/census.py",
        "ohm-gnu-ty-input-census/cli.py",
        "ohm-gnu-atomic-db/build_candidate.py",
        "ohm-gnu-atomic-db/evidence/source-41141810291.json",
        "ohm-gnu-atomic-db/source/source.json",
        "ohm-aarch64-portable-review/source/sdk-members.json",
        "ohm-gnu-syscall/source-rebuild/rebuild.py",
        "ohm-gnu-syscall/source-rebuild/elf.py",
        "ohm-gnu-syscall/bootstrap.py",
        "ohm-gnu-syscall/restore_prior.py",
        "ohm-gnu-syscall/paired.py",
        "ohm-gnu-syscall/watch.c",
        "ohm-gnu-syscall/calibrate.c",
        "ohm-musl-ast/sdk.py",
        "ohm-musl-ast/ruff_loop.py",
        "ohm-musl-ast-pair/lookup.py",
        "ohm-musl-ast-pair/restore.py",
        "ohm-musl-ast-pair/subjects.py",
        "ohm-musl-ast-pair/rustdoc_audit.py",
        "ohm-musl-ast-pair/source.json",
        "ohm-musl-ast-pair/parent.json",
    ]
    if provider:
        scripts += [
            "ohm-musl-ast-pair/composite.py",
            "ohm-musl-ast-pair/original-source-and-ordinary.json",
            "ohm-musl-ast-pair/prior-native-replay.json",
        ]
    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        manifest = {}
        for n in scripts:
            body = subprocess.check_output(
                ["git", "-C", repo, "show", rev + ":scripts/" + n], env={**os.environ, "GIT_NO_LAZY_FETCH": "1"}
            )
            dest = root / n
            dest.parent.mkdir(exist_ok=True, parents=True)
            dest.write_bytes(body)
            manifest[n] = c.sha(body)
        src = root / "ohm-gnu-syscall"
        code = """import sys,os
from pathlib import Path
h=Path(sys.argv[1]);base=Path(sys.argv[2]);mode=sys.argv[3]
sys.path.insert(0,str(h))
import clocked as c
if mode=='calibration':
 sys.path.insert(0,str(base/'ohm-gnu-syscall'))
 import paired
 assert Path(paired.__file__).resolve()==base/'ohm-gnu-syscall/paired.py' and callable(paired.calibrate)
else:
 sys.path.insert(0,str(base/'ohm-musl-ast-pair'))
 import restore,lookup,rustdoc_audit
 if sys.argv[4]=="provider":
  import composite
  assert Path(composite.__file__).resolve()==base/'ohm-musl-ast-pair/composite.py'
  import json
  prior=json.loads((Path(composite.__file__).parent/'prior-native-replay.json').read_bytes())
  assert prior['run']==41172642028 and prior['head']=='c836892dbb9d4dca937c4a7cab9442eaa585b53b'
 sys.path.insert(0,str(base/'ohm-musl-ast'))
 import ruff_loop as r
 assert Path(rustdoc_audit.__file__).resolve()==base/'ohm-musl-ast-pair/rustdoc_audit.py'
 assert len(restore.q.PREVIOUS['files'])==183
 assert r.s.rt.SDK==Path(os.environ['RUNNER_TEMP'])/'ohm-aarch64-linux-zmij/rustup/toolchains/ohm'
 assert r.census.qualify.rt.SDK==restore.SDK
 assert r.s.rt.WILD.endswith('/wild-ld/ld.bfd') and r.s.rt.WILD in restore.q.PREVIOUS['files']
 assert all(callable(f) for f in (lookup.locate,restore.restore,r.prepare,r.training,r.client,r.census.trace_build,r.census.qualify.native))
"""
        for phase in ("calibration", "role"):
            env = {k: v for k, v in os.environ.items() if k != "QA_ROOT"} | {"RUNNER_TEMP": t}
            subprocess.run([sys.executable, "-IB", "-c", code, HERE, root, phase, "provider" if provider else "source"], env=env, check=True)
        c.require(
            {n: manifest["ohm-gnu-syscall/" + n] for n in c.COUNTER_SOURCES} == c.COUNTER_SOURCES,
            "counter source changed",
        )
        return manifest


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("packaging", type=Path)
    p.add_argument("prior_rust_285_zip", type=Path)
    args = p.parse_args()
    print(
        json.dumps(
            {
                "historical_physical": structural(args.prior_rust_285_zip),
                "separate_native_and_typed_controls": distinct_surfaces(args.prior_rust_285_zip),
                "original_compiler_and_ordinary_qualification_head": ingress.SOURCE_HEAD,
                "provider_qualification_head": ingress.PROVIDER_HEAD,
                "original_source_imports": imports(args.packaging, ingress.SOURCE_HEAD),
                "exact_imported_sources": imports(args.packaging, ingress.PROVIDER_HEAD, provider=True),
            },
            indent=2,
            sort_keys=True,
        )
    )
