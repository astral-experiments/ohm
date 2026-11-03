# Ruff #28106 native instruction counts

The same six codegen units that the guarded compiler had previously rebuilt used 17.868 billion native-emission instructions on each observed Rust compiler. Save the two host observations separately. All 21 measured native output intervals agreed within 0.286% of the smaller count. The preregistered threshold was strictly below 2% on each individual unit. [Original two-worker run](https://github.com/astral-experiments/ohm/actions/runs/41565223128) · [Registration](https://github.com/astral-experiments/ohm/blob/a7be222ecd26ecf69e9a9481c0a24f6c1d4c5a89/scripts/ruff-real-cgu-weights/PLAN.md)

| Previously missed unit | Host 1 | Host 2 |
| --- | ---: | ---: |
| 6p30kgvj4lu40zowlel28tnn7 | 5,325,069,646 | 5,326,436,677 |
| 0wrsgo9esbuwdyfhrjd10085r | 4,958,742,236 | 4,958,425,483 |
| 9z2i9ar8n4enu9f18sb2ij12n | 4,087,914,931 | 4,088,630,119 |
| eunp1v4hqzfte5vryd9wi7an7 | 2,121,262,214 | 2,120,779,639 |
| 76u321zsuml5v37ktustj0dr0 | 1,338,212,786 | 1,337,400,115 |
| 16os12t5hva2grho4jumxjwa5 | 36,541,870 | 36,437,665 |

Each interval starts when LLVM successfully opens its native ELF object and ends at entry to the matching successful close. Instruction counts come from pinned per-thread hardware events in user mode. Each object's physical bytes, file descriptor and inode belonged to the identified compiler worker. Its complete count through thread exit bounds its native interval. Across all 138 threads, the two ordinary rustc processes used 111,603,233,459 and 111,608,044,783 instructions. The six native intervals account for 16.0101% and 16.0097% respectively. The six complete worker lifetimes account for 27.08% on each host.

Within each boot, the three complete 27,311,384-byte archives pass literal byte comparison after replacing 250 typed temporary filename fields. Both the ordinary repeat and the observed compiler produced all 125 enrolled complete object bodies and the same independent native consumer executable and verdict. The independent cross-boot historical test refused. All 125 native objects, the index and its 6,297 symbol associations agree. Across boots the main lib.rmeta member differs. Replacing that whole member reconstructs the remaining normalized archive exactly. The two current boots differ in 43,147 bytes in that member. Their private, public and global crate hashes differ, and both differ from the original discovery run. Across the three roots the original 609-argument compiler commands differ in 260 operands by exactly one Cargo namespace component per host. The packet omits independent complete bodies of the 35 inputs passed through the differently named extern paths. These prices describe the recorded builds individually. [Original archive-difference discovery](https://github.com/astral-experiments/ohm/actions/runs/41563286895)

The two original GitHub ZIPs have SHA-256 bff2b4504bacc0a0001fe434e1903c130ae840eaf6c40c5ef86dd158f2482eb4 and 06f5830302ff2e9637edbf7d672b38cd5cb99d99e689b61d80d501439a3d5c9e. The permanent JSON records preserve the exact measured source and tool identities, both kernel boots, all original per-object counter endpoints, their enabled/running denominators, complete object hashes, checkpoints from the independent opens, and both cross-boot outcomes. The retained Actions artifacts contain the full original archives and syscall journals.

From the packaging repository root, verify the compact packet with:

    python3 -IB scripts/ruff-real-cgu-weights/evidence/h4/verify.py

To verify the two original archives through the measured source and physical kernel file records while Actions retains them:

    mkdir -p /tmp/ohm-native-41565223128
    gh-auto api repos/astral-experiments/ohm/actions/artifacts/13198719850/zip > /tmp/ohm-native-41565223128/original-1.zip
    gh-auto api repos/astral-experiments/ohm/actions/artifacts/13199892687/zip > /tmp/ohm-native-41565223128/original-2.zip
    python3 -IB scripts/ruff-real-cgu-weights/evidence/h4/verify.py --originals /tmp/ohm-native-41565223128
