"""Recompute Ir from physical self-cost rows, the process header and the Valgrind log."""

import re


def recount(raw,log,pid,argv):
    pid_rx=rb'^=='+str(pid).encode()+rb'== ';assert raw.splitlines().count(b'pid: '+str(pid).encode())==1
    assert raw.splitlines().count(b'cmd:  '+b' '.join(x.encode() for x in argv))==1 or re.findall(rb'^cmd:\s*(.*?)\s*$',raw,re.M)==[b' '.join(x.encode() for x in argv)]
    assert re.findall(rb'^events: (.*)$',raw,re.M)==[b'Ir']
    total=0;edge=False
    for line in raw.splitlines():
        if line.startswith(b'calls='):
            assert not edge;edge=True
        elif re.match(rb'^[*+\-\d]',line):
            if not edge:total+=int(line.split()[-1])
            edge=False
    assert not edge and list(map(int,re.findall(rb'^totals: (\d+)$',raw,re.M)))==[total]
    numbers=re.findall(pid_rx+rb'Collected\s+:\s+([\d,]+)\s*$',log,re.M)
    assert numbers==[next(iter(numbers))] and int(numbers[0].replace(b',',b''))==total
    return total
