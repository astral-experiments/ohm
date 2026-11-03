"""Test a genuine native loader, file leases and the private runner mount before obtaining Ruff."""
from pathlib import Path
import fcntl
import hashlib
import json
import os
import shlex
import shutil
import signal
import subprocess as sp
import sys

HERE = Path(__file__).resolve().parent
uid = os.getuid()
gid = os.getgid()


def sha(file):
    with file.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def record(file, data):
    file.write_text(json.dumps(data, sort_keys=True, indent=2) + '\n')


def physical(root, entries, label, strict):
    proof = root / 'published'
    paths = [Path(item) for item in entries]
    fds = []
    signal.signal(signal.SIGIO, lambda *_: None)
    try:
        for path in paths:
            fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
            fds.append(fd)
            if strict:
                info = os.fstat(fd)
                assert info.st_uid == uid and info.st_nlink == 1
                fcntl.fcntl(fd, fcntl.F_SETOWN, os.getpid())
                fcntl.fcntl(fd, fcntl.F_SETLEASE, fcntl.F_RDLCK)
        full = [paths[0], 'strict' if strict else 'observe', *paths, *map(str, fds), 'three-private-physical-images']
        output = sp.run(full, pass_fds=fds, capture_output=True)
        rows = [l.split('\t') for l in output.stdout.decode().splitlines()]
        record(proof / (label + '.json'), dict(exit=output.returncode, rows=rows, stderr=output.stderr.decode(),
               sha256=[sha(p) for p in paths], stat=[list(os.fstat(fd)) for fd in fds], argv=list(map(str, full))))
        assert output.returncode == 0 and len(rows) == 3, (label, output.returncode, rows)
        if strict:
            assert all(r[-1] == '1' for r in rows)
            assert all(fcntl.fcntl(fd, fcntl.F_GETLEASE) == fcntl.F_RDLCK for fd in fds)
    finally:
        for fd in fds:
            os.close(fd)


def child(ctx):
    return '/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/bin /usr/bin/python3 -IB ' + shlex.quote(str(HERE / 'topology.py')) + ' ' + ctx


def start(root, local):
    assert uid != 0
    root.mkdir()
    (root / 'published').mkdir()
    helper = root / 'helper.so'
    source = root / 'helper.c'
    source.write_text('int sample_value(void) { return 17; }\n')
    probe = root / 'probe'
    sp.run(['cc', '-Wall', '-Wextra', '-Werror', '-O2', HERE/'topology.c', '-ldl', '-o', probe], check=True)
    sp.run(['cc', '-O2', '-shared', '-fPIC', source, '-o', helper], check=True)
    libc = Path('/usr/lib/x86_64-linux-gnu/libc.so.6').resolve(strict=True)
    assert libc.stat().st_uid != uid and not libc.stat().st_mode & 0o022
    if not local:
        assert libc.stat().st_uid == 0
    paths = list(map(str, [probe, helper, libc]))
    physical(root, paths, 'ordinary', False)
    if local: return
    link = root / 'private-tmpfs'
    link.mkdir()
    q = shlex.quote
    bb = '/bin/busybox'
    assert 'statically linked' in sp.check_output(['file', '-L', bb], text=True) or 'static-pie linked' in sp.check_output(['file', '-L', bb], text=True)
    context = root/'case.json'
    packet = dict(root=str(root), private=str(link), paths=paths, sha256=[sha(Path(p)) for p in paths],
                  uid=uid, gid=gid, namespace=os.readlink('/proc/self/ns/mnt'))
    record(context, packet)
    record(root/'published/host.json', dict(**packet, mountinfo=Path('/proc/self/mountinfo').read_text(),
        status=Path('/proc/self/status').read_text(), run=os.environ.get('GITHUB_RUN_ID'), head=os.environ.get('GITHUB_SHA')))
    ns = '/bin/busybox readlink /proc/self/ns/mnt'
    script = 'set -eu\n'
    script += f'test "$({ns})" != {q(packet["namespace"])}\n'
    script += f'/bin/busybox mount -t tmpfs -o mode=0700,uid={uid},gid={gid},size=64m,nosuid,nodev tmpfs {q(str(link))}\n'
    drop = f'/usr/bin/setpriv --reuid={uid} --regid={gid} --clear-groups --no-new-privs /bin/busybox sh -c '
    script += drop + q('exec ' + child('--stage ' + q(str(context)))) + '\n'
    script += drop + q('kill -STOP $$; exec ' + child('--verify ' + q(str(context)))) + ' &\nchild=$!\n'
    script += 'trap \'kill -CONT "$child" 2>/dev/null || :; kill -TERM "$child" 2>/dev/null || :; wait "$child" 2>/dev/null || :\' EXIT\n'
    check = f'/^State:/ {{a=($2=="T")}} /^Uid:/ {{b=($2=={uid}&&$3=={uid}&&$4=={uid}&&$5=={uid})}} /^CapEff:/ {{c=($2=="0000000000000000")}} /^NoNewPrivs:/ {{d=($2==1)}} END {{exit !(a&&b&&c&&d)}}'
    script += f'i=0; while ! /bin/busybox awk {q(check)} "/proc/$child/status"; do i=$((i+1)); [ "$i" -le 500 ]; /bin/busybox sleep 0.02; done\n'
    for idx,p in enumerate(paths):
        script += f'/bin/busybox mount -o bind {q(str(link/str(idx)))} {q(p)}\n/bin/busybox mount -o remount,bind,ro {q(p)}\n'
    script += 'kill -CONT "$child"; rc=0; wait "$child" || rc=$?; trap - EXIT; exit "$rc"\n'
    (root/'published/namespace-command.sh').write_text(script)
    proc = sp.run(['sudo','-n','unshare','--mount','--propagation','private','--',bb,'sh','-c',script],capture_output=True)
    (root/'published/namespace.stderr').write_bytes(proc.stderr)
    record(root/'published/terminal.json', dict(status=proc.returncode, stdout=proc.stdout.decode(), stderr=proc.stderr.decode()))
    assert proc.returncode == 0, proc.stderr.decode()
    assert not list(link.iterdir()) and os.readlink('/proc/self/ns/mnt') == packet['namespace']


def inner(file, stage):
    spec = json.loads(file.read_bytes())
    root = Path(spec['root']); path = Path(spec['private'])
    assert uid == spec['uid'] != 0 and os.readlink('/proc/self/ns/mnt') != spec['namespace']
    status = Path('/proc/self/status').read_text()
    assert 'NoNewPrivs:\t1' in status and 'CapEff:\t0000000000000000' in status
    mount = Path('/proc/self/mountinfo').read_text().splitlines()
    ours, = [row for row in mount if row.split()[4] == str(path)]
    assert ' - tmpfs ' in ours and all(x not in ours.split()[5].split(',') for x in ('noexec','ro'))
    if stage:
        for i, (name,h) in enumerate(zip(spec['paths'],spec['sha256'],strict=True)):
            dst = path/str(i);shutil.copy2(name,dst);assert dst.stat().st_nlink == 1 and sha(dst) == h
        return
    for i,name in enumerate(spec['paths']):
        assert os.path.samefile(name, path/str(i))
    physical(root,spec['paths'],'private',True)
    # The original user can write the *private tmpfs name*. Linux must stop a writer on this held shared-object generation.
    import errno
    fd=os.open(path/'1',os.O_RDONLY|os.O_CLOEXEC)
    signal.signal(signal.SIGIO, lambda *_: None)
    fcntl.fcntl(fd,fcntl.F_SETOWN,os.getpid());fcntl.fcntl(fd,fcntl.F_SETLEASE,fcntl.F_RDLCK)
    try:
        try: writer=os.open(path/'1',os.O_WRONLY|os.O_NONBLOCK)
        except OSError as err: assert err.errno in (errno.EAGAIN,errno.EWOULDBLOCK)
        else: os.close(writer);raise AssertionError('writer unexpectedly admitted')
    finally:os.close(fd)
    record(root/'published/private-namespace.json',dict(mountinfo=mount,status=status,visible_names=spec['paths'],writer_blocked=True))


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]in ('--verify','--stage'):
        inner(Path(sys.argv[2]),sys.argv[1]=='--stage')
    elif len(sys.argv)==3 and sys.argv[1]=='--local':
        start(Path(sys.argv[2]),True)
    else:
        assert len(sys.argv)==1 and os.environ['GITHUB_SHA']==os.environ['REVIEWED_HEAD']
        start(Path(os.environ['RUNNER_TEMP'])/'ohm-foreign-join',False)
