"""Mutation controls for the coordinate mapping, independent of the performance record."""

import hashlib
from llvm_inputs import FILE, debug_key, sha


def render(src, original=(17, 21, 81)):
    a, b, c = original
    md = hashlib.md5(src).hexdigest()
    # Shapes are authenticated in the full original modules, this fixture targets the debug-key helper.
    return f"""!0 = !DIFile(filename: "{FILE}", directory: "/current", checksumkind: CSK_MD5, checksum: "{md}")
!1 = distinct !DISubprogram(name: "producer", file: !0, line: {a}, scopeLine: {a})
!2 = !DILocation(line: {b}, column: 18, scope: !1)
!3 = !DILocation(line: {c}, column: 27, scope: !1, inlinedAt: !2)
!4 = !DILocation(line: 0, scope: !1)
!5 = !DILexicalBlockFile(scope: !1, file: !0, discriminator: 8)
!6 = !DILocalVariable(name: "survivor", file: !0, line: {c}, scope: !1)
"""


def ordinal_mutations():
    x = b"ordinary archived shape A"
    y = b"ordinary archived shape B"
    o = render(x)
    base, r = debug_key(o, x)
    new, r2 = debug_key(render(y, (119, 120, 506)), y)
    assert (
        base == new
        and r["with_real_checksum"] != r2["with_real_checksum"]
        and r["lossless_debug_roundtrip"]
        and r2["lossless_debug_roundtrip"]
    )
    tests = {}
    for n, before, after in [
        ("column", "column: 27", "column: 28"),
        ("inline chain", "inlinedAt: !2", "inlinedAt: !4"),
        ("lexical scope", "column: 18, scope: !1", "column: 18, scope: !5"),
        ("discriminator", "discriminator: 8", "discriminator: 9"),
        ("zero position", "line: 0", "line: 81"),
        ("merge line identity", "line: 21", "line: 17"),
        ("reorder two lines", "line: 21", "line: 93"),
        ("local name", '"survivor"', '"different"'),
        ("variable line", "line: 81, scope:", "line: 17, scope:"),
        ("file identity", 'directory: "/current"', 'directory: "/other"'),
    ]:
        assert before in o
        nw = debug_key(o.replace(before, after, 1), x)[0]
        assert base != nw, n
        tests[n] = sha(nw.encode())
    try:
        debug_key(o, y)
    except AssertionError:
        tests["wrong current source MD5"] = "rejected"
    else:
        raise AssertionError("stale source accepted")
    return dict(
        independently_shifted=sha(base.encode()),
        reversible_current_tables=True,
        mutated=tests,
    )
