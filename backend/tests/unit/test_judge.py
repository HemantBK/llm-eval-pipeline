"""Tests for judge engine — JSON parsing, score extraction, edge cases."""

import json

import pytest

from app.errors.exceptions import JudgeParseError
from app.judge.engine import JudgeEngine


class TestJudgeJSONParsing:
    """Test the judge's ability to extract and parse JSON from raw text."""

    def _make_engine(self):
        """Create a JudgeEngine with a mock registry (not used for parsing tests)."""
        from unittest.mock import MagicMock

        return JudgeEngine(MagicMock())

    def test_parse_clean_json(self):
        engine = self._make_engine()
        raw = json.dumps(
            {
                "accuracy": 4,
                "completeness": 5,
                "code_quality": 3,
                "safety": 5,
                "hallucination": 4,
                "reasoning": 4,
                "overall_pass": True,
                "judge_notes": "Good response.",
                "dimension_reasoning": {
                    "accuracy": "correct",
                    "completeness": "covered all",
                    "code_quality": "decent",
                    "safety": "safe",
                    "hallucination": "none",
                    "reasoning": "clear",
                },
            }
        )

        from app.judge.rubrics import DEFAULT_RUBRIC

        verdict = engine._parse_judge_response(raw, DEFAULT_RUBRIC, "test-model")

        assert verdict.scores["accuracy"] == 4.0
        assert verdict.scores["safety"] == 5.0
        assert verdict.overall_pass is True

    def test_parse_json_in_markdown_fences(self):
        engine = self._make_engine()
        inner = json.dumps(
            {
                "accuracy": 3,
                "completeness": 3,
                "code_quality": 3,
                "safety": 5,
                "hallucination": 4,
                "reasoning": 3,
                "overall_pass": False,
                "judge_notes": "Mediocre.",
                "dimension_reasoning": {},
            }
        )
        raw = f"```json\n{inner}\n```"

        from app.judge.rubrics import DEFAULT_RUBRIC

        verdict = engine._parse_judge_response(raw, DEFAULT_RUBRIC, "test-model")

        assert verdict.scores["accuracy"] == 3.0
        assert verdict.overall_pass is False

    def test_parse_json_with_surrounding_text(self):
        engine = self._make_engine()
        inner = json.dumps(
            {
                "accuracy": 5,
                "completeness": 5,
                "code_quality": 5,
                "safety": 5,
                "hallucination": 5,
                "reasoning": 5,
                "overall_pass": True,
                "judge_notes": "Perfect.",
                "dimension_reasoning": {},
            }
        )
        raw = f"Here is my evaluation:\n{inner}\nEnd of evaluation."

        from app.judge.rubrics import DEFAULT_RUBRIC

        verdict = engine._parse_judge_response(raw, DEFAULT_RUBRIC, "test-model")

        assert verdict.scores["accuracy"] == 5.0
        assert verdict.overall_pass is True

    def test_score_clamped_to_range(self):
        engine = self._make_engine()
        raw = json.dumps(
            {
                "accuracy": 10,  # over max
                "completeness": 0,  # under min
                "code_quality": 3,
                "safety": 5,
                "hallucination": 4,
                "reasoning": 4,
                "overall_pass": True,
                "judge_notes": "Clamping test.",
                "dimension_reasoning": {},
            }
        )

        from app.judge.rubrics import DEFAULT_RUBRIC

        verdict = engine._parse_judge_response(raw, DEFAULT_RUBRIC, "test-model")

        assert verdict.scores["accuracy"] == 5.0  # clamped to max
        assert verdict.scores["completeness"] == 1.0  # clamped to min

    def test_missing_dimension_raises(self):
        engine = self._make_engine()
        raw = json.dumps(
            {
                "accuracy": 4,
                # missing completeness, code_quality, etc.
                "overall_pass": True,
            }
        )

        from app.judge.rubrics import DEFAULT_RUBRIC

        with pytest.raises(JudgeParseError, match="Missing dimension"):
            engine._parse_judge_response(raw, DEFAULT_RUBRIC, "test-model")

    def test_no_json_raises(self):
        engine = self._make_engine()
        raw = "This response has no JSON at all. Just plain text."

        from app.judge.rubrics import DEFAULT_RUBRIC

        with pytest.raises(JudgeParseError, match="No JSON object found"):
            engine._parse_judge_response(raw, DEFAULT_RUBRIC, "test-model")

    def test_invalid_json_raises(self):
        engine = self._make_engine()
        raw = '{"accuracy": 4, "completeness": INVALID}'

        from app.judge.rubrics import DEFAULT_RUBRIC

        with pytest.raises(JudgeParseError):
            engine._parse_judge_response(raw, DEFAULT_RUBRIC, "test-model")
