# Drop empty Clippy stack commits

Removed seven empty backport commits from the active Clippy stack and closed PRs #36, #37, #39, #40, #42, #43 and #45. Each removed commit has exactly the same Git tree as its parent; the corresponding implementation is already in the Rust 1.99 base.

The stack now contains 14 commits instead of 21. Every surviving commit preserves its original source tree. Each of the six surviving PR diffs is byte-for-byte identical to its previous diff. The final tip changed from `f52143702ff1f265014e87d5e6853e70a3b15728` to `0b5067c75ba5df05fa53be4ea67d2cd82a966bae`, and both tips have tree `a3e70e644ddefcc27d304e4416b2a8cf258b90b8`. This establishes source equivalence without rebuilding or benchmarking identical source.

GitHub native stack #57 was dissolved and recreated as #58 with PRs #38, #41, #44, #46, #48 and #49. The five rewritten branches were published atomically with explicit leases on their previous SHAs. The first branch (#38) did not need rewriting. Bases were updated for #41, #44 and #46.

The primary checkout remains at its original clean HEAD. Independent Clippy codegen PR #51, release references, and the branches of the closed PRs remain intact. Original history is preserved in `before.bundle` and local `refs/backup/stack-prune-approved-01/` references.

The comments explain that this is a source-preserving history cleanup and link the report in [Ohm #144](https://github.com/astral-sh/ohm/issues/144).

| PR | Comment |
| --- | --- |
| #37 | [Removal rationale](https://github.com/astral-sh/ohm-rust-clippy/pull/37#issuecomment-6039556910) |
| #36 | [Removal rationale](https://github.com/astral-sh/ohm-rust-clippy/pull/36#issuecomment-6039557746) |
| #39 | [Removal rationale](https://github.com/astral-sh/ohm-rust-clippy/pull/39#issuecomment-6039558551) |
| #40 | [Removal rationale](https://github.com/astral-sh/ohm-rust-clippy/pull/40#issuecomment-6039559215) |
| #42 | [Removal rationale](https://github.com/astral-sh/ohm-rust-clippy/pull/42#issuecomment-6039559955) |
| #43 | [Removal rationale](https://github.com/astral-sh/ohm-rust-clippy/pull/43#issuecomment-6039560909) |
| #45 | [Removal rationale](https://github.com/astral-sh/ohm-rust-clippy/pull/45#issuecomment-6039561692) |

Evidence: `tree-preservation-proof.json`, `final-verification.json`, `published-prs.json`, `native-stack-after.json`, `publish-plan.json`, and `commit-map.json`.
