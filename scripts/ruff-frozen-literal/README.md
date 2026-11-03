# Qualify immutable rustc literal bytes on a real Ruff typeshed edit

One Linux worker runs the two source-built signed-23-relative compilers in PC, CP order.
Each visit uses the same four CPUs, physical Rustup alias, SDK pathname, Cargo flags,
unmodified historical Ruff checkout, 505 authenticated registry crates and private
empty build environments. The ordinary check starts with the parent of Ruff #29042 and
switches to the historical edit. All source and measurement thresholds are registered
in `registration.json`. The visit also measures the symbol-heavy parser on empty NEW.
This stage is a discovery pilot on one kernel boot.

Separate ordinary build histories produce genuine old, edited and independent clean
executables through Ruff's own packaged typeshed filesystem API. Both changed docstrings
and the typeshed source commit are checked. All 819 generated files, complete emitted
metadata, E0308/repair, complete compiler argv and matching mapped driver identities are
available for independent readback. The hosted job retains the original result on failure.

The two instrumentation methods run separate histories. One counts the complete Cargo
process tree. The other attributes instructions to the actual process image and all its
threads, including the selected rustc and separately executed generator. The readers
reject multiplexed clocks and require the ordinary edited totals to agree within 3%.
Both edited compiler improvements must reach 20%, the whole command must stay within
1% and the ordinary parser and its compiler must stay within 2% before fresh independent
workers can be enrolled.

Dispatch the manual `ci.yml` workflow on the branch in the registration with
`reviewed_head` equal to its entire current commit. Reopen its original downloaded
GitHub archive with `python3 -IB scripts/ruff-frozen-literal/read.py ORIGINAL.zip
GITHUB_ARCHIVE_SHA256 reopened.json`. The output directory must exist.
