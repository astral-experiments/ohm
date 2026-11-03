# The existing Ruff test executable at the native link boundary

On GNU/Linux, signed Ohm -23 runs the Ruff #29697 integration target through rustc, GCC 13, collect2 and Wild 0.11.0. On the first unchanged workspace test build, all four executed programs could read the complete previous 227,979,336-byte executable at their common output path. Wild published a fresh inode whose full SHA-256 matched the previous output.

The genuine Cargo test build selected 55 workspace default members and reported 102 executables. Ruff changed from 157caa55a51ebae4fa541d31697e3af9a6c32ccf to bfa2407e98ee1343caeefd02b4b69043509baa8c. The OLD executable failed the changed commands::debug_command snapshot on NEW. OLD on OLD and both NEW runs on NEW passed. Each complete harness inventory contained the same 200 test names. The edited and unchanged ELFs both matched the independently compiled NEW executable. [Signed census and clean reference](https://github.com/astral-experiments/ohm/actions/runs/41617756983)

| Stage | Prior inode at all four genuine execs | Canonical inode when Cargo returned |
| --- | ---: | ---: |
| Real Ruff edit | 7753022 | 7752955 |
| First unchanged build | 7752955 | 7752165 |

Only three of 446 final native arguments differed between the edited and unchanged links. GCC generated a new native-plugin resolution pathname. Rustc generated a temporary raw-dylibs search directory and a new pathname for symbols.o inside it. All other arguments matched byte for byte in these two ordinary links. The four-byte native symbols challenge establishes why both files and actual library searches still require authentication. [Original lifetime run](https://github.com/astral-experiments/ohm/actions/runs/41701252791) · [Original native challenge](https://github.com/astral-experiments/ohm/actions/runs/41671338175)

A separate Linux capability control demonstrates why keeping the old inode can corrupt the result. A preexisting read-only descriptor caused an exclusive output lease to refuse with EAGAIN. An O_PATH descriptor allowed that lease, then reopened the old generation for writing after lease release. That write affected the canonical path only when it still identified the old inode. The normal fresh publication isolated it. This control is available as output_custody.py. Filesystem clone support returned EOPNOTSUPP on the local ext4 volume.

Reopen the signed acquisition with the following commands. The reader authenticates 6,136,928 bytes, the complete native argv, eight process image/canonical joins, three artifact inventories and four test verdicts. The ZIP SHA-256 is 7b4b0e8d8402eab3902b744f05ad6c5c4195146302fe9f1ba8f1e96b9c9ac49b.

    gh-auto api repos/astral-experiments/ohm/actions/artifacts/13263134782/zip > original.zip
    python3 -IB read_lifetime.py original.zip | cmp - lifetime-summary.json
