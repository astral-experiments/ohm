"""Run the new regression test against the exact preceding production code, then restore the child."""

import re

import binding as reg

PRODUCTION = "compiler/rustc_incremental/src/persist/fs.rs"
TESTS = "compiler/rustc_incremental/src/persist/fs/tests.rs"
NAME = "persist::fs::tests::resolve_complete_rows_at_the_start_of_large_packed_refs"
# D used this literal in branch_revision. The transplanted test alone needs a named constant.
SHIM = b"\nconst PACKED_REFS_LIMIT: usize = 64 * 1024;\n"
D_TESTS = {
    "persist::fs::tests::" + name
    for name in reg.UNITS
    if "persist::fs::tests::" + name != NAME
}


def registered_tests():
    original = reg.HERE / "inputs/parent-native-tests.txt"
    data = original.read_text().splitlines()
    reg.need(
        len(data) == len(set(data)) == 12 and D_TESTS <= set(data) and NAME not in data,
        "wrong recorded D suite",
    )
    return set(data)


def prior_suite(body):
    """Bind the 12 old test names to the genuine original stage1 test command's output."""
    reg.need(
        reg.digest(body)
        == "b1602dd24a39a3227e34e090bc0322a0199f0cf0f9987a7556d7c483d909f6c2"
        and set(re.findall(r"^test (\S+) \.\.\. ok$", body.decode(), re.M))
        == registered_tests(),
        "different genuine D test output",
    )


def outcomes(body, red):
    clean = re.sub(r"\x1b\[[0-9;]*m", "", body)
    tests = re.findall(r"^test (\S+) \.\.\. (ok|FAILED)$", clean, re.M)
    original = registered_tests()
    want = {n: "ok" for n in original} | {NAME: "FAILED" if red else "ok"}
    reg.need(
        len(tests) == len(want)
        and dict(tests) == want
        and clean.splitlines().count("running 13 tests") == 1
        and len(
            re.findall(
                r"^\s*Running unittests src/lib.rs \(.*?/out/rustc_incremental-[a-z0-9]+\)$",
                clean,
                re.M,
            )
        )
        == 1
        and len(re.findall(r"^test result:", clean, re.M)) == 1
        and "internal compiler error" not in clean
        and "error[E" not in clean,
        "wrong actual rustc_incremental test suite",
    )
    if red:
        reg.need(
            re.search(
                r"^test result: FAILED\. 12 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out;",
                clean,
                re.M,
            )
            and re.search(
                r"thread '"
                + re.escape(NAME)
                + r"'[^\n]*panicked at .*?fs/tests.rs:\d+:\d+:\s*assertion `left == right` failed\s*left: None\s*right: Some\("
                + str(0xABCDEF0123456789)
                + r"\)",
                clean,
            ),
            "old source did not reach the actual prior-hint assertion",
        )
    else:
        reg.need(
            re.search(
                r"^test result: ok\. 13 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out;",
                clean,
                re.M,
            ),
            "new source did not pass all 13 native tests",
        )
    return sorted(want)


def run(helper, repo, folder, argv, product):
    production = repo / PRODUCTION
    tests = repo / TESTS
    child_impl, child_tests = production.read_bytes(), tests.read_bytes()
    old_impl = reg.git(repo, "show", reg.OLD + ":" + PRODUCTION)
    old_tests = reg.git(repo, "show", reg.OLD + ":" + TESTS)
    blobs = product["source"]["blobs"]
    modified = child_tests + SHIM
    reg.need(
        child_tests.startswith(old_tests)
        and b"fn " + NAME.split("::")[-1].encode() + b"()"
        in child_tests[len(old_tests) :]
        and b"const PACKED_REFS_LIMIT" not in old_impl
        and b"64 * 1024).ok()?" in old_impl
        and all(
            reg.digest(raw) == blobs[path][role][1]
            for raw, path, role in (
                (child_impl, PRODUCTION, "candidate"),
                (old_impl, PRODUCTION, "parent"),
                (child_tests, TESTS, "candidate"),
                (old_tests, TESTS, "parent"),
            )
        ),
        "foreign transplant preimages",
    )
    try:
        production.write_bytes(old_impl)
        tests.write_bytes(modified)
        reg.need(
            reg.git(repo, "diff", "--no-ext-diff", "--name-only", reg.OLD)
            .decode()
            .splitlines()
            == [TESTS]
            and reg.sha(production) == blobs[PRODUCTION]["parent"][1]
            and reg.sha(tests) == reg.digest(modified),
            "red production differs from D outside the test module",
        )
        reg.save(
            folder / "transplant-source.json",
            {
                "production": reg.OLD,
                "production_sha": reg.sha(production),
                "tests": reg.sha(tests),
                "literal_candidate_tests": reg.digest(child_tests),
                "only_changed_from_D": [TESTS],
                "test": NAME,
            },
        )
        # Retain the literal module to independently verify that the test body itself was unedited.
        (folder / "transplanted-tests.rs").write_bytes(modified)
        rc = helper.log_run(argv, repo, folder / "parent-transplant.log")
        reg.need(rc in (1, 101), ("unexpected parent regression status", rc))
        outcomes((folder / "parent-transplant.log").read_text(errors="replace"), True)
    finally:
        production.write_bytes(child_impl)
        tests.write_bytes(child_tests)
    helper.check_source(repo, reg.NEW)
    helper.succeeded(argv, repo, folder / "restored-tests.log")
    outcomes((folder / "restored-tests.log").read_text(errors="replace"), False)
