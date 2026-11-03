# Native qualification of the next Ohm source pins

The release source verifier accepted Rust `364b82f01c52f77e870cdb1bb5b9f66e2fa89694` and Cargo `d5185be60b88e36ffb5e9daeb543b9f14d077a37` on Linux x86_64 and macOS arm64. The Rust commit updates the Cargo gitlink on [Rust #347](https://github.com/astral-experiments/ohm-rust/pull/347). The Cargo commit joins [#436](https://github.com/astral-experiments/ohm-cargo/pull/436) to the existing [#431](https://github.com/astral-experiments/ohm-cargo/pull/431), [#433](https://github.com/astral-experiments/ohm-cargo/pull/433) and [#435](https://github.com/astral-experiments/ohm-cargo/pull/435) stack. The [manifest used in QA](24.json) carries the Clippy, rustfmt and Wild pins from signed -23.

Each native host built the release-profile all-static ThinLTO Cargo and a stage-1 release-mode rustc and rustdoc. Each ran 112 ordinary Cargo commands across signed -23 controls, mixed toolchains, candidate runs, fresh builds and repairs.

| Commands per host | What was checked |
| ---: | --- |
| 45 | A concurrent include-file save, contradictory path spellings, preserved timestamps, upgrade, failure and repair across check, build and test compilation |
| 16 | Valid edits, independent clean builds and repeated repaired builds |
| 14 | A client directly reading a rebuilt producer's metadata file, including clean E0308 controls |
| 37 | Cold and repeated doctest language gates, Cargo-only migration with the same Rust executables, overlapping doctest harnesses, native archive edits and worktree Git ownership |

An independent reader reopened the four original ZIPs, every Cargo stdout and stderr hash in the 37 additional cases, both candidate Cargo binaries and eight repaired/clean native comparisons per platform. The Linux executable bytes matched and were executed again after download. The macOS reader reconstructed each entire clean binary by replacing only the verified compiler temporary names in Mach-O debug records and their corresponding ad-hoc signature page hashes. [Native run and four original archives](https://github.com/astral-experiments/ohm/actions/runs/41620033827) · [Reopened verdicts, binary hashes and archive sizes](reopened.json)

The first unchanged Ruff check when upgrading an existing signed -23 target ran 336 unit compiles and five LLVM probes. Each of the next two unchanged checks ran one compiler. [Upgrade measurements](https://github.com/astral-experiments/ohm/blob/50cff18f980dc6ea8acf5f50d9abcd9fe4692632/scripts/ruff-join-proof/evidence/reader/upgrade/README.md)

Re-run the nonpublishing native qualification from an authenticated Ohm checkout.

```sh
gh-auto workflow run ci.yml -R astral-experiments/ohm \
  --ref charlie/qa-rc23-integrated-inputs-and-doctests-20261103 \
  -f reviewed_head=d1d5b8f9626ca497e8a50cc6fd170156547bd74f
```

An earlier source-verifier run stopped on a scratch manifest without its sibling schema before building either toolchain. The enrolled run uses the canonical manifest directory and the schema from the signed release. [Earlier pre-build refusal](https://github.com/astral-experiments/ohm/actions/runs/41619362420)
