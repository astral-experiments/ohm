"""Certify cached region-outlives predicates and expose each inherited clause's real Span."""
from bisect import bisect_right
from proof import check, full_span, local_key, original_span, read, var


class InheritedClauses:
    def __init__(self, data, cells, start, keys):
        self.data = data
        self.start = start
        self.keys = keys
        self.cells = cells
        self.anchors = None
        self.owners = {}

    def _parent(self, start):
        tag = self.data[start]
        check(tag in (0, 1), "invalid GenericClauses parent tag")
        if tag == 0:
            return None, start + 1
        (crate, key), end = local_key(self.data, start + 1)
        check(crate == 0 and key in self.keys, "unresolved GenericClauses parent")
        return key, end

    def _symbol(self, pos):
        tag = self.data[pos]
        check(tag in (0, 1), "unsupported early lifetime symbol")
        if tag == 1:
            address, end = read(self.data, pos + 1)
            check(0 < address < pos, "invalid early lifetime symbol offset")
        else:
            address = pos + 1
        size, text = read(self.data, address)
        stop = text + size
        check(stop < self.start and self.data[stop] == 193, "early lifetime symbol bounds or terminator")
        spelling = self.data[text:stop].decode("utf-8")
        check(spelling.startswith("'") and len(spelling) > 1, "unnamed inherited early lifetime")
        return spelling, end if tag == 1 else stop + 1

    def _region(self, pos):
        kind, pos = read(self.data, pos)
        check(kind == 0, "unsupported region in inherited RegionOutlives")
        index, pos = read(self.data, pos)
        check(index < 1 << 32, "invalid early lifetime index")
        name, end = self._symbol(pos)
        return ("early", index, name), end

    def _full(self, pos):
        check(self.data[pos:pos + 2] == b"\x00\x01", "unsupported inherited PredicateKind or ClauseKind")
        lhs, end = self._region(pos + 2)
        rhs, end = self._region(end)
        check(end <= self.start and end - pos >= len(var(pos + 128)), "uncacheable full inherited predicate")
        return (lhs, rhs), end

    def _origin(self, target):
        # Recognize full predicate boundaries by walking an actual GenericClauses table
        # value. A coincidentally parseable byte sequence in another payload is insufficient.
        if self.anchors is None:
            self.anchors = sorted({n for cell in self.cells if 0 < (n := int.from_bytes(cell, "little")) < self.start})
        at = bisect_right(self.anchors, target) - 1
        check(at >= 0, "inherited predicate outside earlier GenericClauses")
        anchor = self.anchors[at]
        if anchor not in self.owners:
            _, pos = self._parent(anchor)
            count, pos = read(self.data, pos)
            limit = self.anchors[at + 1] if at + 1 < len(self.anchors) else self.start
            check(count <= (limit - pos) // 3, "invalid earlier GenericClauses length")
            defined = {}
            for _ in range(count):
                binders, pos = read(self.data, pos)
                check(binders == 0, "unsupported inherited predicate binders")
                if self.data[pos] & 128:
                    key, pos = read(self.data, pos)
                    check(key - 128 in defined, "earlier GenericClauses refers outside its proven predicate set")
                else:
                    source = pos
                    term, pos = self._full(pos)
                    defined[source] = term
                span, pos = original_span(self.data, pos)
                full_span(self.data, span)
                check(pos <= limit, "earlier GenericClauses crossed another table row")
            self.owners[anchor] = defined
        check(target in self.owners[anchor], "cached inherited predicate is not an inline GenericClauses member")
        return self.owners[anchor][target]

    def parts(self, start, expected_parent, limit):
        parent, pos = self._parent(start)
        check(parent == expected_parent, "incorrect inherited clauses parent")
        count, pos = read(self.data, pos)
        check(count <= (limit - pos) // 3, "invalid inherited clause count")
        parts = [("explicit_clauses_of", start, pos, None)]
        for _ in range(count):
            begin = pos
            binders, pos = read(self.data, pos)
            check(binders == 0 and self.data[pos] & 128, "unsupported inline or bound inherited predicate")
            value, end = read(self.data, pos)
            target = value - 128
            check(0 < target < self.start, "inherited shorthand outside invariant prefix")
            self._origin(target)
            # The predicate shorthand is absolute and still addresses the same certified
            # immutable bytes. Its paired Span participates in the existing span writer.
            parts.append(("inherited_predicate", begin, end, None))
            span, pos = original_span(self.data, end)
            full_span(self.data, span)
            check(pos <= limit, "inherited predicate span beyond the next native field")
            parts.append(("inherited_span", end, pos, span))
        check(pos == limit, "inherited GenericClauses did not consume its full field")
        return parts, pos
