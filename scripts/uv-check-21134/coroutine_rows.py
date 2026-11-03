"""Re-emit the admitted rustc SyntheticCoroutineBody type and its shared full Ty.

Only a native Coroutine with a local Closure owner and a source-representable
argument is admitted. Nested cached types must precede all moved item data.
"""
from proof import check, local_key, read, var


# CodegenFnAttrs::new, in struct declaration order. Its two nonzero unit
# discriminants are RtsanSetting::Caller and InstrumentFnAttr::Default.
EMPTY_CODEGEN = bytes([0] * 13 + [2] + [0] * 5 + [2])


class CoroutineTypes:
    def __init__(self, data, start, owners):
        self.data = data
        self.start = start
        self.owners = owners
        self.full = {}
        self.new = {}
        self.short = set()

    def original(self, p):
        data = self.data
        tag, q = read(data, p)
        if tag >= 128:
            target = tag - 128
            check(0 < target < p and data[target] < 128, 'invalid complete Ty source')
            self.short.add(p)
            return target, q
        check(tag == 19, 'unsupported synthetic TyKind')
        (crate, owner), q = local_key(data, q)
        check(crate == 0 and self.owners.get(owner) == 'Closure', 'incorrect coroutine Ty owner')
        count, q = read(data, q)
        for _ in range(count):
            form, q = read(data, q)
            if form == 0:
                region, q = read(data, q)
                check(region in (3, 6), 'non-unit coroutine lifetime')
                continue
            check(form == 1, 'non-type coroutine argument')
            begin = q
            kind, q = read(data, q)
            if kind >= 128:
                target = kind - 128
                check(0 < target < self.start and data[target] < 128,
                      'coroutine argument type crosses reordered data')
            elif kind in (2, 3, 4):
                which, q = read(data, q)
                check(which < (6, 6, 4)[kind - 2], 'invalid primitive coroutine argument')
            elif kind == 22:
                length, q = read(data, q)
                check(length == 0, 'nested non-unit coroutine tuple')
            else:
                check(kind in (0, 1, 7, 21), 'unsupported inline coroutine argument')
            if kind < 128:
                check(q-begin < len(var(begin+128)), 'nested coroutine argument would publish a new Ty')
        check(q-p >= len(var(p+128)), 'uncached full coroutine Ty')
        self.full[p] = data[p:q]
        return p, q

    def encoded(self, target, pos):
        if target < self.start:
            return var(target + 128)
        if target in self.new:
            return var(self.new[target] + 128)
        check(target in self.full, 'unknown moved full coroutine Ty')
        raw = self.full[target]
        check(len(raw) >= len(var(pos + 128)), 'new coroutine Ty cacheability')
        self.new[target] = pos
        return raw

    def external(self, data, cells, old_end, op):
        check(set(self.new) == set(self.full), 'lost published synthetic Ty')
        redirected = {p: n for p,n in self.new.items() if p != n}
        for value in cells:
            p = int.from_bytes(value, 'little')
            if p < old_end or data[p] < 128:
                continue
            v,q = read(data,p)
            if v-128 in redirected:
                raw = var(redirected[v-128]+128)
                check(len(raw) == q-p, 'external Ty shorthand width changed')
                op.write(p,q,raw,'external Ty shorthand to synthetic coroutine')
                self.short.add(p)
        for target in redirected:
            needle = var(target+128)
            p = data.find(needle, target+1)
            while p >= 0:
                check(p in self.short, 'unowned shorthand to moved full coroutine Ty')
                p = data.find(needle, p+1)
