# Front-end opportunity measurement on Ruff #28444

We enroll the full historical parent `64730be0c713bbc642c88e6824a386fa58452962` and child `04ae7c402b2a7f1c49a9a1dd264629c00e38f61b`. The child changes one public diagnostic message in `ruff_linter` and the two upstream CLI snapshots that exercise it. The Cargo.lock SHA-256 in both trees is `1cffd1e540f896e58b709024319f181cc198aba7f21e8c12c39d5dbf32aa7657`.

One newly initialized Linux x86-64 worker uses the published Ohm `-22` SDK. Both histories have the same physical source, registry, build and target paths. Each starts from an empty product tree and pristine, lockfile-verified Cargo registry sources. Unchanged Cargo inventories, the original library metadata and a client of the two exported diagnostics must agree between histories. A third empty child build and an invalid E0308 then repair cross-check the two exported native messages. Every `cargo check` uses the ordinary command below with eight Cargo job slots. Ohm selects its own compiler flags.

```sh
cargo +ohm check -p ruff_linter --lib --locked --offline --message-format=json
```

The ordinary history has no wrapper, sampler or observer. The sampled history uses `perf record` of retired user instructions every 1,000,003 events, inherited into real children, plus a ptrace exec observer with independent per-thread hardware counts. The leaf and stack, PID, TID, period and monotonic time are retained. `env -i` restores the exact original Cargo environment after launching perf. Both histories must have the same Cargo unit roster and freshness, every actual `.rmeta` digest, the selected library digest and complete client output for every corresponding phase. We keep the checked source versions, native consumer objects, original metadata bodies, perf events, exec argv and epoch records. A refusal remains a refusal. Both histories use the same compiler. The resulting instruction distribution sizes work for a prospective optimization.

The primary ranking is the non-overlapping sampled leaf distribution in the actual selected edited `ruff_linter` compiler. Separately group stack entries for expansion, resolution, lowering, type checking, MIR, metadata, dependency graph and other. Inclusive groups can overlap. Native code outside rustc and unattributable samples stay explicit. A plausible redesign must demonstrate enough removable work for about 20% of this compiler or 2× the complete edit and preserve the real verdicts on a prospective separate comparison. An absolute cold or unchanged runtime from this single worker cannot support that claim.
