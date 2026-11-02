# Unmetered Ruff #29206 linter admission

Ruff changed its Unicode escape renderer between `47fdae55e8daf3f39e670e592fe0ce9457dab8d6` and `a7b52a15654cd991d7a2e212ee0cd579cd714450`. A separate signed scout recorded a disappearing external `Either::next` instantiation and a new external `Rev<CharIndices>::try_fold`. This study tests reuse of the actual dependent `ruff_linter` library. It makes no assumption about which query or symbol caused any observed donor. [Signed native scout](https://github.com/astral-experiments/ohm/actions/runs/41437313975)

The ordinary command is `cargo +ohm build -p ruff_linter --lib --locked --offline -j4 --message-format=json`. The JSON option records Cargo's original unit and registry inventories. After an authenticated fetch, all builds run offline with clean Ruff sources. The signed release and each complete matched compiler installation build empty OLD and NEW states. The parent and candidate then independently start from empty OLD and switch to the real NEW commit at the same source and target paths. The only source transition is a Git checkout. [Matched compiler factory](https://github.com/astral-experiments/ohm/actions/runs/41431225435)

Every OLD incremental object in the linter and literal provider stays open through the edit. Device, inode and complete SHA-256 distinguish reuse, identical regeneration and changed bytes. Each incremental object must equal its corresponding complete archived native payload. The original GNU archive names include a varying session suffix. The comparison retains those full names and compares the stable basename that exists in the physical incremental directory. Independent empty builds check every native payload. Each original archive can be reassembled byte-for-byte from its GNU headers and a single content-addressed copy of each member.

A separate typed client links the actual linter, parser AST and literal libraries produced by each ordinary command. It checks a real F401 diagnostic, a used import and a syntax error, then prints the known Unicode renderer result for each of five cases. Exactly two renderings change between OLD and NEW. A second reader rebuilds all physical rlibs from the saved bytes, reruns all 50 client verdicts, and checks Cargo's complete registry placement against this command's signed reference.

The scheduling threshold is **10% of the parent's regenerated linter CGU payload bytes** recovered through additional candidate donors, after subtracting any lost donors. A new measurement is warranted only if the native and correctness checks also pass. The numerator, denominator, counts and individual filenames are retained even when this threshold is missed. Native byte volume is a screen for potential work. This study collects no instruction or wall-time measurements.

## Result

The candidate recovered **535,096 of 18,642,280 regenerated linter bytes (2.8703%)**. This edit falls below the registered threshold. The parent retained 240 of 256 linter objects. Of the sixteen it regenerated, fourteen had actually changed and two were byte-identical. The candidate retained both identical objects, 147,216 and 387,880 bytes, and regenerated all fourteen changed objects. Both compilers retained fourteen of the literal provider's twenty-two OLD objects. Six of its surviving native payloads changed, one OLD CGU disappeared, and one NEW CGU appeared. [Original run](https://github.com/astral-experiments/ohm/actions/runs/41440080008) · [Native proof archive](https://github.com/astral-experiments/ohm/actions/runs/41440080008/artifacts/13140400786)

The reader reassembled twenty original rlibs byte-for-byte from 653 distinct saved native and archive blobs, repeated all fifty typed executions and passed twelve complete same-source CGU comparisons. Each visit observed the same 271 Cargo units and the same 195 registry dependency archives, with 162 shared and 33 private. The paired OLD→NEW builds each rebuilt the literal provider, Python code generator, importer and linter. A separate bounded read checked the original logs and native ledgers against the reported decision. [Compact result](ordinary-result/summary.json)

The following command verifies the original OLD and NEW inode rosters against independent empty builds and recalculates the admission result offline.

```sh
python3 -IB scripts/ruff-literal-map-source/ordinary-result/verify.py
```
