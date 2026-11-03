# First factory, compiler source a9d85b22

The parent produced its physical stage1 compiler and working rustdoc. The candidate stopped during compilation of the Rust build script for `rustc_llvm`. Both E0599 diagnostics are present in the original 13,944-byte `build-C.log`, on lines 269 and 270 of that build script. No candidate SDK or performance observations were generated.

`original.zip` contains all 12 original uploaded records, including the complete P and C build logs, the observed parent construction commands, the real source tree and both inputs. GitHub artifact 13172450043 was 52,900 bytes. [Original factory job](https://github.com/astral-experiments/ohm/actions/runs/41505848219/job/125484864577)

```sh
sha256sum --check SHA256SUMS
python3 -IB verify.py
```
