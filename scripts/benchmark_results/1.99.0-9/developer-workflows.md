# Developer workflows for Ohm 1.99.0-9

We ran five workflows in Ruff/ty and uv with stock Rust 1.99.0 and Ohm 1.99.0-9. Each row shows the median of four runs per toolchain on the same 32-vCPU Linux devbox with eight Cargo jobs. Each run started with fresh build artifacts. The timer included the edit and command sequence and excluded warmup. These runs enabled procedural-macro and native-tool trust. [Benchmark settings](../../../BENCHMARKS.md#recorded-measurements)

| Project | Workflow                          | Rust 1.99.0 | Ohm 1.99.0-9 | Time saved |
| ------- | --------------------------------- | ----------: | -----------: | ---------: |
| Ruff/ty | Edit → focused test               |     17.93 s |      17.93 s |     −0.02% |
| Ruff/ty | Edit dependency → downstream test |     17.80 s |       4.97 s |     72.09% |
| Ruff/ty | Edit → check → test → check       |     26.78 s |      25.97 s |      3.04% |
| Ruff/ty | Check → build → check             |    105.93 s |      69.37 s |     34.51% |
| Ruff/ty | Edit → fmt → clippy → test        |     37.57 s |      27.44 s |     26.95% |
| uv      | Edit → focused test               |     21.66 s |       9.19 s |     57.55% |
| uv      | Edit dependency → downstream test |     25.13 s |       3.05 s |     87.86% |
| uv      | Edit → check → test → check       |     26.01 s |      12.48 s |     52.02% |
| uv      | Check → build → check             |    139.39 s |      72.33 s |     48.11% |
| uv      | Edit → fmt → clippy → test        |     28.90 s |      14.61 s |     49.45% |

Ruff/ty and uv contributed 40 accepted measurements each. The host-activity checks discarded nine attempts on Ruff/ty and four on uv. [Ruff/ty timings](developer-ruff.json) · [uv timings](developer-uv.json)

## Codex

Four Codex runs on three machines stopped during check → build → check. In the final run, all nine attempts at one stock Rust repetition exceeded the CPU limit. We excluded all 74 partial timings.

| Host                                          | Partial timings excluded | Discarded attempts |
| --------------------------------------------- | -----------------------: | -----------------: |
| `charlie-ohm-9-codex`                         |                       36 |                 12 |
| `charlie-ohm-9-ty`                            |                        6 |                  4 |
| `charlie-oss-3`, first run                    |                       16 |                  4 |
| `charlie-oss-3`, eight retries per repetition |                       16 |                 12 |

Codex completed its individual-command benchmarks and its recorded session on 1.99.0-9. The last complete developer-workflow comparison for all three projects used 1.99.0-8. [Individual commands](../workflow.json) · [Recorded sessions](../sessions.json) · [1.99.0-8 developer workflows](../developer-workflows.json)
