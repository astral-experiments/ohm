# Effect of Rust #277 across Ruff’s workspace tests on Apple Silicon

With signed Ohm 1.99.0-20 Cargo, Rust #277 removed four rustc launches and one Apple linker launch on each of three `cargo test --workspace --no-run` commands. Both compilers linked the same 60 of the 83 test executables. The additional link saved by #277 built a build-script executable. These measurements count processes. [Rust #277](https://github.com/astral-experiments/ohm-rust/pull/277) · [Native run and full artifact](https://github.com/astral-experiments/ohm/actions/runs/41066385681)

| Command | Parent / candidate full rustc | Parent / candidate Apple ld | Test executables linked by either |
| --- | ---: | ---: | ---: |
| After the Ruff diagnostics edit | 74 / 70 | 66 / 65 | 60 |
| First unchanged test build | 72 / 68 | 66 / 65 | 60 |
| Second unchanged test build | 72 / 68 | 66 / 65 | 60 |

The two registry instances of `zlib-rs`, the `ty_vendored` build script, and the `ty_vendored` crate account for all four reductions. The candidate still compiled `ron`, `objc2`, and `libm`. After the real edit, the `ty_server` e2e test rebuilt, physically linked, gained the new regression in its 195-test inventory, and ran that case. The complete sizes and SHA-256 values of all 83 returned test programs matched a separate empty build for the same compiler on all three commands. [Ruff #28988](https://github.com/astral-sh/ruff/pull/28988)

The parent is `444c0273a2e2bc0b161e988d43c882349bc2d7a6` and the candidate is `82911b516fb35608fd70ada4deb6f8429277f410`. The verifier also compares the parent against the archived #276 workspace run. It requires the same compiler roster and linked test identities in the two independent parent runs. This experiment used signed Cargo. The focused typeshed measurement with Cargo #293 has its own provider and link evidence. [Earlier workspace run](../native-apple-ty-links-v1/) · [Focused Cargo #293 test](https://github.com/astral-experiments/ohm/actions/runs/41068365290)

## Reproduce the counts

Run in this directory with Python 3.11 or later and its sibling `native-apple-ty-links-v1` directory present.

```sh
sha256sum -c SHA256SUMS
python3 -IB verify.py
```

The portable archive preserves both native bootstrap manifests, loaded driver identities, source and signed-release receipts, each kernel execution stream, Cargo JSON, registry dep-info, test inventories and verdicts, and the full output hashes from the runner. To rebuild it or replay the complete Actions ZIP directly, its artifact ID is `12985485763` and its SHA-256 is `45012e8b81dae37c06c2469cdaf08746cae78f087289ee830da25ec29f8f32e9`.

```sh
gh-auto api repos/astral-experiments/ohm/actions/artifacts/12985485763/zip > workspace.zip
python3 -IB verify.py --source workspace.zip
```
