"""Validate safe acceptance aggregation without model calls or credentials."""
import runpy
import unittest
from pathlib import Path

VERIFY = Path(__file__).resolve().parents[1] / "trial-mysql/verify-real-chat.py"
reasoning_replay = runpy.run_path(str(VERIFY))["reasoning_replay"]


class ReasoningAcceptanceTests(unittest.TestCase):
    def test_decision_and_final_call_chunks_match_ordered_history(self) -> None:
        events = [
            {"type": "step", "step": 0, "content": "schema read"},
            {"type": "reasoning", "step": 0, "content": "one "},
            {"type": "reasoning", "step": 0, "content": "decision"},
            {"type": "step", "step": 0, "content": "query result"},
            {"type": "reasoning", "step": 1, "content": "final "},
            {"type": "summary_delta", "step": 1, "content": "Answer"},
            {"type": "reasoning", "step": 1, "content": "thought"},
            {"type": "summary", "step": 1, "content": "Answer"},
        ]
        history = [
            {"type": "step", "step": 0, "content": "schema read"},
            {"type": "reasoning", "step": 0, "content": "one decision"},
            {"type": "step", "step": 0, "content": "query result"},
            {"type": "reasoning", "step": 1, "content": "final thought"},
            {"type": "summary", "step": 1, "content": "Answer"},
        ]
        result = reasoning_replay(events, history)
        self.assertTrue(result["reasoningReplayMatches"])
        self.assertTrue(result["replayOrderMatches"])
        self.assertEqual(result["reasoningBlockCharacters"], [12, 13])
        self.assertNotIn("one decision", str(result))
        self.assertNotIn("final thought", str(result))

    def test_missing_or_duplicated_reasoning_fails(self) -> None:
        events = [{"type": "reasoning", "step": 0, "content": "actual"}]
        self.assertFalse(reasoning_replay(events, [])["reasoningReplayMatches"])
        history = [{"type": "reasoning", "step": 0, "content": "actual", "reasoningContent": "actual"}]
        self.assertFalse(reasoning_replay(events, history)["reasoningReplayMatches"])

    def test_tool_boundary_preserves_distinct_blocks_even_on_same_step(self) -> None:
        events = [{"type": "reasoning", "step": 0, "content": "first"},
                  {"type": "step", "step": 0, "content": "tool result"},
                  {"type": "reasoning", "step": 0, "content": "second"}]
        history = list(reversed(events))
        self.assertFalse(reasoning_replay(events, history)["replayOrderMatches"])
        self.assertEqual(reasoning_replay(events, events)["reasoningBlockCount"], 2)

    def test_no_reasoning_provider_does_not_require_fabricated_blocks(self) -> None:
        result = reasoning_replay([], [])
        self.assertTrue(result["reasoningReplayMatches"])
        self.assertFalse(result["reasoningObserved"])
        self.assertEqual(result["reasoningBlockCount"], 0)


if __name__ == "__main__":
    unittest.main()
