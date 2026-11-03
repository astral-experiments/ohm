"""Read one typed Cargo dep-info record, retaining every ordinary input during a laboratory ablation."""
from pathlib import Path
import hashlib
import os
import struct
import subprocess

SENTINEL = b'ohm-foreign-span-bytes'


def digest(raw):
    text = subprocess.check_output(['b3sum'], input=raw).split()[0]
    return bytes.fromhex(text.decode())


def without_observation(raw, hash_bytes=digest):
    assert raw[:5] == b'\x01\x00\x00\x00\xff' and raw[5] in (2,4)
    at = 6

    def take(n):
        nonlocal at
        assert n <= len(raw)-at
        part = raw[at:at+n]
        at += n
        return part

    def u32():
        return struct.unpack('<I', take(4))[0]

    def string():
        return take(u32())

    n = u32()
    assert 0 < n < 8192
    entries = []
    for _ in range(n):
        a = at
        category = take(1)
        assert category in (b'\0',b'\1')
        path = string()
        has = take(1)
        assert has in (b'\0',b'\1')
        if has == b'\1':
            take(8)
            string()
        entries.append((raw[a:at],path,has))
    a = at
    nenv = u32()
    assert nenv < 1024
    for _ in range(nenv):
        string()
        mark = take(1)
        assert mark in (b'\0',b'\1')
        if mark == b'\1':string()
    env = raw[a:at]
    # A link marker or another trailer would be an independent mechanism.
    assert take(4) == b'OBS1'
    i = u32()
    assert take(1) == b'\0' and hash_bytes(raw[:at]) == take(32) and at == len(raw)
    assert len([p for _,p,_ in entries if p.rsplit(b'/',1)[-1] == SENTINEL]) == 1
    _,marker,has = entries[i]
    assert marker.rsplit(b'/',1)[-1] == SENTINEL and has == b'\0' and marker.endswith(b'.d/'+SENTINEL)
    remaining = [record for j,(record,_,_) in enumerate(entries) if i!=j]
    out = raw[:6]+struct.pack('<I',n-1)+b''.join(remaining)+env
    assert b'OBS1' not in out and SENTINEL not in out
    return out, {'index':i,'files':n,'env':nenv,'original':hashlib.sha256(raw).hexdigest(),
                 'changed':hashlib.sha256(out).hexdigest(),'marker':os.fsdecode(marker),
                 'remaining_inputs_sha256':hashlib.sha256(b''.join(remaining)+env).hexdigest()}


def replace(p, data, previous):
    s = p.stat()
    assert p.is_file() and not p.is_symlink() and p.read_bytes() == previous
    p.write_bytes(data)
    os.utime(p, ns=(s.st_atime_ns,s.st_mtime_ns))
    assert p.read_bytes() == data and p.stat().st_ino == s.st_ino and p.stat().st_mtime_ns == s.st_mtime_ns
