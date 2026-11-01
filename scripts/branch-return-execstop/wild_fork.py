"""Identify how every worker left one forked, unmodified Wild native link."""

STOCK = '0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5'


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def finish(raw, closed, projected):
    """Inspect a schema-3 ledger whose complete process lifetimes have already been validated."""
    import hashlib
    need(closed['schema'] == 3 and closed['sha256'] == hashlib.sha256(raw).hexdigest(),
         'different closed kernel evidence')
    images = {e['ordinal']: e for e in closed['execs']}
    effective, births, forks, exits, waits, parked = {}, {}, {}, {}, {}, {}
    leaders = set()
    for step, line in enumerate(raw.splitlines()):
        f = line.split(b'\t', 6)
        tag = f[0]
        if tag == b'R':
            effective[int(f[1])] = None
        elif tag == b'E':
            effective[int(f[2])] = int(f[1])
        elif tag == b'N':
            parent, kind, child, pid = map(int, (f[1], f[3], f[4], f[5]))
            effective[child] = effective[parent]
            forks[child] = (parent, kind, pid, effective[parent])
        elif tag == b'B':
            births[int(f[1])] = (int(f[2]), int(f[3]))
        elif tag == b'G':
            leaders.add(int(f[1]))
        elif tag == b'Q':
            parked.setdefault(int(f[3]), []).append(int(f[1]))
        elif tag in (b'X', b'T'):
            (exits if tag == b'X' else waits)[int(f[1])] = (int(f[2]), int(f[3]), step)

    evidence = []
    for link in projected:
        life, event, pid = link['lifetime'], link['event'], link['pid']
        e = images[event]
        need((e['lifetime'], e['pid'], e['image']['sha256']) == (life, pid, STOCK) and
             e['argv'] == link['argv'] and '-o' in e['argv'] and
             e['argv'][e['argv'].index('-o')+1] == link['output'], 'different actual Wild image or output')
        children = [c for c,(p,_,_,img) in forks.items() if p == life and img == event]
        need(len(children) == 1, 'Wild did not fork one helper at the enrolled image')
        helper, = children
        _, kind, hpid, _ = forks[helper]
        need(kind == 1 and births[helper] == (hpid, hpid) and effective[helper] == event,
             'helper changed image or process group')
        workers = {w for w,(_,tgid) in births.items() if tgid == hpid and w != helper}
        need(workers and all(forks[w][0] in {helper, *workers} and forks[w][1] == 3 and
                             forks[w][2:] == (births[w][0], event) and effective[w] == event for w in workers),
             'unexpected worker creation, group or image')
        need({c for c,(p,_,_,_) in forks.items() if p in {helper, *workers}} == workers,
             'unaccounted helper descendant')
        for member, member_pid in [(life, pid), (helper, hpid), *((w, births[w][0]) for w in workers)]:
            need(exits[member][:2] == waits[member][:2] == (member_pid, 0) and
                 exits[member][2] < waits[member][2], 'missing a successful exit and matching wait')
        stopped = sorted(parked.get(helper, []))
        if helper in leaders:
            need(stopped and set(stopped) <= workers, 'incomplete forked group park')
            path = 'parked'
        else:
            need(not stopped and all(waits[w][2] < exits[helper][2] for w in workers),
                 'worker outlived the individually closing helper')
            path = 'reaped-before-helper-exit'
        evidence.append(dict(wild_event=event, wild_lifetime=life, rustc_event=link['rustc_event'],
                             rustc_crate=link['rustc_crate'], output=link['output'], helper=helper,
                             helper_pid=hpid, workers=sorted(workers), parked=stopped, closure=path))
    return evidence


def stock_fixture(summary):
    """Keep the positive real-Wild group park mandatory on the same physical runner."""
    record = summary['native']['wild']
    counts = record['counts']
    need(summary['qualified'] and summary['schema'] == 3 and summary['stock_wild_sha256'] == STOCK and
         record['images'] == 1 and counts['N'] == 3 and counts['G'] == 1 and counts['Q'] == 2 and
         counts['X'] == counts['T'] == 4, 'native stock-Wild fixture lacks a parked fork group')
    return dict(raw_sha256=record['raw_sha256'], parked_workers=counts['Q'], final_waits=counts['T'])
