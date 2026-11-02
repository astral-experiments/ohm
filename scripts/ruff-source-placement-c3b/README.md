# Guarded source placement compiler factory

This independent recipe builds the normal #337 compiler and the complete guarded source-placement compiler from freshly checked-out Git trees at the same paths. The candidate is `ed0262f9bdc384576925229764971f23a141c95f`, with tree `d4a6f3ab70185bec03263086863376298c293360`. Its immediate parent is C2. Both new kits run the same register coalescer, released LLVM, Cargo and Wild. Each rustdoc writes a real HTML page.

The factory first reconstructs #337, C2 and the candidate. It checks all differences from #337, all changed crate roots, and every file digest in the separately supplied three-file patch. The physical construction traces and native outputs are retained for each role. The directional native guard and C++ code come from the actual candidate checkout.

To run the reviewed factory from this QA checkout, use the following command with its actual published QA HEAD.

```sh
/home/dev-user/.local/bin/gh-auto workflow run ci.yml --repo astral-experiments/ohm \
  --ref charlie/qa-ruff-placement-c3b-20261102 \
  -f mode=ldv-placement-c3b-factory \
  -f reviewed_head="$(git rev-parse HEAD)" \
  -f placement_source=ed0262f9bdc384576925229764971f23a141c95f
```

The matched kits and full original constructor and error records have distinct C3b artifact names. Any native Cargo or hardware cohort needs its own original receipts.
