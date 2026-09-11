"""Verify complete inventories against exact upstream source identities."""

import unittest
from unittest import mock

import list_patches


class PatchInventoryTests(unittest.TestCase):
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
