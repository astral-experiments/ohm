"""Repeat genuine fresh-source unit encodings with all actual direct inputs held physically fixed."""

from pathlib import Path
import os
import shutil
import subprocess
import service as s
import collector as cc
import oracles as oo

m = s.m
SCRATCH_FLOOR = 12 * 2**30


def target_reset():
    assert m.TARGET == m.ROOT / "target" and not m.TARGET.is_symlink()
    if m.TARGET.exists():
        shutil.rmtree(m.TARGET)


def make_seed(path):
    assert (
        m.TARGET.is_dir()
        and not path.exists()
        and shutil.disk_usage(path.parent).free > SCRATCH_FLOOR
    )
    subprocess.run(
        [
            "tar",
            "--format=posix",
            "-I",
            "zstd -1 -T2",
            "-cf",
            str(path),
            "-C",
            m.ROOT,
            m.TARGET.name,
        ],
        check=True,
        timeout=240,
    )
    assert 2**20 < path.stat().st_size < 3 * 2**30
    return dict(bytes=path.stat().st_size, sha256=m.filesha(path))


def restore(path, ref):
    assert (
        path.stat().st_size == ref["bytes"]
        and m.filesha(path) == ref["sha256"]
        and shutil.disk_usage(m.ROOT).free > SCRATCH_FLOOR
    )
    target_reset()
    subprocess.run(
        ["tar", "-I", "zstd -d", "-xf", path, "-C", m.ROOT], check=True, timeout=240
    )
    assert m.TARGET.is_dir()


def certify(out, role, owner, baseline, blobs, parser, classes):
    out.mkdir()
    ref = baseline["fresh"]
    forms = m.read(baseline["forms"])
    (original,) = forms[owner]
    known = s.case["known_physical_kinds"][owner]
    units = Path(original[original.index("--out-dir") + 1]).parent
    assert (
        units.parent == m.TARGET / "debug/build" / owner.replace("_", "-")
        and len(units.name) == 16
    )
    (key,) = [
        p for p in ref["workspace"] if Path(p).name.startswith("lib" + owner + "-")
    ]
    before = ref["workspace"][key]
    source_baseline = baseline["witness"]
    variants = {}
    rows = {}
    fixed = None
    all_moved = set()
    for idx, nt in enumerate((8, 1, 1, 8)):
        d = out / (str(idx) + "-" + str(nt))
        logs = out / (str(idx) + "-processes")
        logs.mkdir()
        restore(baseline["archive"], baseline["seal"])
        assert (
            cc.source("B")["tree"] == s.case["trees"]["B"]
            and cc.store(m.TARGET / key, blobs) == before
        )
        files = {str(f): cc.store(f, blobs) for f in sorted(set(cc.externs(original)))}
        if fixed is None:
            fixed = files
        assert files == fixed
        (inc,) = (m.TARGET / "debug/incremental").glob(owner + "-*")
        assert (
            inc.parent == m.TARGET / "debug/incremental"
            and (units / "fingerprint").is_dir()
        )
        shutil.rmtree(inc)
        shutil.rmtree(units)
        env = dict(
            m.ENV,
            RUSTC_WRAPPER=str(s.HERE / "fixed-wrapper.py"),
            OHM_22958_FORMS=str(baseline["forms"]),
            OHM_22958_OWNER=owner,
            OHM_22958_THREADS=str(nt),
            OHM_22958_LOGS=str(logs),
        )
        cc.checked_run(s.CHECK, d, env=env)
        marks = [m.read(f) for f in sorted(logs.glob("*.json"))]
        (selected,) = [x for x in marks if x["name"] == owner]
        assert (
            selected["cwd"] == str(m.SRC)
            and selected["inputs"] == fixed
            and selected["executed"] == selected["original"] + ["-Zthreads=" + str(nt)]
        )
        assert fixed == {
            str(f): cc.store(f, blobs) for f in sorted(set(cc.externs(original)))
        }
        current = cc.store(m.TARGET / key, blobs)
        variants[current[1]] = current
        test = oo.probes(d / "independent-consumer", "B", role)
        assert oo.observables(test) == oo.observables(source_baseline)
        if current != before:
            cmp = parser["check_delta"](before, current, owner)
            assert all(cmp["checks"].values()) and set(cmp["physical_moved"]) <= set(
                known
            )
            all_moved.update(cmp["physical_moved"])
        else:
            cmp = {"raw_exact": True}
        rows[str(idx)] = dict(
            threads=nt,
            rmeta=current,
            original_argv=selected["original"],
            fixed_inputs=files,
            all_other_units=[i["name"] for i in marks if i != selected],
            comparison=cmp,
        )
    # Fresh one-/eight-thread choices need to produce the actually encountered physical class,
    # with native public data and independently linked behavior passing in every visit.
    assert len(variants) >= 2 and set(classes) <= all_moved, (
        owner,
        len(variants),
        sorted(all_moved),
        classes,
    )
    result = dict(
        qualified=True,
        owner=owner,
        source=s.case["B"],
        stable_inputs=fixed,
        coverage=sorted(all_moved),
        rows=rows,
    )
    m.save(out / "fixed.json", result)
    return result
