# Does Cargo touching Insta's byte-identical archive explain the e2e link?

This is one unscored, focused diagnostic. It uses the 309-unit Ruff 93526150
`cargo +ohm test -p ty_server --test e2e --no-run --locked --offline -j8
--message-format=json --features=insta/default,insta/redactions,insta/ron`
on Linux x86-64. The signed -21 Rust and Wild are identical on two workers.
One uses signed Cargo 2d44bd4. The other uses existing strict Cargo 735e1528.
The Rust and proc-macro inputs, Ron recompile and Cargo's scheduler run normally.

One archive is enrolled from the cold e2e Rust compiler's literal `--extern`,
the Cargo JSON and a complete immutable copy. An adapter observes only the matching
physical Cargo executable and selected existing archive device/inode. The normal
arm delegates `futimens` unchanged. Under the hold policy, the existing complete
archive must equal the read-only reference on the open file descriptor, the
source identity must remain stable, and Cargo must ask to omit the access time
and change the modification time. Only then does that same thread submit a real
`utimensat` omitting both timestamps. All other operations pass through. Both
policies use the same hooked executable and environment. The calibration includes
a hard link, another inode, another executable and a same-size changed archive.
An independent empty-target ordinary arm runs a cold build and repeat without
an adapter. Its private outputs are parked before the hooked cold build and
unarmed repeat. The initial attempt switched LD_PRELOAD mid-generation, rebuilt
306 units and stopped at the untouched inode guard before any hold. [Rejected
cross-environment control](https://github.com/astral-experiments/ohm/actions/runs/41137063070). Each touched file, time, fd and native
process is recorded, with an independent strace of the actual syscalls and execs.
The archive, its 18 members, every distinct returned ELF, Cargo JSON and native
verdict streams are retained.

The registered endpoints are two unchanged commands, the actual reversed
83a3afc3 trivia edit and restoration. A valid higher-priority psm/out/libgcc_s.so
runs preinit and yields exit 83 for this e2e. A malformed peer must yield Cargo
101 and Wild must name the bad file. Forced missing executables and independent
empty builds qualify both, together with removal/repair, an invalid Rust input
and same-path clean edited/original ELF checks. A fresh store with a preset native
provider has precisely that single input file. The signed native link workflow is
unsafe if a held visit preserves a wrong program or accepts malformed input.
If both policies do identical native work after an actual positive hold, this
intervention does not isolate the downstream work. A positive skip without these
receiver checks cannot advance. No time test or whole-workspace extrapolation is
registered.

```sh
gh-auto workflow run ci.yml --repo astral-experiments/ohm \
  --ref charlie/qa-signed21-insta-archive-time-20261030 -f task=insta-archive
```
