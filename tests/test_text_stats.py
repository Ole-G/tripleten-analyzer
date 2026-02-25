"""Tests for src/utils/text_stats.compute_text_stats()."""

import sys
from pathlib import Path

import pytest

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.text_stats import compute_text_stats


class TestComputeTextStats:
    """Tests for the compute_text_stats function."""

    def test_empty_string(self):
        result = compute_text_stats("")
        assert result["word_count"] == 0
        assert result["sentence_count"] == 0
        assert result["question_count"] == 0

    def test_none_input(self):
        result = compute_text_stats(None)
        assert result["word_count"] == 0

    def test_non_string_input(self):
        result = compute_text_stats(42)
        assert result["word_count"] == 0

    def test_basic_sentence(self):
        result = compute_text_stats("Hello world.")
        assert result["word_count"] == 2
        assert result["sentence_count"] == 1
        assert result["question_count"] == 0
        assert result["exclamation_count"] == 0

    def test_multiple_sentences(self):
        text = "First sentence. Second sentence. Third sentence."
        result = compute_text_stats(text)
        assert result["word_count"] == 6
        assert result["sentence_count"] == 3

    def test_questions(self):
        text = "What do you think? Are you sure? Yes!"
        result = compute_text_stats(text)
        assert result["question_count"] == 2
        assert result["exclamation_count"] == 1

    def test_first_person_pronouns(self):
        text = "I went to my school. My friend gave me a book."
        result = compute_text_stats(text)
        assert result["first_person_count"] == 4  # I, my, My, me

    def test_second_person_pronouns(self):
        text = "You should check your schedule. It's yours."
        result = compute_text_stats(text)
        assert result["second_person_count"] == 3  # You, your, yours

    def test_product_name_tripleten(self):
        text = "Check out TripleTen. TripleTen offers great courses."
        result = compute_text_stats(text)
        assert result["product_name_mentions"] == 2

    def test_product_name_triple_ten_with_space(self):
        text = "Triple Ten has amazing programs."
        result = compute_text_stats(text)
        assert result["product_name_mentions"] == 1

    def test_product_name_case_insensitive(self):
        text = "tripleten and TRIPLETEN are the same."
        result = compute_text_stats(text)
        assert result["product_name_mentions"] == 2

    def test_no_terminal_punctuation(self):
        """Text with words but no sentence-ending punctuation gets 1 sentence."""
        result = compute_text_stats("Hello world")
        assert result["word_count"] == 2
        assert result["sentence_count"] == 1

    def test_real_integration_text(self):
        """Test with a realistic integration text snippet."""
        text = (
            "I've been coding for years, but I never found a program like TripleTen. "
            "You can change your career in just 7 months! "
            "Have you ever thought about switching to tech? "
            "My friend recommended TripleTen to me, and it changed my life. "
            "Check out the link in the description for a special discount."
        )
        result = compute_text_stats(text)
        assert result["word_count"] > 40
        assert result["sentence_count"] == 5
        assert result["question_count"] == 1
        assert result["exclamation_count"] == 1
        assert result["first_person_count"] >= 4  # I've, I, My, me, my
        assert result["second_person_count"] >= 2  # You, you, your
        assert result["product_name_mentions"] == 2

    def test_all_keys_present(self):
        """Ensure all expected keys are always in the output."""
        result = compute_text_stats("test")
        expected_keys = {
            "word_count", "sentence_count", "question_count",
            "exclamation_count", "first_person_count", "second_person_count",
            "product_name_mentions",
        }
        assert set(result.keys()) == expected_keys

    def test_all_values_are_integers(self):
        """All returned values should be integers."""
        result = compute_text_stats("Hello world. Check out TripleTen!")
        for key, value in result.items():
            assert isinstance(value, int), f"{key} should be int, got {type(value)}"
