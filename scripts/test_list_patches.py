"""Verify complete inventories against exact upstream source identities."""

import unittest
from unittest import mock

import list_patches


class PatchInventoryTests(unittest.TestCase):
    def test_inventory_follows_the_rust_llvm_pin(self):
        rust_base, rust_head = "a" * 40, "b" * 40
        llvm_base, llvm_head = "c" * 40, "d" * 40
        rust = "astral-sh/ohm-rust"
        llvm = "astral-experiments/ohm-llvm"
        manifest = {
            "release": {
                "upstream_rust_version": "1.100.0",
                "toolchain_name": "ohm-1.100.0-9",
            },
            "sources": {
                "rust": {
                    "repository": f"https://github.com/{rust}",
                    "revision": rust_head,
                }
            },
        }
        stock = {
            "submodule_git_url": "https://github.com/rust-lang/llvm-project.git",
            "sha": llvm_base,
        }
        fork = {"submodule_git_url": f"https://github.com/{llvm}.git", "sha": llvm_head}
        responses = {
            "repos/rust-lang/rust/commits/1.100.0": {"sha": rust_base},
            f"repos/rust-lang/rust/contents/src/tools?ref={rust_base}": [],
            f"repos/rust-lang/rust/contents/src/llvm-project?ref={rust_base}": stock,
        }
        for pin in [fork, stock]:
            responses[f"repos/{rust}/contents/src/llvm-project?ref={rust_head}"] = pin
            with (
                self.subTest(pin=pin),
                mock.patch.object(
                    list_patches, "api", side_effect=responses.__getitem__
                ),
                mock.patch.object(list_patches, "commits", return_value=[]) as commits,
            ):
                report = list_patches.inventory(manifest)
                if pin == fork:
                    commits.assert_any_call(llvm, llvm_base, llvm_head)
                    self.assertIn(
                        f"https://github.com/{llvm}/compare/{llvm_base}...{llvm_head}",
                        report,
                    )
                else:
                    commits.assert_called_once_with(rust, rust_base, rust_head)
                    self.assertNotIn(llvm, report)

    def test_reads_every_comparison_page(self):
        pages = [
            {
                "behind_by": 0,
                "base_commit": {"sha": "base"},
                "total_commits": 2,
                "commits": [{"sha": sha}],
            }
            for sha in ("one", "two")
        ]
        with mock.patch.object(list_patches, "api", side_effect=pages) as api:
            self.assertEqual(
                [c["sha"] for c in list_patches.commits("owner/repo", "base", "head")],
                ["one", "two"],
            )
        self.assertIn("page=2", api.call_args.args[0])

    def test_rejects_diverged_or_truncated_comparisons(self):
        for behind, commits in ((1, [{"sha": "one"}]), (0, [])):
            with (
                self.subTest(behind=behind),
                mock.patch.object(
                    list_patches,
                    "api",
                    return_value={
                        "behind_by": behind,
                        "base_commit": {"sha": "base"},
                        "total_commits": 1,
                        "commits": commits,
                    },
                ),
            ):
                with self.assertRaises(ValueError):
                    list_patches.commits("owner/repo", "base", "head")

    def test_subtree_base_requires_exact_content(self):
        pages = [
            [{"sha": "wrong", "commit": {"tree": {"sha": "different"}}}],
            [{"sha": "correct", "commit": {"tree": {"sha": "upstream"}}}],
        ]
        with mock.patch.object(list_patches, "api", side_effect=pages):
            self.assertEqual(
                list_patches.subtree_base("owner/repo", "head", "upstream"), "correct"
            )
        with mock.patch.object(list_patches, "api", return_value=[]):
            with self.assertRaises(ValueError):
                list_patches.subtree_base("owner/repo", "head", "upstream")


if __name__ == "__main__":
    unittest.main()
