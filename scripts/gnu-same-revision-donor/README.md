# Native qualification of a newer same-revision incremental donor

This manual GNU job builds and tests Rust `d95494a6a63c22222806c06e3d3aa0de504d8e8a` (D) against its immediate parent `393b4b05a4bfa3f531a36023846f86236a6b71a9` (E, #301). Both have branch retention enabled. The workflow uses the ordinary Cargo entry point. It leaves both finalized incremental sessions, their files and their locks where rustc put them.

## Source and native SDK

The nine-object Git pack adds D to independently reconstructed E. The verifier checks both changed Rust blobs and their original parent blobs, the whole tree, parent, binary diff and unchanged build/test components. The only changed paths are `compiler/rustc_incremental/src/persist/fs.rs` and its existing `fs/tests.rs`. The source builder repeats the original E bootstrap from the same absolute path with the 24 recorded arguments in `inputs/bootstrap.json`, the original stage0 rustc/Cargo and LLVM. The 81-file E transfer comes from run 41242910474 at `762fc25095e317ac5632ec835df3c7f9cfc64a64`. D is built into a separately allocated 81-file SDK. Every regular member except the driver and optionally rustdoc must match E in size, mode and digest. The source artifact contains a directly verifiable, two-file-maximum compressed D overlay.

The worker runs the full in-tree `rustc_incremental` unit test suite and requires all seven named filesystem tests including the two new tests. It separately runs the original `ohm-packed-branch-cache`, `ohm-branch-cache-opt-out` and `incremental-missing-query-cache` run-makes. Each command must report one executed and passing named suite. The worker rebuilds and reopens the complete 81-file stage afterward.

## Registered cases

For each installed toolchain a fresh private Ruff checkout enrolls A `b5dba861cc38e3f7fb4524c9ceba3e01a474ea13` and B `7b13f01ba1569887a25670820764b24c206da8e5`. It authenticates all 505 locked registry archives. Each of the two histories starts with empty Cargo output directories and trains Y at B, X at A, then fast-forwards X to the same B. The return switches back to Y and changes one comment byte in `nodes.rs`. One history compiles the same tracked B at X. In the other, X first compiles a real, uncommitted `try_from_extension("pyi")` implementation that returns Python. It restores the source before the return, keeping the same X ref and genuinely different donor contents.

The fixed command on every visit is:

```sh
cargo +ohm build --locked --offline -j2 -p ruff_python_edits --lib --message-format=json
```

The Cargo allowlist uses stable, separate `CARGO_TARGET_DIR` and explicit `CARGO_BUILD_BUILD_DIR`. Its only additional Rust flag is `-Zohm-branch-cache=yes`. Both roles run at the same visible Rustup SDK path with independently allocated rustc, driver, strict Cargo `761ea115` and stock Wild. Each return expects the source-registered X donor to be newer and independently created by the installed X-at-B compiler. The source parent may use its original Y donor. D must use the X donor. A passive Linux fanotify group reports actual process ID, marked file device/inode and size through a kernel-returned FD. The short-lived privileged setup accepts only descriptors to the unprivileged caller's own regular files. Cargo and its compilers remain unprivileged. The proof reopens the exact prior graph and query-cache identity and requires the PID to match the corresponding installed rustc and mapped driver in the kernel trace. A distinct physical hardlink and an unread control qualify the observer on the actual developer host before the source compile.

Each history goes on to an unchanged repeat, a genuine AST E0308, repair, and an actual semantic body edit. Two separate empty references per role verify the complete native client ELF, the selected AST and edits rlibs' actual codegen object payloads, type widths 64/56, and `.pyi` and `.py` results. The opposite-width typed client must fail. All successful phases retain complete rlibs and native client executables, normalized only by hash-based storage deduplication. The archive members, metadata and raw ELF are always accounted individually. Whole rlib identities are recorded per visit. The workload compares same-role native objects and executables to that role's corresponding empty reference. It records the real amount of Cargo storage after every phase including hardlink deduplication and unfinished directories.

There are 18 Ruff Cargo visits per compiler. The clean return must actually run AST and edits on E, AST only on D. A divergent dirty donor must still cause the normal corrective compilation on both and return the clean native result. Both repeats must stay fresh. Independently, 11 ordinary Cargo builds per compiler exercise a genuine declared archive and unknown assembly barrier across the same source history. The probe changes native bytes 17→29 at the original inode, size and old mtime, checks malformed data through the genuine GNU linker, repairs to 37, and repeats. It compares to independently empty builds of 29, malformed and 37, reexecutes the full Cargo binary, and binds the physical archive FD (including a verified fork-only helper) to Wild's actual output.

Every genuinely empty installation uses a kernel exec-event observer that explicitly accounts for the installed compiler's version probes. All warm/return/error visits require the independently pinned schema-3 whole-family observer. Partial traces, a foreign attempt/role/SDK, a missing or unaccounted donor FD, a substituted reader or a changed native result refuse qualification. Both original stdout/stderr and refusal files remain in the hosted artifacts. This is a single-host, unscored native qualification. It measures neither instruction counts nor elapsed speedup.

The first attempt on the original QA head passed the source bootstrap and reassembly, seven named compiler tests, three run-makes and the parent native-archive matrix. The first parent cold Ruff Cargo build completed, but the sampler rejected its driver before any branch-return comparison. The installed file had device 33 and inode 7614425, whereas the kernel executable map showed device 32 at the same inode and pathname. Those observations are retained in `inputs/controls/mapped-driver-contacts.json.gz`. [Original run](https://github.com/astral-experiments/ohm/actions/runs/41301552076).

The successor opens and hashes the selected regular SDK file and holds one private read/execute mapping of its first page across each Cargo command. It compares that mapping with the executable mappings of the actual installed rustc processes. The compiler must see the enrolled file through its own root, be in the same mount namespace and agree on the complete pathname and backing device and inode. The tests include a real shared library left mapped across replacement by a separately allocated byte-identical copy at the same displayed path. The registered source, Cargo commands, donor selection and native verdicts are unchanged.

The next attempt passed the live mapped-library controls on the hosted kernel. Its read of the historical parent test fixture failed before SDK acquisition because the older reader blob was absent from the sparse checkout. `inputs/controls/parent-reader-d22c1c9d.py.gz` contains those complete original reader bytes. Their SHA-256 is checked against both the original QA manifest and the original 512-file native control receipt. The current job verifies its sole parent from the reviewed commit header in its depth-one checkout. [Original test log](https://github.com/astral-experiments/ohm/actions/runs/41302988864/job/124837613307)

## Review and replay

The intended branch is `charlie/qa-ruff-same-revision-donor-source-20261101` on the packaging repository. Only manual dispatch of a reviewed exact head and its first attempt are eligible. The workflow has read-only repository/action permissions. The 165-minute deadline and original bootstrap/workload memory and disk guards apply. The source gate requires 32 GiB free at entry on both paths and 32 GiB effective memory. Live guards retain 4 GiB work space, 6 GiB receipt space and 8 GiB effective memory.

From a checkout of this QA commit, with the exact observer checkout `19f9a67b032cce44cea1e3bb7e324558cd9abd0a`, the following commands exercise the controls and independently replay both hosted artifact directories:

```sh
s=scripts/gnu-same-revision-donor
(cd "$s" && sha256sum --check --strict SHA256SUMS)
python3 -IB "$s/test_qualification.py" "$OBSERVER"
python3 -IB "$s/reopen.py" "$SOURCE_RECEIPTS" "$RUNNER_LOGS"
python3 -IB "$s/reopen_ruff.py" "$RUNNER_LOGS" "$OBSERVER"
```

After reviewing the results, `overlay.py D/overlay RUNNER_LOGS ORIGINAL_E NEW_EMPTY_DEST` reconstructs the qualified SDK from the independently authenticated E files and overlay. The offline Ruff verifier requires a normal executable temporary directory on x86-64 GNU. It reexecutes only verified compiler-produced ELF bodies, with the working directory and environment isolated from the supplied study files.
