# Group-exit fixture for the Linux exec observer

Run as an ordinary user on a two-CPU-or-larger x86-64 Linux host with ptrace, native cc, OpenSSL development headers, Python 3.11+ and the original GNU stock Wild. Both destination paths must be absent and their parent must exist. The fixture restricts its own process and children to two available CPUs.

```sh
entry=scripts/branch-return-execstop/group_fixtures.py
python3 -IB "$entry" run "$tools" "$out" "$sdk/lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"
python3 -IB "$entry" reopen "$out" | cmp - "$out/group-v2/qualified.json"
```

Archive all of `$out`, even on rejection. The first command builds and exercises the observer, the three fixture sources and their actual native outputs. Six original positive cases, both untraced clone refusals, 16 original mutations and 12 executable-projection refusals run first. Two four-group racing commands and one active group independently enumerate eight worker TIDs and the real inner exec in each group. The remaining controls verify the actual GNU stock Wild fork helper, its two independently parked workers and native output returning 37, plus a genuine seccomp-notified pending exec which must refuse. Thirty additional mutations cover the group gate, park records, real pre-exit and final waits, and closure counts. Each new successful ledger requires schema 2. A disappeared thread or missing wait cannot count as success.

The second command runs only the trusted checkout's Python. It verifies the two originally refused official streams under both the exact old and new readers, rechecks the native records, all archive bodies, source checksums and compiler/observer identities, and reproduces the compact certificate byte for byte. It works after moving the result directory or removing execute permissions from every archived binary. The inherited raw and verdict remain in `original/` and `qualified.json`. New source, command, terminal, raw ledger, executable and per-host evidence live in `group-v2/`. Each outer archive must preserve these original bytes and establish its own official acquisition and host identity. The historical observer's cold certificate belongs to the original binary.

The source-only change is based on `2969895dc49c9d8970ef121e1ff024ef001dc7ce`. The reviewed runtime patch SHA-256 is `b7e4709015b8f4b2b026713361a1d840dec549d193831809e710fd1e8ba03e9f`. The preceding native diagnosis packet is `a3a7f29c1fb00ac0eaa4a59537bbfde9322155e75c9d510649b9f270b008518a`, with terminal replay `131574d245bfe4101d3c8f84c0f1ed692bef37ef6103cbf7ece98f9a384ebd69`. It qualified 32 racing families, four active families and 24 exact Wild links on kernel 6.8.0-147-generic. The full Ruff source and a fresh Linux 7.1.4/x86-64 host require a separate unscored contact. The original failed cases are the literal compressed members from [position 01](https://github.com/astral-experiments/ohm/actions/runs/41283234972/artifacts/13074429247) and [position 02](https://github.com/astral-experiments/ohm/actions/runs/41283234972/artifacts/13073609945), with exact archive/member checksums and failure reasons in `group_checks.py`.

The fork fixtures run outside the hardware meter. The source component keeps the parent revision’s meter, role bindings and workflows.
