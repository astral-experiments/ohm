"""Exercise release-candidate Cargo GC with actual disposable Linux bind mounts."""
import argparse
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

RUST = "625207d26ce4449c9c95d871c88cfb50e904c09f"
ROLES = {
    "pinned": ("2554a1dfaf22474b360a4298883acf41f82bd78f", "014d4b308410fdaa2acdadaff6aba2a410fc43da"),
    "fixed": ("4591cf45cc10abb19d2456c40b99606e08167f29", "a2c9a62722e1ef849cb68874e79617c92d165a8b"),
}
PRIVATE = "786e5235c3faf04fcfde6beef6c2b91537d37696"
SHARED = "f23a67771c625785cd70f58e9b46e8d26af3d317"
TRIPLE = "x86_64-unknown-linux-gnu"
WORKER = Path(__file__).resolve()


def sha(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def protocol(shared, private):
    for directory, head in ((shared, SHARED), (private, PRIVATE)):
        assert directory == directory.resolve(strict=True)
        assert subprocess.check_output(["git", "-c", "safe.directory=" + str(directory), "-C", directory,
                                        "rev-parse", "HEAD"], text=True).strip() == head
    shared_source = shared / "scripts/gc-mount-evidence"
    private_source = private / "scripts/private-gc-overlay"
    for directory, root, head, names in ((shared_source, shared, SHARED, ("compare.py", "late_bind.py", "observe.py")),
            (private_source, private, PRIVATE, ("reattached.py",))):
        for name in names:
            path = directory / name
            assert not path.is_symlink() and path.read_bytes() == subprocess.check_output(
                ["git", "-c", "safe.directory=" + str(root), "-C", root, "show", head + ":" + str(path.relative_to(root))])
    sys.path[:0] = [str(shared_source), str(private_source)]
    import compare
    import late_bind
    import reattached
    assert Path(compare.__file__) == shared_source / "compare.py"
    assert Path(reattached.__file__) == private_source / "reattached.py"
    assert late_bind.compare is reattached.ctrl is compare
    return compare, late_bind, reattached


def check_sdk(sdk, inventory):
    rustc = sdk / "bin/rustc"
    driver, = (sdk / "lib").glob("librustc_driver*.so")
    wild = sdk / ("lib/rustlib/" + TRIPLE + "/bin/wild-ld/ld.bfd")
    paths = {"rustc": rustc, "driver": driver, "wild": wild}
    assert all(sha(file) == inventory[name] for name, file in paths.items())
    assert inventory["rust"] == RUST
    compiler = subprocess.check_output([rustc, "-vV"], text=True)
    assert "commit-hash: " + RUST + "\n" in compiler and "host: " + TRIPLE + "\n" in compiler
    assert all(file.resolve(strict=True).is_file() for file in paths.values())
    return {key: [sha(file), file.stat().st_dev, file.stat().st_ino] for key, file in paths.items()}


def private_gate(f, driver, result_dir, expect_safe, fallback):
    c = f.makecase("private-replaced")
    ws = c["cwd"]
    target = ws / "target"
    c["env"]["CARGO_TARGET_DIR"] = str(target)
    f.write(ws / "Cargo.toml", b'[package]\nname="target_graft"\nversion="0.1.0"\nedition="2024"\n')
    f.write(ws / "src/lib.rs", b"pub const N:u8=17;\n")
    assert f.cmd(c, "enroll", ["check", "--offline"]).returncode == 0
    stamp = time.time_ns() - 4 * 3600 * 10**9
    os.utime(target / ".ohm-target-last-use-v1", ns=(stamp, stamp))
    old = c["outside"] / "relocated-deps"
    dest = target / "debug/deps"
    leaf = dest / "private-after-scan.bin"
    f.write(leaf, b"actual owned frozen output after discovery\n")
    before = driver.state(leaf)
    assert before["nlink"] == 1
    with leaf.open("rb") as held:
        observations = driver.trace(f, c, dest, old, leaf, result_dir, fallback)
        observations["held_after"] = {"nlink": os.fstat(held.fileno()).st_nlink, "sha256": sha(Path("/proc/self/fd") / str(held.fileno()))}
    driver.ctrl.o.save(result_dir / "private.json", observations)
    validate_private(observations, before, sha(f.runtime / "bin/cargo"), expect_safe, fallback)
    assert driver.state(dest)["mount"] == observations["binding"]["bound_dir"]["mount"]
    f.unmount(observations["binding"]["bound_dir"]["mount"])


def validate_private(observations, before, expected_hash, expect_safe, fallback):
    binding, events = observations["binding"], observations["events"]
    assert binding["sha256"] == expected_hash and before == binding["before_leaf"]
    assert binding["bound_dir"]["mount"] != binding["outside_dir"]["mount"]
    assert binding["bound_leaf"]["inode"] == binding["outside_leaf"]["inode"] == before["inode"]
    assert observations["held_after"]["sha256"] == before["sha256"]
    unlinks = [e for e in events if e.get("kind") == "unlinkat-payload" and e.get("return") == 0]
    if expect_safe:
        assert observations["exit"] == 0 and observations["outside_after"] == binding["outside_leaf"]
        assert observations["held_after"]["nlink"] == 1 and not unlinks
        assert any(e.get("kind") == "openat2" and e.get("resolve", 0) & 1
                   and e.get("return") == (-errno.ENOSYS if fallback else -errno.EXDEV) for e in events)
        if fallback:
            assert any(e.get("kind") == "mount-id-open" and e.get("return", -1) >= 0 for e in events)
    else:
        assert observations["exit"] == 101 and observations["outside_after"] is None and unlinks
        assert observations["held_after"]["nlink"] == 0


def inside(a):
    compare, late, private = protocol(a.shared, a.private)
    cfg = json.loads((a.root / "registration.json").read_bytes())
    role = a.role
    # The frozen helper calls its control slot "signed". Here that slot holds the
    # source-built proposed -22 Cargo recorded in registration.json and -Vv.
    slot = "signed" if role == "pinned" else "fixed"
    sdk = a.root / ("sdk-21" if role == "pinned" else "sdk-fixed")
    out = a.root / "packet" / slot
    assert os.geteuid() == 0 and compare.o.ns() != a.namespace
    assert check_sdk(sdk, cfg) == cfg["identities"]
    commit, _ = ROLES[role]
    f = compare.Fixture(slot, a.root, a.case, sdk, out, a.uid, a.gid, a.namespace, a.nonce, a.shim, commit, cfg[role]["sha256"])
    if a.suite == "shared":
        compare.inner(f)
    elif a.suite == "late":
        late.run(f)
    else:
        private_gate(f, private, out, role == "fixed", a.suite == "private-fallback")
    assert not any(Path(row["path"]).is_relative_to(a.case) for row in compare.o.mounts().values())


def outer(a):
    compare, _, _ = protocol(a.shared, a.private)
    assert a.root.parent == Path(os.environ["RUNNER_TEMP"]).resolve(strict=True) and not a.root.exists()
    cfg = json.loads(a.registration.read_bytes())
    assert set(ROLES) <= set(cfg) and a.suite in ("shared", "late", "private", "private-fallback")
    a.root.mkdir(mode=0o700)
    packet = a.root / "packet"
    packet.mkdir()
    cfg["identities"] = check_sdk(a.sdk, cfg)
    compare.o.save(a.root / "registration.json", cfg)
    compare.o.save(packet / "registration.json", cfg)
    roles = ("fixed",) if a.suite == "private-fallback" else ("pinned", "fixed")
    for role in roles:
        commit, tree = ROLES[role]
        expected = cfg[role]
        assert expected["source"] == commit and expected["tree"] == tree
        binary = a.pinned if role == "pinned" else a.fixed
        assert binary.is_file() and sha(binary) == expected["sha256"]
        version = subprocess.check_output([binary, "-Vv"], text=True)
        assert "commit-hash: " + commit + "\n" in version
        slot = "signed" if role == "pinned" else "fixed"
        sdk = a.root / ("sdk-21" if role == "pinned" else "sdk-fixed")
        sdk.mkdir()
        (sdk / "bin").mkdir()
        for item in a.sdk.iterdir():
            if item.name != "bin":
                (sdk / item.name).symlink_to(item, target_is_directory=item.is_dir())
        for item in (a.sdk / "bin").iterdir():
            if item.name != "cargo":
                (sdk / "bin" / item.name).symlink_to(item)
        shutil.copyfile(binary, sdk / "bin/cargo")
        (sdk / "bin/cargo").chmod(0o755)
        assert sha(sdk / "bin/cargo") == expected["sha256"]
        assert check_sdk(sdk, cfg) == cfg["identities"]
        out = packet / slot
        out.mkdir()
        case = Path(tempfile.mkdtemp(dir=a.root, prefix="qa-" + slot + "-"))
        nonce = str(uuid.uuid4())
        (case / ".owned").write_text(nonce)
        ns = compare.o.ns()
        cmd = ["sudo", "-n", "/usr/bin/env", "-i", "PATH=/usr/sbin:/usr/bin:/sbin:/bin", "LANG=C",
               "/usr/bin/unshare", "--mount", "--propagation", "private", "--fork", "--", "/usr/bin/python3", "-IB",
               str(WORKER), "inside", a.suite, str(a.root), str(a.shared), str(a.private), role, str(case),
               str(os.getuid()), str(os.getgid()), str(ns), nonce, shutil.which("rustup")]
        run = subprocess.run(cmd, capture_output=True, timeout=420)
        (out / "outer.stdout").write_bytes(run.stdout)
        (out / "outer.stderr").write_bytes(run.stderr)
        assert compare.o.ns() == ns and not any(Path(row["path"]).is_relative_to(case) for row in compare.o.mounts().values())
        if run.returncode:
            print(run.stderr.decode(errors="replace")[-2000:], file=sys.stderr)
        assert run.returncode == 0
    compare.o.save(packet / "complete.json", {"roles": roles, "suite": a.suite, "source": cfg["rust"],
                                            "qa": os.environ["GITHUB_SHA"], "run": int(os.environ["GITHUB_RUN_ID"])})


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    command = p.add_subparsers(dest="mode", required=True)
    for mode in ("outer", "inside"):
        arguments = command.add_parser(mode)
        arguments.add_argument("suite", choices=("shared", "late", "private", "private-fallback"))
        for name in ("root", "shared", "private"):
            arguments.add_argument(name, type=Path)
        if mode == "outer":
            for name in ("sdk", "pinned", "fixed", "registration"):
                arguments.add_argument(name, type=Path)
        else:
            arguments.add_argument("role", choices=tuple(ROLES))
            arguments.add_argument("case", type=Path)
            for name in ("uid", "gid", "namespace"):
                arguments.add_argument(name, type=int)
            arguments.add_argument("nonce")
            arguments.add_argument("shim")
    opts = p.parse_args()
    (outer if opts.mode == "outer" else inside)(opts)
