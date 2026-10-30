# Why the signed Linux ty_server e2e rebuilds

The first unchanged workspace test-build on signed Ohm 1.99.0-21 ran 51 full rustcs and 50 stock Wild links. The original ty_server e2e kept all 736 literal compiler arguments from the cold build. Its only direct Rust extern reported dirty by Cargo was Insta. The unchanged and restored e2e matched the independently empty original executable byte for byte. In that 619-unit archive, the edited e2e was `a1c402ed…` and the independently empty edited e2e was `feb60b6a…`. An independent whole-file comparison isolated the difference to the `.rodata` section-header `sh_entsize` field (8 versus 0) and the GNU build ID. Every other byte matched. The independently seeded 309-unit histories below established complete edited-output equality for the focused comparisons. [Original whole-file comparison](https://github.com/astral-experiments/ohm/blob/8e5bcb16e04cf2ffc37c105ce672f4c7d6313d5e/scripts/packaged-release-workspace/LINUX_RESULTS.md) The workspace archive records the physical processes and products. The following focused controls establish causality. [Original 619-unit run](https://github.com/astral-experiments/ohm/actions/runs/41114085548)

On Ruff `93526150`, only ty_project’s dev dependency asks Insta for its Ron feature. The ordinary isolated e2e selection uses 300 units without Ron and reaches zero compilers and linkers twice. Adding Insta defaults and redactions selects 308 units and still reaches zero. Adding only `insta/ron` gives the same Ron and Insta features as the workspace. It selects 309 units and causes exactly two full compiles and one Wild on each repeat. Removing Ron returns to zero. All visits retained the same 200-test inventory and passed the selected LSP diagnostic test. [Ruff manifest](https://github.com/astral-sh/ruff/blob/93526150df078af7dd8fc4226cdcc469539d2001/crates/ty_project/Cargo.toml#L67) · [Isolated e2e](https://github.com/astral-experiments/ohm/actions/runs/41118503524) · [Feature intervention](https://github.com/astral-experiments/ohm/actions/runs/41119367004)

Rustc writes a deliberately missing `ron-….d/ohm-foreign-span-bytes` when a proc macro observed foreign bytes and public dependency hashes are in use. Cargo reported that exact missing operand, compiled Ron, skipped Insta after checking its dependency and marked the e2e stale through Insta. Ron’s complete 12-member rlib remained byte-identical. Its separate rmeta changed on the first two repeats. Insta’s complete 18-member rlib and its rmeta remained byte-identical while Cargo advanced the existing rlib’s mtime. The e2e’s own depfile had no assembly or foreign-span marker. Earlier tests with the same locked Ron identified three Serde joins of foreign bitflags tokens. Removing just that observation produced stale native results. [Compiler marker](https://github.com/astral-experiments/ohm-rust/blob/c79998a5cd143c445a4b2528f20953b176a65c5d/compiler/rustc_interface/src/passes.rs) · [Cargo #261 and the stale controls](https://github.com/astral-experiments/ohm-cargo/pull/261)

| Existing Cargo, same signed rustc and Wild | Each of three unchanged builds | Real edit and restore, each |
| --- | --- | --- |
| Shipped #294 | 2 full, 0 link-only, 1 Wild | 18 full, 0 link-only, 2 Wild |
| Strict #293 | 3 full, 1 link-only, 2 Wild | 20 full, 0 link-only, 3 Wild |

On #293, the e2e used an actual .rlink and `-Z link-only` while running Wild. Ron still compiled. The Ruff Unicode build script and Unicode library also compiled, adding another Wild. The extra dependency-recheck path on #293 applies even though Cargo skipped Insta after checking it. The #292 path requiring all direct dependencies to be fresh cannot explain this result. The initial and restored complete e2es matched across both receivers at `e0a1f22f…`. The real edit and an independently empty edited target matched across both at `23f3dbc5…`. [Matched native histories](https://github.com/astral-experiments/ohm/actions/runs/41120192553) · [Cargo #293](https://github.com/astral-experiments/ohm-cargo/pull/293)

An earlier private `psm/out/libgcc_s.so` changed the e2e’s exit to 83 with each receiver, including a missing-executable control. Malformed input gave Cargo 101 in all four runs. Removing it restored the exact cold executable and passed the test. The raw trace records successful opens of this path, the selected stock Wild, and Wild’s diagnostic naming the malformed input. The provider-only trace projection retained thread-spawn edges and omitted Wild’s separate nonthread fork edge.

In the feature intervention’s first unchanged run under strace, the physical Cargo lived for 1.650 s, Ron for 0.541 s and the e2e compiler for 0.780 s including 0.175 s in Wild. This concerns one selected test and is descriptive. No timing comparison across the two receiver workers or 2× whole-workspace claim was enrolled. [Independent off-clock native verifier](https://github.com/astral-experiments/ohm/actions/runs/41121963155)

### Replay

Run the offline reader from the repository root. It checks the raw checksums, all 736 original arguments across seven workspace visits, the direct extern paths, feature changes, archive members, fingerprints, native rosters and complete e2e file checksums. Its four mutation controls independently reject a missing compile, a mislabeled link-only job, a silently accepted malformed provider and a wrong independently clean e2e.

```sh
python3 -IB scripts/ohm-cargo-301-linux-ci/e2e-result/verify.py --self-test
```

To reacquire the native results, dispatch the four focused jobs with this one command. The first two workers independently run the plain and feature-controlled histories. After these finish, two further empty workers use the same signed -21 rustc, driver and Wild with shipped Cargo and source-built strict #293 Cargo. All four reuse the original workload scripts and pinned inputs. The 619-unit starting observation is preserved here and is not reacquired by the focused workflow.

```sh
gh-auto workflow run ci.yml --repo astral-experiments/ohm \
  --ref charlie/qa-gnu-native-reader-linux-ci-20261030 -f task=e2e-replay
```

The name `all_actual_jobs` covers every physical rustc and Wild process on the reported nonempty-target visits. The cold and independently empty visits retain totals and the root process records. The e2e output means the complete ELF. The selected behavior was `pull_diagnostics::on_did_open`. A valid provider installed a genuine pre-initialization object. The missing-executable control removed the test program before Cargo ran the same command. Both that arm and the ordinary arm observed the earlier provider.

The focused acquisitions pin three upstream sources. The shipped toolchain uses Rust `c79998a5cd143c445a4b2528f20953b176a65c5d` and Cargo `2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c`. The strict Cargo is `735e1528ed741015c57676dccf05dbdc0ff7bed1`. The rerun authenticates the original native #293 artifact and will stop if GitHub no longer retains it. The offline verifier uses only this directory. [Pinned #293 source build and acquisition](https://github.com/astral-experiments/ohm/tree/b3a1bbd38e07293168f06cb21648821b8cacd206/scripts/ohm-aarch64-fallback)

Two setup attempts stopped before compilation. The first used an incorrect runner working directory. The second could not import a helper under isolated Python. Both remain outside the results. [Working-directory failure](https://github.com/astral-experiments/ohm/actions/runs/41118262930) · [Import failure](https://github.com/astral-experiments/ohm/actions/runs/41119882767)
