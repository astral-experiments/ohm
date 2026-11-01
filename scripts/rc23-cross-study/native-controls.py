"""Run the release's declared native library checks on the two cross compilers."""
import os
import shutil
import subprocess
import sys

import measure as m

EXPECTED_FIXTURE = "bdce62a78b5e7176730c99b692262df79f755c11963649cb8bc3ddcc7f35824e"


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise ValueError(f"Release fixture changed around {before!r}")
    return text.replace(before, after)


def platform_fixture(original):
    # Reuse the two-executable release fixture. The separate asm cases already run in direct.py.
    text = original.split("check_output() {", 1)[0] + original[original.index("# Both binaries call into the same native archive."):]
    # Cargo inspects the parent manifest when discovering a workspace for the nested probe.
    text = replace_once(text, "# Both binaries call", "printf 'fn main() {}\\n' >src/main.rs\nprintf 'pub fn value() {}\\n' >engine/src/lib.rs\n# Both binaries call")
    text = replace_once(text, 'host=$(rustc +"$toolchain" -vV | awk \'/^host: / {print $2}\')', 'host="$OHM_QUAL_TARGET"')
    text = replace_once(text, 'exec cc "$@"', 'exec "$OHM_QUAL_CC" "$@"')
    text = replace_once(text, '| cc -x c -c', '| "$OHM_QUAL_CC" -x c -c')
    text = replace_once(text, 'ar rcs next-answer.a', '"$OHM_QUAL_AR" rcs next-answer.a')
    text = replace_once(text, 'actual=$("$CARGO_TARGET_DIR/debug/$bin")', '''if [[ -n "$OHM_QUAL_QEMU" ]]; then
      actual=$("$OHM_QUAL_QEMU" -L /usr/aarch64-linux-gnu "$CARGO_TARGET_DIR/$host/debug/$bin")
    else
      actual=$("$CARGO_TARGET_DIR/$host/debug/$bin")
    fi''')
    text = replace_once(text, 'core::arch::asm!("/* {0} */", in(reg) value, options(nomem, nostack, preserves_flags));',
                        'core::arch::asm!("/* {value} */", value = in(reg) value, options(nomem, nostack));')
    anchor = '  if (( $# == 1 )); then'
    text = replace_once(text, anchor, '''  count=$(wc -l <"$OHM_SMOKE_LINK_LOG")
  expected=any
  if (( $# == 2 )); then expected=$2; fi
  printf '%s\\t%s\\t%s\\t%s\\n' "$(basename "$CARGO_TARGET_DIR")" "$1" "$expected" "$count" >> "$OHM_QUAL_COUNTS"
  # The control compiler may conservatively relink an unchanged, unrecognized asm dependency.
  if [[ "$OHM_QUAL_ARM" == base && "$CARGO_TARGET_DIR" == */marked-declared-target && "$expected" == 0 ]]; then
    return
  fi
''' + anchor)
    anchor = '# Leave the archive off the build script'
    text = replace_once(text, anchor, '''# A deleted, explicitly declared archive must fail before the next executable can run.
mv -- native/libanswer.a declared-previous.a
if cargo +"$toolchain" build --bins --offline >"$OHM_QUAL_EVIDENCE/missing-declared.log" 2>&1; then
  echo "Build succeeded with a missing declared libanswer.a" >&2
  exit 1
fi
grep -F 'answer' "$OHM_QUAL_EVIDENCE/missing-declared.log" >/dev/null
mv -- declared-previous.a native/libanswer.a
check_links 29
''' + anchor)
    return text.replace('cargo +"$toolchain"', '"$OHM_QUAL_CARGO"')


def main(kind):
    assert kind in m.P["cases"]
    assert os.environ["GITHUB_REPOSITORY"] == "astral-experiments/ohm"
    assert os.environ["GITHUB_EVENT_NAME"] == "workflow_dispatch"
    assert os.environ["GITHUB_SHA"] == os.environ["REVIEWED_HEAD"]
    for path in (m.WORK, m.OUT, m.WORK / "home", m.WORK / "tmp"):
        path.mkdir()
    target = m.install(kind)
    original = m.HERE / "fixtures/release-relink.sh"
    actual = m.sha(original)
    assert actual == EXPECTED_FIXTURE
    fixture = m.OUT / "cross-declared-relink.sh"
    fixture.write_text(platform_fixture(original.read_text()))
    reports = {}
    for arm in m.ARMS:
        m.switch(arm)
        sdk = m.WORK / ("sdk-" + arm)
        path = m.OUT / arm
        path.mkdir()
        project = m.WORK / ("probe-" + arm)
        counts = path / "links.tsv"
        env = m.env(target)
        env.update(
            CARGO_HOME=str(m.WORK / ("cargo-" + arm)),
            CARGO_BUILD_TARGET=target,
            OHM_QUAL_TARGET=target,
            OHM_QUAL_CARGO=str(sdk / "bin/cargo"),
            OHM_QUAL_CC=shutil.which("aarch64-linux-gnu-gcc" if kind == "gnu" else "musl-gcc"),
            OHM_QUAL_AR=shutil.which("aarch64-linux-gnu-ar" if kind == "gnu" else "ar"),
            OHM_QUAL_QEMU=shutil.which("qemu-aarch64") if kind == "gnu" else "",
            OHM_QUAL_ARM=arm, OHM_QUAL_EVIDENCE=str(path), OHM_QUAL_COUNTS=str(counts),
        )
        result = subprocess.run(["bash", str(fixture), arm, str(project)], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (path / "fixture.log").write_bytes(result.stdout)
        rows = []
        if counts.exists():
            for line in counts.read_text().splitlines():
                group, value, expected, links = line.split("\t")
                rows.append(dict(case=group, output=int(value), expected=expected, links=int(links)))
        bad = project / "declared/bad-archive.log"
        if bad.exists():
            shutil.copyfile(bad, path / "malformed-archive.log")
        products = {}
        if result.returncode == 0:
            for name in ("first", "second"):
                binary = project / "declared/shadow-target" / target / "debug" / name
                elf = subprocess.check_output(["readelf", "-h", "-l", str(binary)])
                (path / (name + "-elf.txt")).write_bytes(elf)
                assert (b"AArch64" if kind == "gnu" else b"X86-64") in elf
                if kind == "musl":
                    assert b"ld-linux" not in elf
                products[name] = m.sha(binary)
        reports[arm] = dict(exit=result.returncode, rows=rows, products=products,
                            log_sha256=m.sha(path / "fixture.log"))
        m.dump(m.OUT / "outcomes.json", reports)
        print(kind, arm, result.returncode, len(rows), flush=True)
        if result.returncode:
            print(result.stdout.decode(errors="replace")[-2200:], flush=True)
    if any(v["exit"] for v in reports.values()):
        raise RuntimeError("See both compiler outcomes for the failed cross-target control.")
    for arm, entry in reports.items():
        rows = entry["rows"]
        for group in ("target", "marked-declared-target"):
            checks = [(r["output"], r["expected"], r["links"]) for r in rows if r["case"] == group and r["expected"] != "any"]
            assert [(v, e) for v, e, _ in checks] == [(17, "0"), (29, "2"), (29, "0")]
            if arm == "cross" or group == "target":
                assert all(n == int(e) for _, e, n in checks)
            else:
                assert checks[1][2] == 2
        assert [(r["output"], r["links"]) for r in rows if r["case"] == "shadow-target" and r["expected"] == "2"] == [(41, 2), (29, 2)]
        assert (m.OUT / arm / "missing-declared.log").is_file()
        assert (m.OUT / arm / "malformed-archive.log").is_file()
    m.dump(m.OUT / "verified-native.json", dict(
        run=os.environ["GITHUB_RUN_ID"], head=os.environ["GITHUB_SHA"],
        fixture_sha256=actual, adapted_sha256=m.sha(fixture), target=target, results=reports,
    ))


if __name__ == "__main__":
    main(sys.argv[1])
