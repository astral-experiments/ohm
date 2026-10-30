# The initial candidate failed to compile

On the genuine signed -21 Linux compiler, source parent `2d44bd4a` built
successfully. Initial Cargo candidate `8c68d93d` returned 101. The native
compiler emitted E0004 at `src/ops/cargo_report/rebuilds.rs:398:11` because
the exhaustive reporting match omitted `DirtyReason::PreviousBuildIncomplete`.
The hosted worker stopped during the Cargo build. The original Ruff and
in-tree regression commands have no observations on this head. [Failed native build](https://github.com/astral-experiments/ohm/actions/runs/41141438793/job/124356391839)

Both checkouts reopened 3,108 source entries from Git objects and built
with the same signed compiler, lockfile, release options and Cargo
`ohm-defaults,all-static` features. The original GitHub archive is
145,686 bytes and SHA-256
`423cacaa3a906d7e2c67cb35332f84c7bf009e37a00471f4937d1738f75d05d9`.
From this directory, `python3 -IB verify_build.py` reopens the complete
typed compiler output and independently checks the commits, status codes,
source location and missing enum arm.
