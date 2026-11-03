"""Count a conservative subset of instructions in a selected compiler process."""
import ctypes
import errno
import hashlib
import json
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

def signed_windows(driver):
    # The SDK installer has hashed the whole driver. Compare its actual GNU build ID
    # and executable text in memory as well. Overlayfs may report a different device
    # in stat(2) from the underlying device in procfs, even for the same mapping.
    with driver.open('rb') as signed:
        header = signed.read(4096)
        assert header.startswith(b'\x7fELF\x02\x01')
        phoff, = struct.unpack_from('<Q', header, 32)
        entsize, count = struct.unpack_from('<HH', header, 54)
        assert entsize == 56 and count == 12
        signed.seek(phoff)
        phdrs = signed.read(count * entsize)
        assert len(phdrs) == count * entsize
        build_id = bytes.fromhex('13d77347e7b9583b23105b596b85d283cd70af08')
        note = struct.pack('<III', 4, len(build_id), 3) + b'GNU\0' + build_id
        assert header.count(note) == 1
        windows = [(0, False, header)]
        for i in range(count):
            kind, flags, offset, _, _, size, _, _ = struct.unpack_from('<IIQQQQQQ', phdrs, i * entsize)
            if kind == 1 and flags & 1:
                assert size >= 8192
                signed.seek(offset + 4096)
                windows.append((offset + 4096, True, signed.read(128)))
        assert len(windows) == 3
        return windows

def matching_driver(process, driver, driver_stat, windows, image):
    regions = []
    for line in (process / 'maps').read_text().splitlines():
        parts = line.split(maxsplit=5)
        if len(parts) != 6 or int(parts[4]) != driver_stat.st_ino or parts[5] != str(driver):
            continue
        lo, hi = (int(v, 16) for v in parts[0].split('-'))
        regions.append((lo, hi, int(parts[2], 16), parts[1], parts[3]))
    if not regions:
        return False
    if not (process / 'root' / driver.relative_to('/')).samefile(driver):
        return False
    receipts = []
    with (process / 'mem').open('rb', buffering=0) as memory:
        for offset, executable, expected in windows:
            for lo, hi, file_offset, permissions, device in regions:
                address = lo + offset - file_offset
                if lo <= address and address + len(expected) <= hi and ('x' in permissions) == executable:
                    actual = os.pread(memory.fileno(), len(expected), address)
                    if actual != expected:
                        return False
                    receipts.append({'address': address, 'file_offset': offset, 'map_device': device,
                                     'bytes': actual.hex(), 'sha256': hashlib.sha256(actual).hexdigest()})
                    break
            else:
                return False
    image['signed_memory_windows'] = receipts
    return True

def observe(command, *, library, sdk, dst, cwd, env, stdout, stderr):
    cargo = sdk / 'bin/cargo'
    rustc = sdk / 'bin/rustc'
    driver, = (sdk / 'lib').glob('librustc_driver-*.so')
    driver_stat = driver.stat()
    windows = signed_windows(driver)
    fds = {}
    programs = {}
    images = {}
    attempts = 0
    procfs = Path('/proc')
    with subprocess.Popen(command, cwd=cwd, env=env, stdout=stdout, stderr=stderr, start_new_session=True) as proc:
        try:
            while proc.poll() is None:
                attempts += 1
                for pid_name in os.listdir(procfs):
                    if not pid_name.isdecimal():
                        continue
                    pid = int(pid_name)
                    task = procfs / pid_name
                    try:
                        if pid not in programs:
                            if os.getpgid(pid) != proc.pid:
                                continue
                            fields = (task / 'stat').read_bytes().rsplit(b')', 1)[1].split()
                            ppid = int(fields[1])
                            exe = (task / 'exe').readlink()
                            image = images.setdefault((pid, str(exe)), {'pid': pid, 'ppid': ppid, 'exe': str(exe)})
                            if not rustc.samefile(task / 'exe'):
                                continue
                            image['is_rustc'] = True
                            image['parent'] = str((procfs / str(ppid) / 'exe').readlink())
                            if not cargo.samefile(procfs / str(ppid) / 'exe'):
                                continue
                            argv = list(map(os.fsdecode, (task / 'cmdline').read_bytes().rstrip(b'\0').split(b'\0')))
                            if '--crate-name' not in argv or argv[argv.index('--crate-name')+1] != 'ty_python_semantic':
                                continue
                            image['cargo_child_ty'] = True
                            if 'driver_seen' not in image:
                                maps = [line for line in (task / 'maps').read_text().splitlines() if 'librustc_driver-' in line]
                                if maps:
                                    image['driver_seen'] = maps
                            if not any(arg == '--emit' or arg.startswith('--emit=') for arg in argv) or not matching_driver(task, driver, driver_stat, windows, image):
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
            (dst/'observed-images.json').write_text(json.dumps({'polls':attempts,'observer_pid':proc.pid,'images':list(images.values()),
                'driver':{'inode':driver_stat.st_ino,'major':os.major(driver_stat.st_dev),'minor':os.minor(driver_stat.st_dev)}},indent=2)+'\n')
            for fd in fds.values():
                os.close(fd)
