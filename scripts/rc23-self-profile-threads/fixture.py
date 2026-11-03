"""Generate a deterministic crate with externally observable native code in every module."""
from pathlib import Path

MASK = (1 << 64) - 1
SEEDS = [11, 0xFEDCBA9876543210]


def values():
    parts = []
    calls = []
    expected = SEEDS.copy()
    for module in range(48):
        parts.append(f"pub mod m{module} {{")
        for index in range(5):
            serial = 1 + module * 5 + index
            rotation = (serial * 11) % 63 + 1
            constant = serial * 17389 + 97
            factor = 2 * serial + 3
            parts.append(f"""#[inline(never)]
pub fn f{index}(mut x: u64) -> u64 {{
    for j in 0..29u64 {{
        x = std::hint::black_box(x).wrapping_add(j ^ {constant}).rotate_left({rotation}).wrapping_mul({factor});
        if x & 7 == {serial % 8} {{ x ^= {constant + 1}; }}
    }}
    x
}}""")
            calls.append(f"x = m{module}::f{index}(x);")
            for i, x in enumerate(expected):
                for j in range(29):
                    x = (x + (j ^ constant)) & MASK
                    x = (((x << rotation) | (x >> (64 - rotation))) * factor) & MASK
                    if x & 7 == serial % 8:
                        x ^= constant + 1
                expected[i] = x
        parts.append("}")
    parts += ["pub fn exercise(mut x:u64)->u64 {", *calls, "x }"]
    client = f'fn main() {{ for x in [{SEEDS[0]}u64,{SEEDS[1]}u64] {{ println!("{{}}",counter_fixture::exercise(x)); }} }}\n'
    return "\n".join(parts) + "\n", client, "".join(f"{n}\n" for n in expected)
