# Published Rust stack cleanup

The active Rust stack now uses serial query-cache promotion and the collector's normal rustdoc selection. Sixty-five branch heads were published atomically with explicit expected-head leases. All 66 retained PR heads, their bases, draft states, and source trees were verified. Native stack #159 has the original ordered membership minus #44, #49, #50, #51, and #66 (63 members). Those five PRs are closed with comments explaining the removals.

Rust #66's cached-expansion identity validation, under-lock recheck, unit tests, and incremental CI coverage remain in #77. Only the parallel dispatch was removed; #105's saved-query index and invalid-index/green-node admission remain. The final main-stack graph source is byte-identical to the accepted serial ablation (SHA256 `ad23bf782fba0f25c66644b0f11cf43caa7ec7f6d79a628d0a7718f1636eaa0e`). Independent review verified that the identity-fix commit patch is unchanged.

The rustdoc change removes the redundant executable override, its unused path helper, and the corresponding override assertion. The existing component test now checks the normal Doc-training selector. All 10 opt-dist tests passed on the exact final source tree. All compiler/Cargo/rustdoc/Clippy/formatter PGO training and profile-use behavior remains otherwise unchanged. This work did not rebuild the compiler or rerun the benchmark campaigns; the compiler evidence is exact equality with the previously built and exercised serial-ablation source plus preserved identity/test blobs.

Ten originally empty Rust commits were removed, with exact parent/tree equality retained in the evidence. One additional Cargo-pin commit (`320cc7264ccca1d3a9037af5c6384b9351d24912`, indexed scheduling) became empty when the previously removed Cargo #115 was mapped to its retained base, and was dropped separately. This additional commit is not counted among the report's 25 original empty commits.

All active Cargo pins are mapped to the corresponding published Cargo stack after #96/#104/#115 removal. Four historical intermediate pins were mapped using the previous and current Cargo removal proofs. The only unmapped Cargo identity is upstream `5f94df4789f005f9a352888e8355ffc645b7ed0e`. The main tip and ordinary experiments pin Cargo #127; compact-artifact #157 pins #134; the explicit early-metadata integration #158 pins #133. Clippy is a vendored tree in this Rust repository, so its source bytes did not change when its own empty history was removed.

Main Rust #151: `b80854545d08f2975f1b1d877c1370c2c0a5e316`.

Rust #128 was already closed. A new comment records why it stays archived: the real recorded workloads never admitted a metadata-prefix clone, while the fixture establishes functionality rather than real-workflow benefit. Its branch remains preserved. Historical 1.98 side experiments #96/#136/#137/#138/#141/#144/#145 and released tags were not rewritten.

Clear comments and refreshed #67/#77 descriptions link to https://github.com/astral-sh/ohm/issues/144. Original heads remain under `refs/prune-approved-01/before/*` and in `before.bundle`. `commit-map.json`, `tree-validation.json`, `publish-plan.json`, `prepublish-validation.json`, `opt-dist-tests.log`, and `publication-verification.json` contain the exact evidence.
