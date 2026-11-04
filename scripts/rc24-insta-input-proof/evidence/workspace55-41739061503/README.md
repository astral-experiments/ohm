# The separate 55-member Ruff workspace follow-up

Both independently enrolled hosts failed the native-output gate. The two-host workspace speedup is unqualified. The six independent focused `ty_project` hosts follow their own previously registered decision.

Both orders ran ordinary `cargo +ohm test --no-run --locked --offline -j4 --message-format=json` at the default workspace root on the real Ruff #29697 edit. The exact old and new source revisions, normal command, stock signed -24 compiler/LLVM/Wild and gate are in `workspace-enrollment.json`. The Cargo parent and candidate were compiled under the same release profile. Each role independently populated fresh build and target directories for the same fixed Ruff source and signed SDK. The separate process-owning exec-stop census was outside the ordinary hardware readings. [Original jobs](https://github.com/astral-experiments/ohm/actions/runs/41739061503) · [Frozen decision](https://github.com/astral-experiments/ohm/blob/e58f3032cfb217136bd72f787f63c7fa64098a98/scripts/rc24-insta-input-proof/workspace-enrollment.json)

| Boot order | Original pair gate | Parent first unchanged instructions | Candidate instructions | Observed parent/candidate |
|---|---|---:|---:|---:|
| PC | refused | 124,226,175,242 | 79,956,486,687 | 1.55367× |
| CP | refused | 124,222,285,553 | 79,956,072,550 | 1.55363× |

The primary, edited, second unchanged, repair and independently empty values are preserved separately in `verified.json`. Both same-source error checks and the actual edited native positive/failing/repair comparisons ran off the primary counter.

## Parent e2e refusal

In PC order, the ordinary edited and settled e2e, repair, and independently empty e2e matched across both roles at `9827cae719308452d3293caadd022351e4a940b9c01502c3da339d12c036ed25`. The parent's separate observed visit returned `67a829d0ca8d4bdc5a1b078b1dc502ba42a3163a19c103400c60f73e1c9b5a47`. In CP order the candidate ran first and produced precisely that same alternate during its separate observed visit. The parent ran second and matched clean. In both orders the ordinary edited, settled, repaired and empty e2e images agreed. Each image is 226,598,344 bytes. Exactly 32 bytes in the GNU build ID (offsets 896–927) and one byte in the nonloaded `.rodata` section header's `sh_entsize` (offset 226,596,416, observed 0, clean 8) changed. Every other ELF byte matched. All four `PT_LOAD` segments matched after removing only the proven build-ID bytes. This classification leaves the registered refusal intact.

The two roles had identical SHA-256s for all 102 edited products on both hosts. Within each of the four roles the edited `ty_project` libtest differed from its own empty build. Its captured section payloads differed only in `.note.gnu.build-id`. A full header comparison on that particular body would require a separately saved ELF. All 102 edited product SHA-256s and each later overwritten test product's section hashes are in the raw controls. The separate ledgers name any secondary bodies whose original SHA changed between visits. Only the selected e2e had its complete bodies archived by the worker.

## Actual compilation and linking

| Order/role | Full compiler owners | Link-only rustcs | Stock Wild invocations | `ron` local instructions | `insta` local instructions | `insta_cmd` local instructions |
|---|---|---:|---:|---:|---:|---:|
| PC/candidate | `ron` | 50 | 50 | 9,328,544,671 | 0 | 0 |
| PC/parent | `insta`, `insta_cmd`, `ron` | 50 | 50 | 9,330,714,761 | 41,652,552,875 | 2,586,446,604 |
| CP/candidate | `ron` | 50 | 50 | 9,329,882,120 | 0 | 0 |
| CP/parent | `insta`, `insta_cmd`, `ron` | 50 | 50 | 9,330,787,159 | 41,641,738,824 | 2,584,335,200 |

## Offline readback

`raw-controls.tar.xz` and `controls-index.json` preserve every non-ELF member from both original ZIPs byte-for-byte, deduplicated by SHA-256. This includes the original Cargo JSON lines, native test inventories/stdout, complete ELF section ledgers, both compiler errors, hardware counters and kernel exec epochs/argv. The public packet keeps one actual compressed clean e2e plus a delta which reconstructs the exact compressed refused generation. The offline reader rehashes and parses both full native bodies and independently recomputes the complete acquired difference, Cargo/PMU stages and true compiler/link rosters.

`verified.json` was computed against the complete originals, including the other saved (cold) e2e bodies. The compact reader verifies those additional bodies' original whole-file, section and compressed-stream commitments. The original-ZIP path physically reopens every body. The original archive IDs, byte lengths and SHA-256s are in `artifacts.json`.

```sh
sha256sum -c SHA256SUMS
python3 -IB reopen.py | diff -u compact-reopened.json -
```

With the two original ZIPs saved as `workspace-PC.zip` and `workspace-CP.zip` in a separate directory alongside `run.json`, `artifacts.json` and `expected.json`, the full reader revalidates the original archive hashes before opening their contents.

```sh
python3 -IB workspace-review.py "$WORKSPACE_ORIGINALS" --suite "$PWD"
cmp "$WORKSPACE_ORIGINALS/verified.json" verified.json
```
