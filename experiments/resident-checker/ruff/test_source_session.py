import unittest

from measure_source import ResidentSourceState


class TestResidentSourceState(unittest.TestCase):
    def test_supported_file_cannot_hide_unresolved_fallback(self):
        state = ResidentSourceState({"a.rs": "original", "b.rs": "original"})
        self.assertEqual(
            state.observe("a.rs", "unsupported", "fallback", "signature"),
            ("fallback", "signature"),
        )
        for text in ("edited", "original"):
            self.assertEqual(
                state.observe("b.rs", text, "resident", None),
                ("fallback", "unresolved-source-fallback:a.rs"),
            )
            self.assertEqual(state.accepted["b.rs"], text)
        self.assertEqual(
            state.observe("a.rs", "original", "noop", None), ("noop", None)
        )
        self.assertEqual(
            state.observe("b.rs", "edited", "resident", None), ("resident", None)
        )

    def test_every_pending_file_must_be_resolved(self):
        state = ResidentSourceState({"a.rs": "a", "b.rs": "b", "c.rs": "c"})
        state.observe("b.rs", "changed", "fallback", "signature")
        state.observe("a.rs", "changed", "fallback", "imports")
        self.assertEqual(
            state.observe("c.rs", "c", "noop", None),
            ("fallback", "unresolved-source-fallback:a.rs,b.rs"),
        )
        self.assertEqual(
            state.observe("a.rs", "other but supported", "resident", None),
            ("fallback", "unresolved-source-fallback:b.rs"),
        )
        self.assertEqual(state.observe("b.rs", "b", "noop", None), ("noop", None))


if __name__ == "__main__":
    unittest.main()
