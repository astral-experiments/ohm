# Why the same signed Wild command emits two different Ruff executables

Signed Wild 0.11 produced both complete output files from the same 446 arguments, ordered 409 native inputs, paths, content and CPU affinity. The real Cargo pipe yielded one worker. Providing one further GNU jobserver token yielded two. Four signed full emissions in the order 1, 2, 2, 1 repeated the same two complete files in both genuine source states. The unmodified CLI, explicit worker overrides, tracing and the source instrument all agreed in their respective worker configurations. The source recorded 37,530 contributing input sections on each observed state.

The final group supplies the output section header. With one worker group 14 contains one 8-byte-entry constant section from compiler_builtins cgu.155. With two workers the last contributing group is 159, with six entry sizes from core cgu.0, including ordinary zero-sized-entry attributes. The signed OLD files have SHA-256 f203086d… and 6d372446…. The signed NEW files have SHA-256 86b94323… and d236bd03…. The section occupies 5,851,098 bytes. Libelf's full-file update reports “invalid section entry size” on the eight-byte header and accepts the zero form. The derived build ID also changes. The upstream fix merges section attributes across all file groups. [Upstream fix](https://github.com/wild-linker/wild/pull/2816)

The first real stock token-repayment check sampled the fork parent's successful return and caught the token still owned by the cleaning-up child. The original refusal is preserved. The successful run waited separately for actual repayment. The longest post-return interval observed was 34.94 ms. [First actual run](https://github.com/astral-experiments/ohm/actions/runs/41712333191) · [Complete repeat](https://github.com/astral-experiments/ohm/actions/runs/41714102566)

From this directory, the following commands independently inspect the compact physical receipts and full ELF section table. The raw archive also contains the per-stage invocations, actual output/header/outside-section operands, libelf verdicts, group and physical input rows. The archive contains no second full native executable.

    gh-auto api repos/astral-experiments/ohm/actions/artifacts/13268484811/zip > groups.zip
    python3 -IB read_groups.py groups.zip 3eadfc7c73d34ec3ad15d99d6dcded32e44406404387a77a69d218703d805d5d a3769c76040427f115a8fda7c376d5c019b81d72 41714102566 > actual.json
    cmp actual.json groups-qualified-reopened.json
