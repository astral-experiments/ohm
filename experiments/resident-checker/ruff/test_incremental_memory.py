"""Checks for truthful OS-memory retention across fresh rustc generations."""

import errno
import mmap
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from incremental_memory import FILES, IncrementalMemory, MemoryLockError


class TestIncrementalMemory(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def generation(self, timestamp, *, crate="crate-abc", suffix="dead", files=None):
        path = self.root / crate / f"s-{timestamp}-abc-{suffix}"
        path.mkdir(parents=True)
        if files is None:
            files = {name: (name + timestamp).encode() for name in FILES}
        for name, content in files.items():
            (path / name).write_bytes(content)
        return path

    @patch("incremental_memory._memory_call")
    def test_only_newest_completed_generation_and_serialized_inputs(self, memory_call):
        self.generation("0001")
        self.generation("000a")
        self.generation("000b", suffix="working")
        newest = self.generation("0010")
        (newest / "unrelated.o").write_bytes(b"do not map a machine-code file")
        other = self.generation("0001", crate="other-def")
        with IncrementalMemory(self.root) as memory:
            report = memory.refresh()
            self.assertEqual(report["retention"], "locked")
            self.assertEqual(report["file_count"], 6)
            self.assertEqual(report["locked_files"], 6)
            self.assertEqual(report["errors"], [])
            self.assertEqual(
                report["generations"],
                [str(path.relative_to(self.root)) for path in (newest, other)],
            )
            self.assertEqual(
                {Path(item["paths"][0]).name for item in report["files"]}, set(FILES)
            )
            first = report["files"][0]
            original = (newest / FILES[0]).stat()
            self.assertEqual(first["identity"]["device"], original.st_dev)
            self.assertEqual(first["identity"]["inode"], original.st_ino)
            self.assertEqual(first["identity"]["bytes"], original.st_size)
            again = memory.refresh()
            self.assertEqual(again["new_files"], 0)
            self.assertEqual(again["reused_files"], 6)
            self.assertEqual(again["new_prefaulted_bytes"], 0)
            self.assertGreater(again["refresh_ns"], 0)
        self.assertEqual(
            [call.args[0] for call in memory_call.call_args_list],
            ["mlock"] * 6 + ["munlock"] * 6,
        )

    @patch("incremental_memory._memory_call")
    def test_replacement_releases_old_generation_even_if_rustc_unlinks_it(self, calls):
        old = self.generation("0001")
        with IncrementalMemory(self.root) as memory:
            first = memory.refresh()
            old_inodes = {item["identity"]["inode"] for item in first["files"]}
            new = self.generation("0002")
            shutil.rmtree(old)
            second = memory.refresh()
            self.assertEqual(second["new_files"], 3)
            self.assertEqual(second["released_files"], 3)
            self.assertEqual(second["reused_files"], 0)
            self.assertEqual(second["generations"], [str(new.relative_to(self.root))])
            self.assertTrue(
                old_inodes.isdisjoint(
                    item["identity"]["inode"] for item in second["files"]
                )
            )
            shutil.rmtree(new)
            empty = memory.refresh()
            self.assertEqual(empty["retention"], "no-files")
            self.assertEqual(empty["released_files"], 3)
        self.assertEqual(
            [call.args[0] for call in calls.call_args_list],
            ["mlock"] * 3 + ["munlock"] * 3 + ["mlock"] * 3 + ["munlock"] * 3,
        )

    @patch("incremental_memory._memory_call")
    def test_limit_bounds_page_rounded_mappings_and_skips_whole_files(self, _):
        self.generation(
            "0001",
            files={
                FILES[0]: b"x" * (mmap.PAGESIZE + 1),
                FILES[1]: b"y",
                FILES[2]: b"z",
            },
        )
        with IncrementalMemory(self.root, limit_bytes=mmap.PAGESIZE) as memory:
            report = memory.refresh()
            self.assertEqual(report["file_count"], 1)
            self.assertEqual(report["prefaulted_bytes"], 1)
            self.assertEqual(report["locked_bytes"], 1)
            self.assertEqual(report["mapped_page_bytes"], mmap.PAGESIZE)
            self.assertEqual(report["locked_page_bytes"], mmap.PAGESIZE)
            self.assertEqual(
                [Path(item["path"]).name for item in report["skipped"]],
                [FILES[0], FILES[2]],
            )
            self.assertEqual(report["skipped_page_bytes"], 3 * mmap.PAGESIZE)
        with IncrementalMemory(self.root, limit_bytes=0) as memory:
            self.assertEqual(memory.refresh()["retention"], "no-files")
        with self.assertRaises(ValueError):
            IncrementalMemory(self.root, limit_bytes=-1)

    def test_soft_lock_failure_remains_prefaulted_but_is_never_reported_locked(self):
        self.generation("0001", files={FILES[0]: b"x"})
        denied = PermissionError(errno.EPERM, "pinning prohibited")
        with (
            patch("incremental_memory._memory_call", side_effect=denied) as calls,
            IncrementalMemory(self.root) as memory,
        ):
            report = memory.refresh()
            self.assertEqual(report["retention"], "prefaulted-only")
            self.assertEqual(report["prefaulted_bytes"], 1)
            self.assertEqual(report["locked_bytes"], 0)
            self.assertEqual(report["locked_page_bytes"], 0)
            self.assertIn("pinning prohibited", report["files"][0]["lock_error"])
            self.assertEqual(memory.refresh()["reused_files"], 1)
        self.assertEqual([call.args[0] for call in calls.call_args_list], ["mlock"])

    def test_strict_lock_failure_closes_previous_and_partial_generation(self):
        self.generation("0001")
        mlocks = 0

        def memory_call(name, _):
            nonlocal mlocks
            if name == "mlock":
                mlocks += 1
                if mlocks == 2:
                    raise OSError(errno.ENOMEM, "lock allowance exhausted")

        with (
            patch("incremental_memory._memory_call", side_effect=memory_call) as calls,
            IncrementalMemory(self.root, require_lock=True) as memory,
        ):
            with self.assertRaisesRegex(MemoryLockError, "lock allowance exhausted"):
                memory.refresh()
            self.assertEqual(memory._mappings, {})
            self.assertEqual(
                [call.args[0] for call in calls.call_args_list],
                ["mlock", "mlock", "munlock"],
            )
            self.assertEqual(memory.refresh()["retention"], "locked")

    def test_partial_lock_and_failed_explicit_unlock_are_reported_and_cleaned(self):
        self.generation("0001", files={FILES[0]: b"x", FILES[1]: b"y"})
        lock_count = 0

        def memory_call(name, _):
            nonlocal lock_count
            if name == "mlock":
                lock_count += 1
                if lock_count == 2:
                    raise OSError(errno.ENOMEM, "lock limit")
            else:
                raise OSError(errno.EINVAL, "simulate a failed explicit unlock")

        with (
            patch("incremental_memory._memory_call", side_effect=memory_call),
            IncrementalMemory(self.root) as memory,
        ):
            report = memory.refresh()
            self.assertEqual(report["retention"], "partially-locked")
            self.assertEqual(report["prefaulted_bytes"], 2)
            self.assertEqual(report["locked_bytes"], 1)
            self.assertEqual(report["locked_files"], 1)
            mappings = [mapping.data for mapping in memory._mappings.values()]
        self.assertTrue(all(mapping.closed for mapping in mappings))

    @patch("incremental_memory._memory_call")
    def test_same_path_replacement_changes_file_identity(self, _):
        current = self.generation("0001", files={FILES[0]: b"old"})
        with IncrementalMemory(self.root) as memory:
            old = memory.refresh()
            destination = current / FILES[0]
            temporary = current / "replacement"
            temporary.write_bytes(b"new")
            temporary.replace(destination)
            new = memory.refresh()
            self.assertEqual(new["new_files"], 1)
            self.assertEqual(new["released_files"], 1)
            self.assertNotEqual(
                old["files"][0]["identity"]["inode"],
                new["files"][0]["identity"]["inode"],
            )
            self.assertEqual(destination.read_bytes(), b"new")

    @patch("incremental_memory._memory_call")
    def test_only_regular_files_and_no_symlinked_crates_or_generations(self, _):
        current = self.generation("0001", files={})
        outside = self.root / "outside"
        outside.write_bytes(b"outside")
        (current / FILES[0]).symlink_to(outside)
        (current / FILES[1]).mkdir()
        (current / FILES[2]).write_bytes(b"")
        (self.root / "linked-crate").symlink_to(
            current.parent, target_is_directory=True
        )
        (current.parent / "s-9999-abc-dead").symlink_to(
            current, target_is_directory=True
        )
        with IncrementalMemory(self.root) as memory:
            report = memory.refresh()
            self.assertEqual(report["retention"], "no-files")
            self.assertEqual(
                report["generations"], [str(current.relative_to(self.root))]
            )
            self.assertEqual(
                [item["reason"] for item in report["skipped"]],
                ["not-regular", "not-regular", "empty"],
            )

    @patch("incremental_memory._memory_call")
    def test_hard_linked_serialized_files_share_one_mapping_and_cap(self, _):
        current = self.generation("0001", files={FILES[0]: b"same"})
        os.link(current / FILES[0], current / FILES[1])
        with IncrementalMemory(self.root, limit_bytes=mmap.PAGESIZE) as memory:
            report = memory.refresh()
            self.assertEqual(report["file_count"], 1)
            self.assertEqual(report["mapped_page_bytes"], mmap.PAGESIZE)
            self.assertEqual(
                [Path(path).name for path in report["files"][0]["paths"]],
                list(FILES[:2]),
            )
            self.assertEqual(report["skipped"], [])

    def test_missing_root_and_closed_state(self):
        with IncrementalMemory(self.root / "not-created-yet") as memory:
            report = memory.refresh()
            self.assertEqual(report["retention"], "no-files")
            self.assertEqual(report["errors"], [])
        memory.close()
        with self.assertRaisesRegex(RuntimeError, "already closed"):
            memory.refresh()

    def test_os_mapping_and_lock_status_are_consistent(self):
        content = b"data" * mmap.PAGESIZE
        current = self.generation("0001", files={FILES[0]: content})
        with IncrementalMemory(self.root) as memory:
            report = memory.refresh()
            self.assertEqual(report["file_count"], 1)
            self.assertEqual(report["prefaulted_bytes"], len(content))
            self.assertIn(report["retention"], ("locked", "prefaulted-only"))
            file = report["files"][0]
            self.assertEqual(file["locked"], report["retention"] == "locked")
            self.assertEqual(file["lock_error"] is None, file["locked"])
        self.assertEqual((current / FILES[0]).read_bytes(), content)


if __name__ == "__main__":
    unittest.main()
