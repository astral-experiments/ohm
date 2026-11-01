# Private GNU and Apple Silicon distribution smoke

This manual QA workflow builds Rust `1bc7b35699479d5899a2935d79392b7bdaf7497d` with Cargo `4591cf45cc10abb19d2456c40b99606e08167f29`, Clippy `0d76dc1f4fe7ffb86ee5e1a8a9cc4d6bef1d1bf6`, and rustfmt `3c9620c92b01e6c393324729c4861823cc3676e2`. The manifest, optimized distribution recipe, native tools and installer come from Ohm `64e2c3213fd69f28dfbcce3c18495507156f81fe`. The workflow checks these inputs against its direct parent before the build.

The source readback reconstructs the previously qualified Rust parent and exact full Cargo tree. It adds the single integrated Rust Git commit, validates its gitlink and reopens each reviewed Clippy/rustfmt Git commit in a fresh shallow checkout. All Git transports in this directory are checksum-bound. The four-directory release source verifier runs before either native build. The build uses the release compiler and tool PGO, GNU BOLT, static Cargo native features, host and Wasm standard libraries, the pinned Wild on Linux and ordinary Xcode tooling on Apple Silicon.

One Linux assembly job checks both new distributions and writes the normal checksum-pinned installer. Separate fresh Linux and Apple Silicon jobs install each platform product and run the complete ordinary release smoke. A second private installation on each host records the physical release components and executes unwrapped Cargo builds and tests that import private, retained native symbols. The ordinary Rust dynamic-library client separately checks a private field-width edit. A two-crate Cargo check deliberately rejects E0308 and E0425, repairs the source after changing a dependency body, and verifies the genuine warning on repetition and from an independent empty target. Its four literal Rust source files come from the in-tree regression and the originating source checkout verifies them before bootstrap.

The only persistent outputs are QA branch commits and private Actions artifacts. The workflow uses read-only repository permissions and requires its exact reviewed head, branch and first attempt. Use `gh-auto` from the checked-out packaging QA branch to create a fresh enrollment.

```sh
head=$(git rev-parse HEAD)
/home/dev-user/.local/bin/gh-auto workflow run ci.yml -R astral-experiments/ohm \
  --ref charlie/qa-integrated-native-release-smoke-20261101 -f reviewed_head="$head"
```

The platform `qa-dist-*` ZIPs hold the exact newly built `.tar.gz`, source provenance, and checksums. The `qa-integrated-installer` ZIP contains the assembled global manifest, checksums and generated installer. Each native `integrated-smoke-*` archive contains the unmodified release smoke's stdout and stderr, installed file hashes, raw Cargo diagnostics, executable outputs and wrong-expectation controls. To replay the release shell offline, extract one platform ZIP and the installer ZIP into the same directory, provide the matching upstream rust-analyzer, and run `bash scripts/smoke-test-release.sh <directory> ohm-1.99.0-22 <target> 0d76dc1f4fe7ffb86ee5e1a8a9cc4d6bef1d1bf6` from the reviewed checkout. The registry entries consumed by the release shell must be accessible on replay. The source and CI retention settings are listed in `.github/workflows/ci.yml`.
