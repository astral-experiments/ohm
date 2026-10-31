# Reopen the cold Ruff exit diagnostic

Each job produces cold-Ruff-Foff-exit-diagnostic or cold-Ruff-Kon-exit-diagnostic. Keep both original ZIPs when an observed build refuses. Run the matching commands below from this exact QA checkout on Linux with Python 3.11 or newer, zstd and b3sum. Choose the refusal reader only for a worker that rejected the native family.

    python3 -IB scripts/branch-return-execstop/reopen.py /path/to/first/artifact Foff > Foff.json
    python3 -IB scripts/branch-return-execstop/reopen.py /path/to/second/artifact Kon --refusal > Kon.json
    python3 -IB scripts/branch-return-execstop/pair.py Foff.json Kon.json

The kernel files are observed/cold-A/kernel.tsv.gz and kernel.tsv.exits.gz. The accepted case has independent closure, subsidiary exit audit and the counted native roster. A refused case has the exact original REFUSE and supplementary task snapshot, verified against its recorded generation. No count is imputed for an incomplete ledger. Both kinds of artifacts retain their SDK catalog, source, native controls, registered ordinary Cargo arguments and completed unwrapped CLI/reader. The checkout's PLAN.md records the exact acceptance rules.

From scripts/branch-return-execstop, the following commands regenerate the historical off and on receipts and exercise the host fixture suite. Both fixture destinations must be absent children of a private owned directory. The host must allow unprivileged tracing of the observer's own child.

    python3 -IB history.py /path/to/41200174886-01-13042772691.zip /path/to/41200174886-02-13043111933.zip | cmp - cold.json
    python3 -IB history.py --grades /path/to/41200174886-01-13042772691.zip /path/to/41200174886-02-13043111933.zip | cmp - grades.json
    python3 -IB test_projection.py
    python3 -IB qualify.py --preflight
    RUNNER_TEMP=/tmp python3 -IB fixtures.py /path/to/new-tools /path/to/new-receipts
