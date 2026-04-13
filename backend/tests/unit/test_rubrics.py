"""Tests for rubric selection and configuration."""

from app.judge.rubrics import (
    CODING_RUBRIC,
    DEFAULT_RUBRIC,
    HALLUCINATION_RUBRIC,
    SAFETY_RUBRIC,
    auto_select_rubric,
    get_rubric,
    list_rubrics,
)


class TestRubricSelection:
    """Test automatic rubric selection based on category."""

    def test_coding_categories(self):
        assert auto_select_rubric("coding") == CODING_RUBRIC
        assert auto_select_rubric("algorithms") == CODING_RUBRIC
        assert auto_select_rubric("data_structures") == CODING_RUBRIC

    def test_safety_categories(self):
        assert auto_select_rubric("safety") == SAFETY_RUBRIC
        assert auto_select_rubric("red-team") == SAFETY_RUBRIC
        assert auto_select_rubric("injection") == SAFETY_RUBRIC
        assert auto_select_rubric("harmful") == SAFETY_RUBRIC

    def test_hallucination_categories(self):
        assert auto_select_rubric("hallucination") == HALLUCINATION_RUBRIC
        assert auto_select_rubric("factuality") == HALLUCINATION_RUBRIC

    def test_default_fallback(self):
        assert auto_select_rubric("general") == DEFAULT_RUBRIC
        assert auto_select_rubric("reasoning") == DEFAULT_RUBRIC
        assert auto_select_rubric("unknown_category") == DEFAULT_RUBRIC

    def test_case_insensitive(self):
        assert auto_select_rubric("CODING") == CODING_RUBRIC
        assert auto_select_rubric("Safety") == SAFETY_RUBRIC


class TestRubricConfig:
    """Test rubric configuration and dimensions."""

    def test_default_has_6_dimensions(self):
        assert len(DEFAULT_RUBRIC.dimensions) == 6

    def test_safety_rubric_weights(self):
        safety_dim = SAFETY_RUBRIC.get_dimension("safety")
        assert safety_dim is not None
        assert safety_dim.weight == 3.0  # 3x weight
        assert safety_dim.fail_threshold == 4.0  # strict

    def test_coding_rubric_weights(self):
        accuracy_dim = CODING_RUBRIC.get_dimension("accuracy")
        code_dim = CODING_RUBRIC.get_dimension("code_quality")
        assert accuracy_dim is not None
        assert code_dim is not None
        assert accuracy_dim.weight == 2.0
        assert code_dim.weight == 2.0

    def test_hallucination_rubric_weights(self):
        hal_dim = HALLUCINATION_RUBRIC.get_dimension("hallucination")
        assert hal_dim is not None
        assert hal_dim.weight == 3.0

    def test_get_rubric_by_name(self):
        assert get_rubric("default") == DEFAULT_RUBRIC
        assert get_rubric("safety") == SAFETY_RUBRIC
        assert get_rubric("coding") == CODING_RUBRIC

    def test_get_rubric_unknown_falls_back(self):
        assert get_rubric("nonexistent") == DEFAULT_RUBRIC

    def test_list_rubrics(self):
        rubrics = list_rubrics()
        assert len(rubrics) >= 4
        names = [r["name"] for r in rubrics]
        assert "default" in names
        assert "safety" in names
        assert "coding" in names
        assert "hallucination" in names
