# Optimized GNU baseline for the fifty original Ruff workspace test products

This one-host structural study asks which of fifty specific native outputs link again on each unchanged workspace test build, what actually happened to Ron, and which previous codegen products Cargo had. It records no performance counters or timing result.

## Inputs and enrollment

* The sole package is the optimized integrated GNU rehearsal from `astral-experiments/ohm` run 41256793646, attempt 1, successful job 124701560401. Its official artifact 13064288126 is 356,748,266 bytes with SHA-256 `611ee35ee079032afc2f02b9bb832b11b4bde6d9ee7bb82b7332f7485d5b26ee`. The original multi-platform workflow failed on Apple. The Linux intake requires that original run, the successful GNU steps, the archive/package/provenance SHA-256s and all 79 installed regular members. The effective rustc and rustdoc report `1bc7b35699479d5899a2935d79392b7bdaf7497d`. Cargo reports `4591cf45cc10abb19d2456c40b99606e08167f29`. The later `c5178286` compiler has the same Git tree. The archive carries the earlier revision. The worker binds actual rustup, Cargo, rustc, driver initialization, stock Wild and the system linker. [Original workflow](https://github.com/astral-experiments/ohm/actions/runs/41256793646)
* Ruff `93526150df078af7dd8fc4226cdcc469539d2001`, its Git tree and lockfile, all 498 registry archives, and the complete three-file patch from `83a3afc3156d73ae4296f3fa74ede28e4c72bfcd` are pinned. The exact 50 output identities, 102 executable/84 test products and behavior controls are inherited from QA `f40b16cdb9c041c941a5e339f816111a80a84bdf`. The accepted signed -21 output was artifact 13005843628. [Signed comparison](https://github.com/astral-experiments/ohm/actions/runs/41114085548)
* Only the manual dispatch of the reviewed SHA on `charlie/qa-rc22-workspace-50-20261101`, first attempt, is enrolled. One 16-core x86-64 Linux Namespace worker has a 260-minute limit. Entry requires 110 GiB, each visit requires 65 GiB, and the live watchdog stops below 60 GiB. The previous successful 16-core job reported 303,649,792,000 bytes free at entry. Exact comparisons may use up to 33 GiB of temporary private ELF storage, with a 3 GiB compressed portable-ELF ceiling plus 512 MiB for recipe/fingerprint bodies. Refusals upload the observations already available.

## Visits and readback

The five ordinary commands are identical:

```sh
cargo +ohm test --workspace --no-run --locked --offline -j8 --message-format=json
```

They visit cold original, unchanged original, historical edit, restored original, and unchanged original. A sixth visit on the unchanged source adds only `CARGO_LOG=cargo::compiler=info,cargo::compiler::fingerprint=info`. It records Cargo's direct per-unit reason, including the emitting mode/source, and its relink/early-cutoff messages. Two independently empty slots at the same logical target, private shared-build and registry paths produce clean original and clean edited references. Positive and negative typed consumers, actual parser and ty_server test cases, the e2e inventory and missing-snapshot refusal, and all 250 complete warm/own-empty ELF comparisons are retained.

Per-visit `22/native/PHASE/` contains the unmodified Cargo streams, its environment/argv, raw successful process syscalls and per-task exits (`process.tsv.gz`), hash/device/inode-bound native executables, and complete compiler/linker rosters. `owners.json` binds every selected Wild to its actual compiler through the Linux child-creation tree. It retains unsuccessful speculative rustcs as well as retries. The independent reader rejects partial process families, unhandled exec mechanisms, a foreign compiling rustc, or an ambiguous native owner. Four of the historical integration targets have `harness=false`. Their Cargo identity and own physical output still distinguish them.

`tracked.json` gives each original target and Ron's Cargo fresh bit, each compiler attempt and exit, mode, actual output/suffix/options and linker PID. A dirty Cargo row without a compiler remains a distinct observation. `pre-recipes.json.gz` (warm visits) and `recipes.json.gz` (all visits) capture the genuine .rlink, manifest, named object hashes, returned executable stat, source depfile and Cargo fingerprint files. Raw recipe/manifest/dep-info/fingerprint bodies are content-addressed under `22/recipe-blobs`. The field comparison checks observed paths, lengths, modification times and hashes. Cargo's opaque internal checksum and other eligibility predicates cannot be inferred from that comparison alone. Only an actual compiler PID reading its own recipe establishes a link-only invocation. No quantity here establishes a possible speedup or safe omission of a native linker.

## Replay

On an x86-64 GNU host with Python 3.11+ and b3sum, from the exact workload checkout:

```sh
qa=scripts/packaged-release-workspace
sha256sum --quiet -c "$qa/RC22-SHA256SUMS"
python3 -IB "$qa/linux_controls.py"
python3 -IB "$qa/rc22_controls.py"
python3 -IB "$qa/linux_reopen.py" 22 /path/to/official-workspace.zip --expected-head "$(git rev-parse HEAD)"
```

The offline controls include literal earlier 50-pair/Ron process arguments and a tiny test workspace actually built by this optimized Rust/Cargo pair. That separate calibration observed a cold speculative rustc exit 1, a successful identical-argv retry and its one Wild, fresh unchanged tests, and a genuine source edit with direct and transitive Cargo fingerprint reasons. `rc22_controls.py --native NEW_DIRECTORY` also runs a small independent GCC/collect2/system-linker control on a native host that permits unprivileged ptrace.
