"""Fresh native Ruff A, edited B, immediate repeat and independently empty B for each compiler."""

import gzip, json, os, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from binding import need, sha, digest, save, job
from ast_records import open_obj, expansions

GRAPH = json.loads(gzip.decompress((HERE / "inputs/ast-units.json.gz").read_bytes()))
PHASES = (("cold-A", "A"), ("edit-B", "B"), ("unchanged-B", "B"), ("empty-B", "B"))
MACROS = {"is_macro", "rustversion", "thiserror_impl"}
CLI = [
    "cargo",
    "+ohm",
    "build",
    "-p",
    "ruff_python_ast",
    "--lib",
    "--locked",
    "--offline",
    "-j2",
    "--message-format=json",
]


def gz(path, data):
    with path.open("xb") as f:
        f.write(gzip.compress(data, compresslevel=2, mtime=0))


def read_body(root, key):
    raw = gzip.decompress((root / (key + ".gz")).read_bytes())
    need(digest(raw) == key, "CAS digest differs from physical asset")
    return raw


def put(root, p):
    raw = p.read_bytes()
    key = digest(raw)
    dst = root / (key + ".gz")
    if dst.exists():
        need(read_body(root, key) == raw, "CAS collision")
    else:
        gz(dst, raw)
    return key


def execute(args, cwd, env, folder, name, rc=0):
    args = list(map(str, args))
    child = subprocess.run(args, cwd=cwd, env=env, capture_output=True)
    gz(folder / (name + ".stdout.gz"), child.stdout)
    gz(folder / (name + ".stderr.gz"), child.stderr)
    save(
        folder / (name + ".json"),
        dict(
            argv=args,
            cwd=str(cwd),
            exit=child.returncode,
            stdout=digest(child.stdout),
            stderr=digest(child.stderr),
        ),
    )
    need(child.returncode == rc, (name, child.returncode, child.stderr[-1400:]))
    return child


def archive(p):
    from archive_fields import analyze

    v, _ = analyze(p.read_bytes())
    need(
        subprocess.check_output(["ar", "t", p], text=True).splitlines() == list(v["members"]),
        "ar disagrees with physical member sequence",
    )
    return v


def roles(events, tree, work, cas):
    rows = [r for r in events if r["reason"] == "compiler-artifact"]
    scripts = [r for r in events if r["reason"] == "build-script-executed"]
    need(events[-1] == {"reason": "build-finished", "success": True}, "no native Cargo completion")

    need(
        not any(r["reason"] == "compiler-message" for r in events),
        "unexpected diagnostic in previously clean AST build",
    )

    def confined(path, directory=False):
        p = Path(path)
        need(
            (p.is_dir() if directory else p.is_file())
            and p.resolve() == p
            and any(p.is_relative_to(work / sub) for sub in ("target", "build")),
            ("foreign Cargo artifact", p),
        )
        return str(p.relative_to(work))

    units = []
    deps = set()
    macros = {}
    root = []
    for r in rows:
        t = r["target"]
        files = list(map(Path, r["filenames"]))
        role = [
            r["package_id"].replace(str(tree), "/__ENROLLED_RUFF__"),
            t["name"],
            t["kind"],
            t["crate_types"],
            r["features"],
            r["profile"],
        ]
        units.append([role, [confined(f) for f in files], r["fresh"]])
        if r["executable"]:
            confined(r["executable"])
        deps.update(p.parent for p in files if p.suffix in (".rlib", ".rmeta", ".so"))
        if t["kind"] == ["proc-macro"]:
            (so,) = [p for p in files if p.suffix == ".so"]
            macros[t["name"]] = put(cas, so)
        if t["name"] == "ruff_python_ast" and t["kind"] == ["lib"]:
            root.append(files)
    units.sort(key=lambda u: json.dumps(u[0], sort_keys=True))
    need(
        [u[0] for u in units] == GRAPH["roles"]
        and sorted(r["package_id"] for r in scripts) == GRAPH["scripts"]
        and len(units) == 36
        and len(scripts) == 5
        and set(macros) == MACROS
        and len(root) == 1,
        "wrong ordinary 41-unit Ruff closure",
    )
    script_out = {r["package_id"]: confined(r["out_dir"], True) for r in scripts}
    (meta,) = [p for p in root[0] if p.suffix == ".rmeta"]
    (rlib,) = [p for p in root[0] if p.suffix == ".rlib"]
    return units, script_out, macros, sorted(deps), meta, rlib


def typed(env, tree, work, folder, cas, branch, rlib, depdirs):
    width = 64 if branch == "A" else 56
    base = [
        "rustc",
        "+ohm",
        "--edition=2024",
        "--crate-name",
        "ast_width_reader",
        "--error-format=json",
        "--extern",
        "ruff_python_ast=" + str(rlib),
        *[v for p in depdirs for v in ("-L", "dependency=" + str(p))],
    ]
    source = work / "reader.rs"
    output = work / "reader-bin"
    result = {}
    for n, correct in ((width, True), (120 - width, False)):
        src = (HERE / "inputs/reader.rs.in").read_text().replace("@WIDTH@", str(n))
        source.write_text(src)
        (folder / ("positive.rs" if correct else "negative.rs")).write_text(src)
        output.unlink(missing_ok=True)
        c = execute(
            base + ([] if correct else ["--emit=metadata"]) + ["-o", output, source],
            tree,
            env,
            folder,
            "correct" if correct else "contradictory",
            0 if correct else 1,
        )
        if correct:
            result["elf"] = put(cas, output)
            for ext, kind in (("pyi", "Some(Stub)"), ("qno", "None")):
                value = execute([output, ext], tree, env, folder, "run-" + ext).stdout
                need(value == f"{width} {kind}\n".encode(), "wrong native Ruff verdict")
                result[ext] = value.decode().strip()
        else:
            diags = [json.loads(l) for l in c.stderr.splitlines()]
            errors = [d for d in diags if d["level"] == "error" and d["code"]]
            need(
                not output.exists()
                and [
                    (d["code"]["code"], [s["file_name"] for s in d["spans"] if s["is_primary"]])
                    for d in errors
                ]
                == [("E0308", [str(source)])]
                and b"internal compiler error" not in c.stderr,
                "missing precise contradictory Rust diagnostic",
            )
            result["negative"] = digest(c.stderr)
    return result


def projection(a, b, role):
    need(
        role in ("E", "C")
        and (a["name"], a["private"], a["global_fp"], a["stable"])
        == (b["name"], b["private"], b["global_fp"], b["stable"])
        and a["defs"].keys() == b["defs"].keys(),
        "different source/private/global or stable set",
    )
    changed = 0
    reachable = 0
    indices = 0
    for k, x in a["defs"].items():
        y = b["defs"][k]
        need(
            x["path"] == y["path"] and (x["fp"] is None) == (y["fp"] is None), "different path/reachability"
        )
        changed += x["fp"] != y["fp"]
        reachable += x["fp"] is not None
        indices += x["id"] != y["id"]
    ex = expansions(a)
    need(
        ex == expansions(b) and (len(a["defs"]), reachable, len(ex)) == (18142, 17431, 3589),
        "wrong Ruff source/expansion inventory",
    )
    need(
        changed == (10150 if role == "E" else 0) and ((a["public"] != b["public"]) == (role == "E")),
        "baseline drift not reproduced or candidate public surface still changes",
    )
    return dict(
        role=role,
        public=[a["public"], b["public"]],
        private=a["private"],
        global_hash=a["global_fp"],
        def_keys=len(a["defs"]),
        reachable=reachable,
        expansion_keys=len(ex),
        renumbered_indices=indices,
        changed_def_hashes=changed,
        allocations=[len(o["allocs"]) for o in (a, b)],
        raw_rmeta_equal=a["raw"] == b["raw"],
    )


def validate_repeat(before, repeat):
    need(
        all(before[k] == repeat[k] for k in ("rlib", "rmeta", "listing", "client", "macros")),
        "fresh repeat did not retain exactly the same artifacts, macros and client",
    )


def compare(info, root, case):
    w = info[(case, "edit-B")]
    validate_repeat(w, info[(case, "unchanged-B")])
    return pair(w, info[(case, "empty-B")], root, case)


def pair(w, e, root, case):
    native = lambda r: (r["archive"]["object_order"], r["archive"]["object_sha256"])
    need(
        len(native(w)[0]) == 94
        and native(w) == native(e)
        and w["client"] == e["client"]
        and w["macros"] == e["macros"],
        "native warm/empty or actual proc-macro input differs",
    )
    opened = [
        open_obj(
            read_body(root / "bodies", r["rmeta"]),
            gzip.decompress((root / case / r["phase"] / "root.stdout.gz").read_bytes()).decode(),
        )
        for r in (w, e)
    ]
    p = projection(*opened, case)
    return {
        **p,
        "matching_native_objects": len(native(w)[0]),
        "raw_rlib_equal": w["rlib"] == e["rlib"],
        "metadata_object_equal": w["archive"]["members"]["lib.rmeta"]
        == e["archive"]["members"]["lib.rmeta"],
        "link_metadata_equal": w["archive"]["members"]["lib.rmeta-link"]
        == e["archive"]["members"]["lib.rmeta-link"],
        "client": w["client"],
    }


def main():
    job()
    sys.path[:0] = [str(HERE.parent / "branch-return-pmu"), str(HERE.parent / "ohm-packed-ruff")]
    import bindings as b
    import study as kit

    root = b.OUT / "ast"
    root.mkdir()
    cas = root / "bodies"
    cas.mkdir()
    env = b.environment("Eoff", permitted={"Eoff"})
    del env["CARGO_BUILD_BUILD_DIR"]
    b.PROXIES.mkdir(parents=True, exist_ok=True)
    real = Path(shutil.which("rustup")).resolve(strict=True)
    for n in ("rustup", "cargo", "rustc", "rustdoc"):
        target = b.PROXIES / n
        if target.exists():
            need(sha(target) == sha(real), "foreign proxy")
        else:
            shutil.copy2(real, target)
    (b.HOME / ".cargo/config.toml").write_text(
        "[build]\nbuild-dir = " + json.dumps(str(b.WORK / "build")) + "\n"
    )

    def alias(case):
        if b.SDK.is_symlink():
            b.SDK.unlink()
        b.SDK.symlink_to(b.PARK / case, target_is_directory=True)
        record = json.loads((b.OUT / "sdk" / (case + ".json")).read_bytes())
        need(
            b.inventory(b.PARK / case) == record["files"]
            and Path(
                subprocess.check_output(["rustc", "+ohm", "--print", "sysroot"], env=env, text=True).strip()
            ).samefile(b.PARK / case),
            "wrong actual role",
        )
        return record

    alias("E")
    b.prepare_inputs(kit, env)
    changed = kit.git(
        "diff", "--name-only", *kit.REVS.values(), "--", "crates/ruff_python_ast"
    ).splitlines()
    need(len(changed) == 9, "not the historical AST layout change")
    summary = {}
    data = {}
    for case in ("E", "C"):
        rec = alias(case)
        (root / case).mkdir()
        for phase, branch in PHASES:
            where = root / case / phase
            where.mkdir()
            kit.git("switch", "--quiet", kit.NAMES[branch])
            need(
                kit.git("rev-parse", "HEAD") == kit.REVS[branch] and not kit.git("status", "--porcelain"),
                "dirty Ruff tree",
            )
            if phase in ("cold-A", "empty-B"):
                b.fresh_outputs()
            raw = execute(CLI, kit.TREE, env, where, "cargo")
            units, scripts, macros, dirs, meta, rlib = roles(
                [json.loads(v) for v in raw.stdout.splitlines()], kit.TREE, b.WORK, cas
            )
            dirty = sorted(x[0][1] for x in units if not x[2])
            need(
                (
                    len(dirty) == 36
                    if phase in ("cold-A", "empty-B")
                    else dirty == (["ruff_python_ast"] if phase == "edit-B" else [])
                ),
                "wrong native rebuild scope",
            )
            listing = execute(["rustc", "+ohm", "-Zls=root", rlib], kit.TREE, env, where, "root")
            result = dict(
                phase=phase,
                branch=branch,
                driver=rec["files"][rec["driver"]][0],
                source=kit.REVS[branch],
                rmeta=put(cas, meta),
                rlib=put(cas, rlib),
                listing=digest(listing.stdout),
                archive=archive(rlib),
                client=typed(env, kit.TREE, b.WORK, where, cas, branch, rlib, dirs),
                units=units,
                build_scripts=scripts,
                macros=macros,
            )
            save(where / "result.json", result)
            data[case, phase] = result
        summary[case] = compare(data, root, case)
    for phase, branch in PHASES:
        e, c = (data[r, phase] for r in ("E", "C"))
        need(
            e["source"] == c["source"]
            and e["client"] == c["client"]
            and e["macros"] == c["macros"]
            and [i[:2] for i in e["units"]] == [i[:2] for i in c["units"]]
            and e["build_scripts"] == c["build_scripts"],
            "cross-source client, proc-macro or returned path changed",
        )
        need(
            e["archive"]["object_order"] == c["archive"]["object_order"]
            and e["archive"]["object_sha256"] == c["archive"]["object_sha256"],
            "cross-source native AST objects changed",
        )
    need(summary["C"]["public"][1] == summary["E"]["public"][1], "candidate changed clean public hash")
    save(
        root / "qualified.json",
        dict(subjects=summary, source_files=changed, proxy=sha(real), cli=CLI, counts=None),
    )


if __name__ == "__main__":
    main()
