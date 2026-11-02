# Source-built LiveDebugValues trial on two Ruff edits

Parent 1589b588 and candidate 531eb198 both include the existing coalescer from Rust #326. The shared Cargo, Linux x86-64 LLVM, Wild, standard libraries, version stamp and stage0 are physically matched. Each installation parks its two compiler trees and installs the selected one at the same rustup path. It verifies every large object in the source-built capsule before and after the work. Each role, suite and independent clean reference starts with private Cargo build and target directories. No debug actor is in either compiler or Cargo invocation.

The primary command is the developer-profile `ruff_workspace` library build on Ruff #28106. The independent second task is the `ty_server:e2e` test build on #27836. The printed terminal and the independent original-archive reader must agree on what actually ran, including the unchanged e2e linker. Nonces on three independently read and source-bound cold autocfg stdin probes are explicitly recorded. All actual owner arguments and native ELF bytes must agree. Each owner option archive is preserved byte-for-byte even where two genuine independently compiled archives differ.

The original two signed-Rust pilot pairs are excluded. Their unchanged measurements and the independently crossed Cargo diagnostic files are preserved under `scripts/ruff-ldv-cached-stderr`. The experiment, primary estimator, adverse-trial handling and randomized six-boot assignment were frozen before constructing these compilers in `scripts/ruff-ldv-physical-stage/confirmation.json`. Solitary native admission and its raw independent readbacks must pass before any scored enrollment. Hardware files stay in the original archives until all scheduled boots and fresh readers finish.

From this packaging QA checkout use the existing OSS GitHub identity.

```sh
head=$(git rev-parse HEAD)
ref=charlie/qa-ruff-workspace-link-census-20261102
gh-auto workflow run ci.yml -R astral-experiments/ohm --ref "$ref" -f mode=ldv-source-admit -f reviewed_head="$head"
# Supply the successfully verified native-only run ID from that precise commit.
gh-auto workflow run ci.yml -R astral-experiments/ohm --ref "$ref" -f mode=ldv-source-score -f reviewed_head="$head" -f ldv_admission="$admission"
```

Both commands require the enrolled reviewed commit to be the current QA head on dispatch. Reusing a prior attempt, boot, source, counter, or native baseline from another cohort fails admission. The independently read original compiler and Ruff archives remain available for the hosted artifact retention window.

The first physical admission, run 41429121227, stopped after the initial stock Cargo build succeeded on each boot. Its observer had incorrectly treated the signed Cargo build-script export of CARGO_ENCODED_RUSTFLAGS as a caller override. The independent replay traced all 1,069 successful execs and their clone ancestry. Every one of the 132 nonempty exports came from a real build script below the signed Cargo binary. The earlier two signed, unmodified Ruff histories show the same seven flags and empty caller environments. The exact code locations, raw archives, process counts and byte digests are in child-environment.json. Fresh trials still reject any caller-supplied Rust flags, wrappers, loader controls, trust settings, changed flag or an export outside a build-script subtree. The first two builds contribute no measurements.

A separate unscored layout control selects the original source parent without Rustdoc, then the same parent, candidate and parent again with access to the intact signed documentation component. It compiles the real locked autocfg package and an executable consumer at fixed paths with ordinary Cargo and independently empty target/build roots. Each documentation check opens the actual signed driver, uses the common LLVM and produces HTML. The control records actual registry --extern operands, file hashes and the native verdict on each visit. The six scored trials require a source-matched documentation tool and a new native admission.
