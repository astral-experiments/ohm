# Applied Ohm stack cleanup

The removals approved in [Ohm #144](https://github.com/astral-sh/ohm/issues/144) are applied to the active Rust, Cargo and Clippy stacks. The October 7 report remains a snapshot of the review; its other recommendations remain proposals.

| Change | Applied result and reason |
| --- | --- |
| Rust #66 | Restored serial query promotion. Eighteen paired runs showed no consistent command-time benefit from parallel promotion. The cached-expansion identity fix, regression tests and applicable CI coverage remain under #77. [Decision](https://github.com/astral-sh/ohm-rust/pull/66#issuecomment-6039781048). |
| Rust #67 rustdoc selector | Removed the redundant selector and its unused path helper; updated the component-training test. Both selectors chose identical binary bytes. Formatter, Clippy and upstream rustdoc PGO remain. [Decision](https://github.com/astral-sh/ohm-rust/pull/67#issuecomment-6039782099). |
| Cargo #96 | Removed the queued-miss recheck: 136 net production lines. Writer reservations already cover its eligible units; both variants compiled the shared dependency once in the concurrent uv probe. Reservation, locking and concurrency tests remain. [Decision](https://github.com/astral-sh/ohm-cargo/pull/96#issuecomment-6039586359). |
| Rust #128 | Kept the already-closed experiment archived and recorded the reason: the tested real workloads never admitted a metadata clone. Its branch and evidence remain available. [Decision](https://github.com/astral-sh/ohm-rust/pull/128#issuecomment-6039783066). |
| Empty stack layers | Dropped the 25 exact-empty commits identified in the report: ten Rust, eight Cargo and seven Clippy. Updating Cargo references made one additional obsolete Cargo #115 pin empty; that commit was also dropped. The corresponding upstream implementations remain. |

The retained branches were published with explicit leases against their original heads. GitHub stack membership and bases were rebuilt to bypass the removed layers. Archived source references and historical release manifests were preserved.

## Validation

- Cargo: all 67 shared-registry tests passed on the rebuilt source, including concurrency, cancellation and deadlock coverage. Formatting and diff checks passed. Every retained tree differs only by the accepted three-file production removal, or remains identical if it precedes #96.
- Rust: all 10 opt-dist tests passed. An independent audit checked the reconstructed trees and parent relationships across 181 original commits, preserved identity fixes/tests, and mapped Cargo references. The final promotion source exactly matches the accepted serial-ablation source. This implementation did not run a new full compiler build or benchmark campaign.
- Clippy: all retained commit trees and all six surviving PR diffs are identical to their originals. The history shrank from 21 commits to 14, with no source change.
- Report attachment: an independent audit verified the published Git blobs, Markdown and HTML content, direct report links, manifest checksums and ZIP contents.

The current main-stack heads are Rust `b80854545d08f2975f1b1d877c1370c2c0a5e316`, Cargo `84593fd08a20d1b049e2e04d0d7e327b65da9004`, and Clippy `0b5067c75ba5df05fa53be4ea67d2cd82a966bae`. These are source-stack changes; they do not replace an installed or released toolchain.
