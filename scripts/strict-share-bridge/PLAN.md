# Exact signed compiler bridge for the Unicode generator

Two fresh native Linux x86-64 workers, four fresh and isolated modes each, through the same release-style Cargo 761ea115 and signed -21 rustc c79998a5/Wild. Every measured Cargo command has the same immutable native `RUSTC_WORKSPACE_WRAPPER` at the same physical path and inode for the entire host. The wrapper execs the handed-off compiler unchanged except for Q, where it appends exactly one `-Zshare-generics=no` to the verified native host `unicode_names2_generator` library rustc. No modification reaches another compiler call. Each case is fixed for the lifetime of its separate target and shared roots. The case environment is a diagnostic control outside Cargo’s normal fingerprint. Switching B/Q in one populated target is inadmissible and will not be measured.

| Mode | Package profile | rustc generic sharing |
| --- | --- | --- |
| A | Default host opt 0 | Signed compiler default |
| B | Only `ruff_unicode_names2_generator` at opt 1 | Signed compiler default |
| Q | Exactly B’s package profile | Explicitly disabled for that one physical compiler |
| C | Only `ruff_unicode_names2_generator` at opt 2 | Signed compiler default |

Worker 01 runs ABQC, reversing the upstream ty_project edit and the secondary Unicode hunk. Worker 02 runs CQBA, applying the original forward edits. No replacement for a slow sample. On each arm, use a calibrated native inherited whole-process user instruction counter without ptrace to measure fresh cold, neutral unchanged, the historical edit and the first unchanged. The two independent primary comparisons are B/Q (conditional compiler effect at opt 1) and A/Q (combined package profile plus flag). Report C/A and C/Q to expose the natural opt-2 alternative. A bridge signals further evaluation only when B/Q >1 and A/Q ≥2 in both fresh workers; cold Q/B ≤1.05, fresh Q minus B ≤8 MiB and ≤1% are separately reported. Two observations do not qualify a default or a release. Report actual physical compiler/link counts, complete allocated target+shared blocks and regions per fresh phase.

The user commands are unchanged from the separate twelve-host package-only qualification.

```sh
cargo +ohm check -p ty_project --tests --locked --offline -j8 --message-format=json
cargo +ohm build -p ruff_unicode_names2 --lib --locked --offline -j4 --message-format=json
```

Pin the 498-archive lock, source Ruff 93526150, complete check edit 32c5cd5d, and genuine secondary Unicode generator hunk bfedc614b7. Controls use the exact neutral outputs, uniquely held `.rlib`/ELF, diagnostic-free original/edited/repair and complete E0308 against its own independently empty invalid source. In a separate structural cold and unchanged flank, match each wrapper’s incoming kernel argv to rustc’s outgoing argv on that same PID, require Q be the only added flag on one named host unit, inventory every workspace and registry rustc, its real Wild link and true generator. Reopen complete generated files, actual source states, stable checked-overflow and debug behavior, and CPU/driver/SDK/wrapper identities. The focused B/Q native provider on both hosts must read 83 then 47 even when length, inode and mtime are held, reject malformation, repair with removal to 0 and match independent clean reads. A and C each receive actual neutral/invalid/repair and linked reader controls. The native adversarial observations have no scored counters.

The prior package-only migration increased allocation by 388 MiB. This fresh-root bridge cannot establish the migration or release behavior of a future compiler change. Rich original disk ledgers are retained; no content equality is inferred from two graph files of the same size.
