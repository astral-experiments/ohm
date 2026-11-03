"""Count a conservative subset of instructions in a selected compiler process."""
import ctypes
import errno
import os
from pathlib import Path
import struct
import subprocess
import time

def load_library(path):
    library = ctypes.CDLL(str(path), use_errno=True)
    library.open_task_counter.argtypes = (ctypes.c_int,)
    library.open_task_counter.restype = ctypes.c_int
    return library

def attach(library, tid):
    fd = library.open_task_counter(tid)
    if fd < 0:
        code = ctypes.get_errno()
        if code in (errno.ESRCH, errno.ENOENT):
            raise ProcessLookupError(code, os.strerror(code))
        raise OSError(code, os.strerror(code))
    return fd

def count(fd):
    instructions, enabled, running = struct.unpack('=QQQ', os.read(fd, 24))
    assert enabled == running and (not instructions or running > 0), (instructions, enabled, running)
    return dict(instructions=instructions, enabled=enabled, running=running)

def task_id(task):
    # starttime is field 22. The task name in parentheses may contain whitespace.
    stat = (task / 'stat').read_bytes().rsplit(b')', 1)[1].split()
    return int(stat[19])

def matching_driver(process, driver):
    device = f'{os.major(driver.st_dev):x}', f'{os.minor(driver.st_dev):x}'
    for row in (process / 'maps').read_text().splitlines():
        _, permissions, _, dev, ino, *_ = row.split(maxsplit=5)
        if 'x' in permissions and int(ino) == driver.st_ino:
            if tuple(format(int(v, 16), 'x') for v in dev.split(':')) == device:
                return True
    return False

def children(task):
    pids = set()
    for thread in (task / 'task').iterdir():
        try:
            pids.update(map(int, (thread / 'children').read_text().split()))
        except (FileNotFoundError, ProcessLookupError):
            pass
    return pids

def observe(command, *, library, sdk, dst, cwd, env, stdout, stderr):
    cargo = sdk / 'bin/cargo'
    rustc = sdk / 'bin/rustc'
    driver, = (sdk / 'lib').glob('librustc_driver-*.so')
    driver = driver.stat()
    fds = {}
    programs = {}
    procfs = Path('/proc')
    with subprocess.Popen(command, cwd=cwd, env=env, stdout=stdout, stderr=stderr) as proc:
        try:
            while proc.poll() is None:
                candidates = set(programs)
                try:
                    for cargo_pid in children(procfs / str(proc.pid)):
                        cargo_task = procfs / str(cargo_pid)
                        if cargo.samefile(cargo_task / 'exe'):
                            candidates.update(children(cargo_task))
                except (FileNotFoundError, ProcessLookupError):
                    pass
                for pid in candidates:
                    task = procfs / str(pid)
                    try:
                        if pid not in programs:
                            if not rustc.samefile(task / 'exe'):
                                continue
                            fields = (task / 'stat').read_bytes().rsplit(b')', 1)[1].split()
                            if not cargo.samefile(procfs / fields[1].decode() / 'exe'):
                                continue
                            argv = list(map(os.fsdecode, (task / 'cmdline').read_bytes().rstrip(b'\0').split(b'\0')))
                            if '--crate-name' not in argv or argv[argv.index('--crate-name')+1] != 'ty_python_semantic':
                                continue
                            if not any(arg == '--emit' or arg.startswith('--emit=') for arg in argv) or not matching_driver(task, driver):
                                continue
                            programs[pid] = {'argv': argv, 'start': task_id(task), 'cargo_pid': int(fields[1])}
                        if task_id(task) != programs[pid]['start'] or not rustc.samefile(task / 'exe'):
                            continue
                        for thread in (task / 'task').iterdir():
                            tid = int(thread.name)
                            if (pid, tid) in fds:
                                continue
                            try:
                                start = task_id(thread)
                                fd = attach(library, tid)
                                try:
                                    if task_id(thread) == start and rustc.samefile(thread / 'exe'):
                                        fds[pid, tid] = fd
                                        fd = None
                                finally:
                                    if fd is not None:
                                        os.close(fd)
                            except (FileNotFoundError, ProcessLookupError):
                                pass
                    except (FileNotFoundError, ProcessLookupError):
                        pass
                time.sleep(.002)
            assert proc.returncode == 0, (dst, proc.returncode)
            assert len(programs) == 1 and fds, (dst, programs, len(fds))
            rows = [{'pid': pid, 'tid': tid, **count(fd)} for (pid, tid), fd in fds.items()]
            assert len({row['tid'] for row in rows}) == len(rows)
            return {'processes': programs, 'threads': rows, 'instructions': sum(r['instructions'] for r in rows)}
        finally:
            for fd in fds.values():
                os.close(fd)
