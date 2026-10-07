# Cargo #104 and #115 removal

Both PRs were removed from the active Cargo stack and closed on 2026-10-05.

- [#104 removal comment](https://github.com/astral-sh/ohm-cargo/pull/104#issuecomment-5995654553): the expiry protocol adds tracking, ownership, locking and deletion recovery, while its storage measurement uses simulated ages. The measured Ruff parser edit slowed from 0.244 s to 0.903 s after expiry.
- [#115 removal comment](https://github.com/astral-sh/ohm-cargo/pull/115#issuecomment-5995655432): the indexed scheduler reduced instructions by 0.27–0.66% on warm no-op commands, with no clear improvement in elapsed time.

The eight retained descendant branches were pushed atomically with explicit leases. #108 now targets #106, and #123 targets #114. GitHub's native stack was recreated with its other 56 PRs in the original order. Unaffected heads, titles, draft states and the stack base were verified unchanged.

The retained top Cargo commit is `42fdb978f8d37c037bb418326ecab3aa8690ca85`. Production files match an independent direct removal of #104/#115 from the previous top. The dependency queue is the exact pre-#115 file. Cleanup for ordinary and isolated Clippy state is retained, with coverage added to the existing package-clean test.

Validation: queue tests (2), worktree tests (33), CLI help, formatting and the development shared-registry suite (67) pass. Packaged-default shared-registry testing has three failures, all reproduced on the unchanged original top with the same settings. No performance measurement was needed to remove these two features.

The compiler's active Cargo pointer was updated in Rust #140 and propagated through #151, #154, #155, #156 and #157. Every non-Cargo file is unchanged at all six heads and at each of the 39 replayed commits. Rust #157 retains its Cargo #134 experiment with the corresponding reduced-stack revision. The three stale side experiments (#141, #144 and #145) remain at their historical bases; they are outside the current native Rust stack. Existing release tags and manifests remain unchanged. The three ongoing ablations retain the original Cargo `018a2b9` as a fixed input.

The complete diff, original-ref bundle, test logs, branch mapping and remote publication checks are in `../stack-prune-104-115/`; see `validation-report.md`, `publication-verification.json`, `rust-integration-report.md` and `rust-publication-verification.json` there.
