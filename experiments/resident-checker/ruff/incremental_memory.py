"""Keep rustc's finalized, serialized incremental inputs hot in a separate process.

This maps the ordinary files read-only at the descriptor level. It does not replace
rustc's disk format, deserialize its state, or retain compiler query objects. Call
``refresh`` between compiler invocations; rustc may unlink an old finalized
generation, but it must never truncate a published file while it is being mapped.
"""

import ctypes
import errno
import mmap
import os
import re
import stat
import time
from dataclasses import dataclass
from pathlib import Path

FILES = ("dep-graph.bin", "query-cache.bin", "work-products.bin")
GENERATION = re.compile(r"s-([0-9a-z]+)-[0-9a-z]+-[0-9a-z]+\Z")
DEFAULT_LIMIT = 256 * 1024 * 1024


def _library():
    library = ctypes.CDLL(None, use_errno=True)
    for name in ("mlock", "munlock"):
        function = getattr(library, name, None)
        if function is not None:
            function.argtypes = (ctypes.c_void_p, ctypes.c_size_t)
            function.restype = ctypes.c_int
    return library


LIBRARY = _library()


def _memory_call(name, data):
    function = getattr(LIBRARY, name, None)
    if function is None:
        raise OSError(errno.ENOSYS, f"{name} is not available")
    # Python needs a writable buffer to expose its address. This mmap is private,
    # its source descriptor is read-only, and this module never writes to it, so
    # its untouched pages continue to refer to the same file-backed physical pages.
    address = ctypes.addressof(ctypes.c_char.from_buffer(data))
    if function(address, len(data)):
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def _identity(status):
    return (
        status.st_dev,
        status.st_ino,
        status.st_size,
        status.st_mtime_ns,
        status.st_ctime_ns,
    )


def _identity_report(identity):
    return dict(zip(("device", "inode", "bytes", "mtime_ns", "ctime_ns"), identity))


def _page_bytes(size):
    return ((size + mmap.PAGESIZE - 1) // mmap.PAGESIZE) * mmap.PAGESIZE


def _prefault(data):
    for offset in range(0, len(data), mmap.PAGESIZE):
        data[offset]


class MemoryLockError(OSError):
    """The caller required guaranteed retention and the kernel rejected mlock."""


@dataclass
class Mapping:
    data: mmap.mmap
    locked: bool
    lock_error: str | None

    def close(self):
        try:
            if self.locked:
                _memory_call("munlock", self.data)
        except OSError:
            # Unmapping releases the lock itself if the explicit call failed.
            pass
        finally:
            self.data.close()


class IncrementalMemory:
    """Prefault and attempt to pin bounded, immutable rustc incremental files.

    Only the newest finalized generation of each crate is selected, matching
    rustc's timestamp ordering. Whole, page-rounded files must fit in
    ``limit_bytes``. Without
    ``require_lock``, an unsuccessful lock is recorded and the prefaulted mmap
    remains live, but the kernel is allowed to evict its pages. With it, a lock
    failure raises ``MemoryLockError`` and releases the retained mappings.
    """

    def __init__(self, root: Path, limit_bytes=DEFAULT_LIMIT, *, require_lock=False):
        if limit_bytes < 0:
            raise ValueError("limit_bytes must not be negative")
        self.root = Path(root).resolve()
        self.limit_bytes = limit_bytes
        self.require_lock = require_lock
        self._mappings = {}
        self._closed = False

    def __enter__(self):
        if self._closed:
            raise RuntimeError("incremental memory is already closed")
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        if not self._closed:
            self._release_all()
            self._closed = True

    def _release_all(self):
        for identity in list(self._mappings):
            self._mappings.pop(identity).close()

    def _error(self, report, path, error):
        report["errors"].append(
            {"path": str(path.relative_to(self.root)), "error": str(error)}
        )

    def _generations(self, report):
        try:
            crates = sorted(self.root.iterdir())
        except FileNotFoundError:
            return
        except OSError as error:
            self._error(report, self.root, error)
            return
        for crate in crates:
            if crate.is_symlink() or not crate.is_dir():
                continue
            try:
                candidates = []
                for generation in crate.iterdir():
                    name = GENERATION.fullmatch(generation.name)
                    if (
                        name
                        and not generation.name.endswith("-working")
                        and not generation.is_symlink()
                        and generation.is_dir()
                    ):
                        candidates.append((int(name[1], 36), generation))
                if candidates:
                    yield max(candidates)[1]
            except OSError as error:
                self._error(report, crate, error)

    def _selection(self, report):
        selected = {}
        available = self.limit_bytes
        for generation in self._generations(report):
            report["generations"].append(str(generation.relative_to(self.root)))
            for name in FILES:
                path = generation / name
                relative = str(path.relative_to(self.root))
                try:
                    status = path.lstat()
                    if not stat.S_ISREG(status.st_mode):
                        report["skipped"].append(
                            {"path": relative, "bytes": 0, "reason": "not-regular"}
                        )
                        continue
                    identity = _identity(status)
                    size = status.st_size
                    page_bytes = _page_bytes(size)
                    if size == 0:
                        report["skipped"].append(
                            {"path": relative, "bytes": 0, "reason": "empty"}
                        )
                    elif identity in selected:
                        selected[identity].append(path)
                    elif page_bytes > available:
                        report["skipped"].append(
                            {"path": relative, "bytes": size, "reason": "byte-limit"}
                        )
                    else:
                        available -= page_bytes
                        selected[identity] = [path]
                except FileNotFoundError:
                    continue
                except OSError as error:
                    self._error(report, path, error)
        return selected

    def _map(self, path, identity):
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            current = os.fstat(descriptor)
            if not stat.S_ISREG(current.st_mode) or _identity(current) != identity:
                raise OSError(errno.ESTALE, "incremental file changed during refresh")
            data = mmap.mmap(descriptor, current.st_size, access=mmap.ACCESS_COPY)
        finally:
            os.close(descriptor)
        try:
            _prefault(data)
            try:
                _memory_call("mlock", data)
            except OSError as error:
                if self.require_lock:
                    raise MemoryLockError(
                        error.errno, error.strerror, str(path)
                    ) from error
                return Mapping(data, False, str(error))
            return Mapping(data, True, None)
        except BaseException:
            data.close()
            raise

    def refresh(self):
        """Synchronize mappings and report what is actually resident or prefaulted."""
        if self._closed:
            raise RuntimeError("incremental memory is already closed")
        started = time.perf_counter_ns()
        report = {
            "selection": "newest-finalized-generation-per-crate",
            "policy": "require-mlock" if self.require_lock else "attempt-mlock",
            "limit_bytes": self.limit_bytes,
            "page_bytes": mmap.PAGESIZE,
            "generations": [],
            "files": [],
            "new_files": 0,
            "reused_files": 0,
            "released_files": 0,
            "new_prefaulted_bytes": 0,
            "prefaulted_bytes": 0,
            "mapped_page_bytes": 0,
            "locked_bytes": 0,
            "locked_page_bytes": 0,
            "locked_files": 0,
            "skipped": [],
            "errors": [],
        }
        selected = self._selection(report)
        for identity in list(self._mappings):
            if identity not in selected:
                self._mappings.pop(identity).close()
                report["released_files"] += 1
        for identity, paths in selected.items():
            path = paths[0]
            if identity in self._mappings:
                report["reused_files"] += 1
            else:
                try:
                    self._mappings[identity] = self._map(path, identity)
                except MemoryLockError:
                    self._release_all()
                    raise
                except OSError as error:
                    self._error(report, path, error)
                    continue
                report["new_files"] += 1
                report["new_prefaulted_bytes"] += identity[2]
            mapping = self._mappings[identity]
            size = identity[2]
            report["prefaulted_bytes"] += size
            report["mapped_page_bytes"] += _page_bytes(size)
            if mapping.locked:
                report["locked_files"] += 1
                report["locked_bytes"] += size
                report["locked_page_bytes"] += _page_bytes(size)
            report["files"].append(
                {
                    "paths": [str(path.relative_to(self.root)) for path in paths],
                    "identity": _identity_report(identity),
                    "locked": mapping.locked,
                    "lock_error": mapping.lock_error,
                }
            )
        report["file_count"] = len(report["files"])
        if not report["file_count"]:
            report["retention"] = "no-files"
        elif report["file_count"] == report["locked_files"]:
            report["retention"] = "locked"
        elif report["locked_files"]:
            report["retention"] = "partially-locked"
        else:
            report["retention"] = "prefaulted-only"
        report["skipped_bytes"] = sum(item["bytes"] for item in report["skipped"])
        report["skipped_page_bytes"] = sum(
            _page_bytes(item["bytes"]) for item in report["skipped"]
        )
        report["refresh_ns"] = time.perf_counter_ns() - started
        return report
