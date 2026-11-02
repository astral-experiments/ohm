# Ruff #25492 on the original Ohm #253 Linux toolchain

The ordinary Ruff CLI build consumed 61,066,244,767 retired user instructions after the CRLF fix. It ran 27 full rustc commands and two Wild links. Repeating the same build consumed 575,439,525 instructions with no rustc or linker process. Cold OLD and independent empty NEW consumed 1,231,130,932,690 and 1,231,255,307,763 instructions, respectively. The isolated command was `cargo +ohm build -p ruff --bin ruff --locked --offline -j4 --message-format=json`. Each visit returned 357 Cargo products. [Original worker](https://github.com/astral-experiments/ohm/actions/runs/41460616635) · [Frozen registration](https://github.com/astral-experiments/ohm/blob/f13962a93be15adcb600fa48e1ea2ae4d8168034/scripts/ruff-line-end-25492/PLAN.md)

All four visits used the same inherited environment at the actual watchdog, Cargo proxy and signed Cargo executable after accounting for the deliberately independent clean target/build paths. Exactly 356 products used the same literal native-tool namespace `v2-81804c127ee1d049` on every visit. The arithmetic-calibrated hardware counter encloses the Cargo process tree. It records one total per visit. The earlier sampled worker changed the native-tool namespace and its edited and unchanged prices are ineligible. [Control history](CONTROL.md)

The changed library was compiled both without features and with `get-size,serde`. The CLI directly named the latter archive. Both feature variants returned 2 and 3 for the registered ASCII and Unicode CRLF byte offsets on OLD, and 1 and 2 on edited, repeated and empty NEW. LF, bare CR, last-line offsets, the two plain CLI verdicts and two captured notebook diagnostics matched their controls. The four CLI diagnostics were identical even on OLD, so the independently linked typed programs discriminate the edit. The incremental and empty NEW CLI executables have different raw hashes, retained in the packet. Every one of the 644 selected native object payloads matched empty NEW.

| Owner | Objects | Reused original inode and bytes | New inode, same bytes | Different payload |
| --- | ---: | ---: | ---: | ---: |
| `ruff_source_file`, both instances | 171 | 168 | 0 | 3 |
| `ruff_db` | 217 | 215 | 0 | 2 |
| `ruff_linter` | 256 | 254 | 1 | 1 |

This is a single baseline, with no optimized arm. The one rebuilt, byte-identical object leaves little direct evidence of a large missed-CGU opportunity in these three owners. The 27 actual compiler executions justify isolating the costs of validating and emitting the same consumer artifacts. Half of the edited work is 30,533,122,383.5 instructions.

[Compact original hardware clocks, native rosters, object counts and content identities](ordinary.json) · [Complete 6,857,620-byte archive](https://github.com/astral-experiments/ohm/actions/runs/41460616635/artifacts/13150085836)

From an authenticated OSS checkout, the raw packet can be verified with:

```sh
gh-auto api repos/astral-experiments/ohm/actions/artifacts/13150085836/zip > /tmp/ruff-line-end-ordinary.zip
printf '%s  %s\n' c088eba27ed747cbb719332209dfe801682168cf1b2268831a48afa9a1d4c588 /tmp/ruff-line-end-ordinary.zip | sha256sum -c -
unzip -p /tmp/ruff-line-end-ordinary.zip edit/clock.json
```
