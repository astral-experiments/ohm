# Compatibility correctness evidence

This additive proof covers Rust base `36f01299` plus patch `4790daed` and Cargo base `6333daf7` plus patch `20b9d1fd`, with unchanged Wild `9179eb98`. The separate final Cargo confirmation covers published `76793c44` (full patch `cc8871ae`), pinned by Rust `b0e3800d`. It contains the source patches, new regression test payload, recorded Linux builds and native controls, source reviews, and retained failed/superseded attempts. It contains no toolchain binary, target cache, filesystem image, or earlier measurement archive.

Verify and extract into a new directory:

```sh
python3 verify_correctness.py \
  --archive compatibility-correctness.tar.gz \
  --manifest correctness-bundle.json \
  --destination extracted-correctness
```

The verifier checks the sealed archive and complete inventory, rejects noncanonical paths, duplicate members and links, and never overwrites an existing destination. It then checks recorded source/binary identities, three forced Rust suites, twelve required Cargo tests, six compiler compatibility cases, thirty-two Cargo policy commands, their output/argument logs and preservation receipts. The final Cargo build and five native cases are checked separately, including the corrected dylib assertion and ordinary configuration regressions. This reproduces the evidence checks; it does not rerun a compiler or independently attest the original host.

The compiler cases cover packed/unpacked debug information and GDB source/argument lookup, retained hardlink inputs, ordinary BFD replay, and LLVM 23 plugin LTO. Cargo cases cover automatic selection and opt-out, capability/metadata/opaque-response fallback, custom and late linker choices, wrappers, thin/fat LTO, packed debug, runtime output, doctests and cleanup. Source reviews cover materialized-input ownership and cleanup, archive/bitcode conversion, fingerprint/metadata policy and explicit validation before freshness.

The retained d6 Cargo routing failure exposed explicit response-file validation bypass on fresh artifacts. Patch `20b9d1fd` fixes validation before freshness; the unchanged failing response regression and a new fresh metadata-alias regression pass. Rust V2's `OutFileName`/`Path` type mismatch is retained alongside the V3 correction and successful rebuild. Earlier assembly failures and superseded attempts remain evidence, not passed executions.

The extra `build::embed_metadata_no_dylib_dep` test fails an inherited command-line assertion in the frozen native snapshot after a successful build. Its failure is preserved separately from the twelve required tests; an exact base-6333 test-suite execution is not claimed. The native control confirms actual base/candidate dylib behavior. A separate test-only supplement fixes that assertion, retains the separate-metadata assertion, and forces the dylib and Linux routing tests in CI. The corrected test passed locally on macOS, in CI, and in the separate final native confirmation. These results do not replace the original native failure.

Cargo's first published compatibility followup exposed two CI issues: the mock compiler forwarded split replay flags to stable rustc, and the ordinary noncompact/non-Wild path unnecessarily read linker configuration. Final Cargo `76793c44` fixes both; all eight enabled CI jobs pass, including six forced Linux routing tests and the dylib test on both platforms. The source review shows the new ordinary-path early return is not taken by any frozen timing configuration. This does not make the separately rebuilt final binary identical to the measured `20b9d1fd` binary.

The current Rust code passed a macOS compiler typecheck. The current Rust GitHub jobs stop before checks because the dedicated source-App client ID is unconfigured; no credentials were installed. This scope does not establish a current macOS compiler link/runtime build, full production PGO distribution, all platforms, every Cargo configuration, or a performance/adoption decision.

The archive excludes one historical 109 MB before-snapshot listing of previously protected files; its exact size and SHA-256 are recorded in `excluded-evidence.json`, and the original remains retained locally. The bounded after-comparison receipts remain included. Reproduction verifies the recorded comparisons, not all historical files on the original host.
