# First-edit uv-client wall on three production compilers

This private workflow checks the parent of astral-sh/uv#21041 with `cargo check -p uv-client --locked --offline -j8`, restores a verified warm cache, applies the landed source change in place, then times that same ordinary Cargo command. The three production SDKs contain corrected Ohm −22, corrected −22 with #296 and #306, and that stack with the callable receiver change. All use the signed −22 Cargo executable.

The frozen `measurement-plan.json` assigns all six orders of the three compilers to each of two independently built cache histories. Each of the 36 timed children runs uninstrumented. The clock includes process launch through the return of a blocking wait. A signal-driven watchdog remains armed outside that wait. A native sleep probe tests elapsed time, nonzero exit and the timeout path before and after the panel.

The treatment also runs a separately restored signed Cargo build-analysis visit in each history. Its raw unit ready, start, metadata and finish records show when upstream results unblock dependents and how long uv-client remains the only active compiler. A second, separately restored verbose visit checks the actual eight rustc commands, while an unchanged repeat must launch zero units. These logged clocks are diagnostic. The reader authenticates real metadata outputs, linked behavior, native cache transitions and both original SDK producers.

`trio_score.py` reconstructs both registered wall comparisons and their two history splits from the original records. The candidate-versus-mature threshold is parity and the candidate-versus-corrected-stock threshold is 2×. The two exact one-sided sign tests use Holm adjustment.
