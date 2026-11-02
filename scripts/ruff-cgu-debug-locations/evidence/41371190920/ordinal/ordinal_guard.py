"""Preserve comparisons between physical line numbers anywhere in an LLVM module."""
def certify(previous, current):
    if previous.keys() != current.keys():
        return False, 'file sets differ'
    relation = {0: 0, 1: 1}
    for path, before in previous.items():
        after = current[path]
        if len(before) != len(after):
            return False, 'ordinal counts differ'
        for a, b in zip(before, after):
            if a in relation and relation[a] != b:
                return False, 'one physical line splits across files'
            relation[a] = b
    values = [v for _, v in sorted(relation.items())]
    if any(x >= y for x, y in zip(values, values[1:])):
        return False, 'physical line ranks cross across files'
    return True, 'all physical line-order comparisons preserved'
