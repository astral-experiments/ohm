"""Compare executed RUSTDOC, denied namespaces, and real library compilers with signed Ruff data."""

from pathlib import Path
import gzip, io, json, re, sys, zipfile

D = Path(__file__).resolve().parent
sys.path.insert(0, str(D))
import reopen as a

FROZEN_OLD = "e2dffc67a5a3eeab53b8e1fcded93f7896dc325c"
MARK = ".ohm-worktree-seed-deny-v7"


def marker(bs, d):
    table = a.J(gzip.decompress(bs[d + "/allocated-ledger.gz"]))
    return {
        Path(v[0]).name: [v[0], v[5]]
        for v in table
        if Path(v[0]).name in (MARK, ".ohm-worktree-seed-v7")
    }


def execution(bs, place, tools):
    prefix = place + "/kernel/"
    execs = []
    for row in bs[prefix + "exec.tsv"].decode().splitlines():
        n, pid, dev, ino, hit, img = row.split("\t")
        blob = bs[prefix + "args-" + n.zfill(4)]
        assert blob.endswith(b"\0")
        args = blob[:-1].decode().split("\0")
        if (
            [int(dev), int(ino)] == tools["rustc"]["dev_ino"]
            and "--crate-name" in args
            and "--out-dir" in args
            and not any(f.startswith("--print") for f in args)
        ):
            execs.append([int(pid), args[args.index("--crate-name") + 1]])
    v = a.J(bs[place + "/build.json"])
    assert v["physical_rustcs"] == execs
    return execs


def main(old, d):
    out = {}
    for row in ("01", "02"):
        src = d / ("actual-compiler-loop-" + row)
        sm = a.J(src.with_suffix(".json").read_bytes())
        b = a.opened(src.with_suffix(".zip").read_bytes(), sm, row)
        staged = {}
        for arm in a.ORDER[row]:
            r, lv = arm
            root = "opt" + arm
            rt = a.J(b[root + "/runtime.json"])
            sl = a.J(b[rt["record"] + "/selection.json"])
            vr = a.J(b["native-manifest-" + r + ".json"])
            assert not any(Path(x).name == "rustdoc" for x in vr["files"])
            sysroot = Path(sl["sysroot"])
            assert (
                sysroot.parent.name == "ordinary-ron-check" and sysroot.name == "sdk-21"
            )
            p = a.J(b[root + "/actual-cargo-driver/neutral-generator.json"])["path"]
            lines = gzip.decompress(
                b[root + "/actual-cargo-driver/all-process-opens.gz"]
            ).splitlines()
            ex = []
            for line in lines:
                match = re.match(rb'^(\d+) execve\("([^"]+)",', line)
                if match and match[2].decode() == p and line.endswith(b"= 0"):
                    values = [
                        x.decode()
                        for x in re.findall(
                            rb'"((?:RUSTDOC|RUSTUP_HOME|RUSTUP_TOOLCHAIN)=[^"]*)"', line
                        )
                    ]
                    assert [t for t in values if t.startswith("RUSTDOC=")] == [
                        "RUSTDOC=rustdoc"
                    ]
                    ex.append([int(match[1]), p, values])
            assert len(ex) == 1
            check = {n: marker(b, root + "/" + n) for n in a.SCORE}
            observed = {
                "physical_sysroot": str(sysroot),
                "kit_manifests_contain_rustdoc": False,
                "build_script_exec_and_environment": ex,
                "check_markers": check,
            }
            if lv == ("0" if row == "01" else "2"):
                base = "linked-opt" + lv + "/opt" + str("PC".index(r))
                sel = {
                    n: marker(b, base + "/" + n)
                    for n in (
                        "cold",
                        "neutral-unchanged",
                        "historical-hunk",
                        "first-unchanged",
                    )
                }
                assert all(
                    v[MARK][1] == 30 and v[".ohm-worktree-seed-v7"][1] == 2
                    for v in sel.values()
                )
                observed["link_markers"] = sel
                observed["compiled"] = execution(
                    b, base + "/traced-repeat", rt["tools"]
                )
            staged[arm] = observed
        src = old / ("one-package-" + row)
        sm2 = a.J(src.with_suffix(".json").read_bytes())
        bits = src.with_suffix(".zip").read_bytes()
        assert (
            sm2["digest"] == "sha256:" + a.h.sha(bits)
            and len(bits) == sm2["size_in_bytes"]
        )
        with zipfile.ZipFile(io.BytesIO(bits)) as z:
            assert z.testzip() is None
            v = a.h.unpack(z.read(z.namelist()[0]))
        now = {}
        for i in ("0", "1"):
            root = "ordinary-lib/opt" + i
            s = a.J(v["subjects.json"])
            cols = {}
            for n in (
                "cold",
                "neutral-unchanged",
                "historical-hunk",
                "first-unchanged",
            ):
                val = marker(v, root + "/" + n)
                assert {k for k in val} == {".ohm-worktree-seed-v7"}
                cols[n] = val
            states = {}
            for n in (
                "neutral-unchanged",
                "historical-hunk",
                "first-unchanged",
                "traced-repeat",
                "independent-empty",
            ):
                z = a.J(v[root + "/" + n + "/build.json"])
                states[n] = {
                    "rlib_attestation": z["rlib"][1],
                    "reader": z["reader_elf"]["sha256"],
                    "dirty": z["dirty"],
                }
            actual = execution(v, root + "/traced-repeat", s["tools"])
            assert len(actual) == 1 and actual[0][1] == "build_script_build"
            assert (
                len(
                    {
                        k["rlib_attestation"]
                        for n, k in states.items()
                        if n != "independent-empty"
                    }
                )
                == 1
            )
            assert len({k["reader"] for k in states.values()}) == 1
            now[i] = {"markers": cols, "traced_physical": actual, "returned": states}
        out[row] = {
            "current": staged,
            "signed_baseline_zip": sm2,
            "signed_complete_previous": now,
        }
    return {
        "cargo": a.h.CARGO,
        "historical_evidence": FROZEN_OLD,
        "current_head": a.HEAD,
        "current_run": a.RUN,
        "rows": out,
    }


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("historical_packet", type=Path)
    p.add_argument("--current", type=Path, default=D)
    p.add_argument("--out", type=Path)
    v = p.parse_args()
    doc = main(v.historical_packet, v.current)
    result = json.dumps(doc, indent=2, sort_keys=True) + "\n"
    if v.out:
        v.out.write_text(result)
    else:
        print(result, end="")
