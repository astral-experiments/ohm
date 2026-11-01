"""Outside the comment endpoint, require an actual CLI behavior change under the same Cargo selector."""

import gzip
import json
from pathlib import Path
import subprocess

import contract as q


def observe(h, s, cli, env, out, edited):
    result = {}
    for case in s.CASES:
        argv = [str(cli), *s.argv(case)]
        p = subprocess.run(argv, input=s.SOURCE, env=env, cwd=h.kit.TREE, capture_output=True, timeout=30)
        for k, body in [("stdout", p.stdout), ("stderr", p.stderr)]:
            (out / f"stub-{case}.{k}.gz").write_bytes(gzip.compress(body, mtime=0))
        h.save(
            out / f"stub-{case}.json",
            dict(
                argv=argv,
                cwd=str(h.kit.TREE),
                exit=p.returncode,
                stdin=q.sha(s.SOURCE),
                stdout=q.sha(p.stdout),
                stderr=q.sha(p.stderr),
            ),
        )
        result[case] = s.verdict(case, edited, p.returncode, p.stdout, p.stderr, h.kit.TREE)
    return result


def source(h, s):
    repo = h.kit.TREE
    want = {
        "ref": h.kit.NAMES["B"],
        "commit": h.kit.REVS["B"],
        "tree": h.kit.TREES["B"],
        "modified": sorted([s.AST, h.routes.NODES]),
        "body": s.AFTER,
        "comment": h.routes.AFTER,
        "parser": s.GOOD,
    }
    obj = {
        "ref": q.git(repo, "symbolic-ref", "--short", "HEAD"),
        "commit": q.git(repo, "rev-parse", "HEAD"),
        "tree": q.git(repo, "rev-parse", "HEAD^{tree}"),
        "modified": q.git(repo, "diff", "--name-only").splitlines(),
        "body": h.sha(repo / s.AST),
        "comment": h.sha(repo / h.routes.NODES),
        "parser": h.sha(repo / s.PARSER),
    }
    expected_status = b"".join(b" M " + v.encode() + b"\n" for v in want["modified"])
    q.need(
        obj == want and s.git(repo, "status", "--porcelain=v1") == expected_status,
        "unexpected edited Ruff inputs",
    )
    return obj


def run(h, select, suite, observer, arm, env, top, old_owners, reset):
    s = q.semantics()
    baseline = json.loads((top / "repair/selected.json").read_bytes())["paths"]["cli"]
    observe(h, s, Path(baseline), env, top / "repair", False)
    previous = json.loads((top / "repair/visit.json").read_bytes())["products"]
    target = h.kit.TREE / s.AST
    wanted = None
    for phase in ("semantic-edit", "semantic-empty"):
        w = top / phase
        w.mkdir()
        if phase == "semantic-empty":
            h.save(w / "fresh.json", reset(h, env))
            h.routes.advance(h.kit.TREE, h.kit.NAMES, "clean-edited", "return")
        target.write_bytes(s.altered(target.read_bytes()))
        state = source(h, s)
        h.save(w / "source.json", state)
        events, count, phys = observer.invocation(w, env, 0, arm)
        q.need(
            count is None
            and any(r["crate"] == "ruff_python_ast" and r["mode"] == "full" for r in phys["rustcs"]),
            "no actual edited AST rustc",
        )
        q.install_boundary(
            observer.packages().reader.read(w / "kernel.tsv.gz", expected_code=0, expected_schema=3)[
                "execs"
            ]
        )
        cold = phase == "semantic-empty"
        rows, dirty = select.roster(events, h.kit.TREE)
        storage = h.original.disk.allocated(
            h.WORK / "target",
            h.WORK / "build",
            w,
            failed_sessions=h.original.failed_session.observed(h.WORK),
        )
        q.need(
            len(rows) == 390
            and not storage["failed_sessions"]
            and (not cold or (len(dirty) == 390 and storage["packed_files"] == 0)),
            "wrong edited workspace",
        )
        h.publish(w / "roster.json.gz", dict(units=rows, dirty=dirty))
        paths = select.selected_paths(events, h.kit.TREE, h.WORK)
        mapping = select.join_native(phys, paths, cold, {} if cold else old_owners, h.sha, True)
        filtered, providers = select.reader_stream(events, mapping, h.sha)
        identities = {}
        for role, path in paths.items():
            (link,) = mapping[role]["linked_by"]
            (row,) = (
                r
                for r in phys["wild_processes"]
                if r["pid"] == link["pid"] and r["output"] == link["path"]
            )
            (owner,) = (r for r in phys["rustcs"] if r["event"] == row["rustc_event"])
            q.need(
                owner["crate"] == ("ruff" if role == "cli" else "integration_test"),
                "wrong terminal linker owner",
            )
            identities[role] = {
                str(p): [p.stat().st_dev, p.stat().st_ino, p.stat().st_size, h.sha(p)]
                for p in (path, Path(link["path"]))
            }
        h.save(
            w / "selected.json",
            dict(
                paths={k: str(v) for k, v in paths.items()},
                owners=mapping,
                reader=providers,
                operands=q.operand_files(mapping, providers, h.sha),
                terminal_files=identities,
            ),
        )
        prod, files = h.original.native.observed(
            filtered, "B", h.kit.REVS["B"], env, h.ROOT, h.kit.TREE, h.WORK, w
        )
        files["harness"] = paths["harness"]
        images = {k: prod[k] for k in ("cli", "reader")} | {
            "harness": h.original.native.elf(paths["harness"])
        }
        h.save(w / "harness-elf.json", images["harness"])
        stubs = observe(h, s, paths["cli"], env, w, True)
        rec = dict(
            phase=phase,
            products={k: v["whole"] for k, v in images.items()},
            stubs=stubs,
            allocated=storage["allocated"],
            physical=q.identities(phys),
            wild_outputs=q.link_outputs(phys),
        )
        q.need(
            rec["products"]["cli"] != previous["cli"] and source(h, s) == state,
            "stale semantic executable or changed source",
        )
        for k, p in files.items():
            if wanted is None:
                h.original.native.preserve(p, images[k], h.original.BODIES, h.original.BUNDLE)
            else:
                h.original.native.same_file(p, images[k], wanted[k], h.original.BODIES, w)
        if wanted is None:
            wanted = images
        h.save(w / "semantic.json", rec)
        q.need(h.sha(target) == s.AFTER, "refusing to change unfamiliar semantic edit")
        s.git(h.kit.TREE, "restore", "--worktree", "--", s.AST)
    return [q.sha((top / p / "semantic.json").read_bytes()) for p in ("semantic-edit", "semantic-empty")]
