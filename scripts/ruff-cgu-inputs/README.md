# Signed Ruff codegen inputs on the first checkout of A

This single-worker diagnostic captures the actual pre-optimization LLVM bitcode emitted by signed rustc for `ruff_linter` and `ruff_workspace`, and the native objects and metadata in the libraries Cargo reports. It compares them after building B then switching to A with independent builds from empty roots at the same physical paths. B is `7b13f01ba1569887a25670820764b24c206da8e5` and A is `b5dba861cc38e3f7fb4524c9ceba3e01a474ea13`.

Every visit runs the same command:

```sh
cargo +ohm build -p ruff --bin ruff --locked --offline -j4 --message-format=json
```

| History | Visits | What it records |
| --- | --- | --- |
| `reference` | empty B, independently empty A | Whole native Ruff and typed client references |
| `plain-1` | empty B, first A | One calibrated whole-command user instruction count on A |
| `ordinary-observed` | empty B, first A | Read-only observation of original signed rustc arguments |
| `diagnostic-empty` | empty B, independently empty A | Independent bitcode and native archive references |
| `diagnostic` | empty B, first A, unchanged A, invalid A, repaired A | Bitcode and archive evidence on a genuine change, reuse, failure and repair |

Each history has independent writable state. Only the diagnostic recorder adds `-Csave-temps=yes` at the already-selected physical rustc exec for the two enrolled libraries. The tracer saves the complete original and effective argument vectors. The reader compares the multisets of original argument bytes on the two observed transitions to A and reconciles the 20 dirty owners with the original Cargo artifact rows. Cargo, rustc wrappers, registry trust, the toolchain and compilation flags use the signed recipe. No tracing or extra compiler flag is present inside the ordinary hardware window.

Every successful visit must reproduce its independently empty CLI and reader, external API verdict and 375-unit Cargo graph. The invalid parser edit must produce its specific E0308 and exit 101. The repair requires the authentic failed-session grace period. Each optional bitcode file is collected before the next command. The live monitor retains the original resource floors and refuses more than 2 GiB of compressed original codegen data.

With the three checkouts exactly as named in the workflow (`enrolled`, `collector`, `contract`), run:

```sh
python3 -IB enrolled/scripts/ruff-cgu-inputs/acquire_cgu.py --sources
python3 -IB enrolled/scripts/ruff-cgu-inputs/test_cgu_orchestration.py
python3 -IB enrolled/scripts/ruff-cgu-inputs/worker_cgu.py reopen ORIGINAL_LOG_DIRECTORY collector contract EXACT_QA_HEAD
```

The review entry reopens original native bodies, signed SDK identities, calibration and trip counts, compiler arguments, historical Git, per-inode storage, typed diagnostics and retained bitcode. For a pre-acquisition rehearsal with the authentic first-A reference from run 41357296901, use:

```sh
python3 -IB enrolled/scripts/ruff-cgu-inputs/test_cgu_orchestration.py --original 41357296901-13103812439.zip collector contract
```

That historical readback uses the original signed executable and actual kernel arguments. Its reconstruction of the new recorder's file format is a separate test. The hosted job runs the real recorder against its own positive and negative native cases before acquiring the SDK. A successful diagnostic can establish equality or differences in the two enrolled compilers' inputs. It measures one ordinary command, so it cannot establish the instruction cost of reusing those inputs or a speedup.
