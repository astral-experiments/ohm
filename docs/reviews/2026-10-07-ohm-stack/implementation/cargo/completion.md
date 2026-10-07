# Cargo stack cleanup

Published 44 rebuilt branch heads with explicit old-head leases in one atomic push. GitHub native stack 135 was replaced by stack 136, retaining 47 members in their original order. PRs #61, #65 and #100 now bypass the removed layers. The two additional live branches, #132 and #134, were also rebuilt; all 49 retained PR heads and bases were verified. Unrelated #102 is unchanged.

Closed #96 and the eight exact-empty PRs #56, #57, #58, #59, #60, #62, #63 and #64. Each has a comment explaining the removal and linking to Ohm issue 144. Their branches retain the original heads. #61 is retained. A comment on #100 explains why its writer reservations and the concurrency tests remain.

The production change is exactly the accepted #96 removal: three files, +13/-149. It removes the queued-miss callback, specialized freshness recheck and unnecessary fresh-work helper. Existing writer reservations acquire or retry the necessary locks before freshness observations, covering the same eligible shared registry units. All concurrency tests remain; their original #96 additions now belong to the first retained #100 commit. Every retained PR tree was checked: unchanged before #96, and exactly the approved production removal after it. No other source or test changes were introduced.

Validation on rebuilt #127 (`84593fd08a20d1b049e2e04d0d7e327b65da9004`):

- All 67 shared-registry tests passed, including concurrent build/check, forced rebuilds, environment changes, deadlock handling, producer failure and waiter cancellation.
- `cargo +ohm fmt --all -- --check` passed.
- `git diff --check` passed for every retained PR tree comparison.
- Fresh GitHub verification confirmed all retained and archived heads, bases, draft flags, states, and native stack membership.

The test command was `cargo +ohm test --test testsuite build_dir::shared_registry_cache --jobs 8 -- --include-ignored --test-threads=4`, using the existing task target and shared build directories. This run checked the source change; it collected no benchmark timings.

`commit-map.json` has 95 old-to-new entries: 91 current-stack commits plus four historical Cargo pins needed by retained Rust integration PRs. `historical-pin-map.json` records the four older pins. Old #114/#123 map through the previously verified #104/#115 removal to their new equivalents. Removed #104 maps to its retained #106 base; removed #115 maps to its retained #114 base. All destinations also exclude #96 and are published on retained branches. Upstream `5f94df4789f005f9a352888e8355ffc645b7ed0e` predates #96 and remains unchanged.

Evidence files: `publish-plan.json`, `tree-validation.json`, `top-removal.patch`, `shared-tests.log`, `fmt.log`, `publication-verified.json`, `final-pr-verification.json`, `native-final.json`, `closures.json`, and `comment-100-url.txt`. The original refs are preserved in `before.bundle` and `refs/archive/prune-approved-01/` in the task clone. Existing release tags and primary Cargo working-tree edits were preserved.
