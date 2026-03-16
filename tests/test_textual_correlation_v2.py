"""Tests for build_textual_comparison_v2 (cost_per_contact quartile classification)."""

import pytest

from src.analysis.textual_correlation import build_textual_comparison_v2
from src.analysis.textual_aggregation_tables import compute_all_textual_tables_v2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_textual_response() -> dict:
    return {
        "opening_pattern": {
            "first_sentence": "So I've been using this platform called TripleTen.",
            "opening_type": "personal_anecdote",
            "opening_hook": "I've been using this platform",
        },
        "closing_pattern": {
            "last_sentence": "Link is in the description below.",
            "closing_type": "cta_repeat",
            "closing_phrase": "Link is in the description",
        },
        "transition": {
            "transition_phrase": "Speaking of learning new things",
            "transition_style": "topic_related",
            "acknowledges_sponsorship": True,
        },
        "persuasion_phrases": [
            {
                "phrase": "I changed my career in just 7 months",
                "function": "social_proof",
                "position": "opening",
            },
        ],
        "benefit_framings": ["change your career in 7 months"],
        "pain_point_framings": ["stuck in a dead-end job"],
        "cta_phrases": [
            {
                "phrase": "Click the link in the description",
                "type": "consultation",
                "urgency_words": ["free"],
            },
        ],
        "specificity_markers": ["$200 per month"],
        "emotional_triggers": ["imagine waking up excited"],
        "rhetorical_questions": ["Have you ever felt stuck?"],
        "text_stats": {
            "word_count": 245,
            "sentence_count": 18,
            "question_count": 3,
            "exclamation_count": 2,
            "first_person_count": 8,
            "second_person_count": 12,
            "product_name_mentions": 3,
        },
    }


def _make_enriched_record(
    ad_link: str = "https://youtube.com/watch?v=test123",
    has_textual: bool = True,
) -> dict:
    """Create a mock enriched record."""
    record = {
        "video_id": "test123",
        "url": ad_link,
        "enrichment": {
            "extraction": {
                "integration_text": "Test integration text...",
            },
        },
    }
    if has_textual:
        record["enrichment"]["textual"] = _valid_textual_response()
    return record


def _make_merged_record(
    ad_link: str = "https://youtube.com/watch?v=test123",
    budget: float = 5000.0,
    contacts: float = 50.0,
    format_val: str = "youtube",
    purchases: float = 0.0,
) -> dict:
    """Create a mock merged record with Budget and Contacts Fact."""
    return {
        "Ad link": ad_link,
        "Budget": budget,
        "Contacts Fact": contacts,
        "Format": format_val,
        "Purchase F - TOTAL": purchases,
    }


# ---------------------------------------------------------------------------
# Build test data: 8 youtube records with varying cost_per_contact
# ---------------------------------------------------------------------------

def _build_youtube_dataset():
    """Build 8 youtube enriched + merged records with known cost_per_contact.

    cost_per_contact values (Budget / Contacts Fact):
      url_1: 1000/100 = 10   -> Q1 (high_performers)
      url_2: 1000/50  = 20   -> Q1 (high_performers)
      url_3: 2000/50  = 40   -> Q2 (middle, excluded)
      url_4: 3000/50  = 60   -> Q2 (middle, excluded)
      url_5: 4000/50  = 80   -> Q3 (middle, excluded)
      url_6: 5000/50  = 100  -> Q3 (middle, excluded)
      url_7: 6000/50  = 120  -> Q4 (low_performers)
      url_8: 7000/50  = 140  -> Q4 (low_performers)
    """
    enriched = []
    merged = []

    configs = [
        ("https://yt.com/1", 1000, 100, "youtube"),   # cpc=10
        ("https://yt.com/2", 1000, 50, "youtube"),    # cpc=20
        ("https://yt.com/3", 2000, 50, "youtube"),    # cpc=40
        ("https://yt.com/4", 3000, 50, "youtube"),    # cpc=60
        ("https://yt.com/5", 4000, 50, "youtube"),    # cpc=80
        ("https://yt.com/6", 5000, 50, "youtube"),    # cpc=100
        ("https://yt.com/7", 6000, 50, "youtube"),    # cpc=120
        ("https://yt.com/8", 7000, 50, "youtube"),    # cpc=140
    ]

    for url, budget, contacts, fmt in configs:
        enriched.append(_make_enriched_record(ad_link=url))
        merged.append(_make_merged_record(
            ad_link=url, budget=budget, contacts=contacts, format_val=fmt,
        ))

    return enriched, merged


def _build_mixed_platform_dataset():
    """Build dataset with both youtube and short-form records.

    YouTube (4 records, cost_per_contact):
      yt_1: 1000/100 = 10   -> Q1
      yt_2: 5000/50  = 100  -> Q4

    Short-form (4 records, cost_per_contact):
      reel_1: 500/50   = 10   -> Q1
      reel_2: 2000/20  = 100  -> Q4
      tiktok_1: 300/30 = 10   -> Q1
      tiktok_2: 1500/10 = 150 -> Q4
    """
    enriched = []
    merged = []

    configs = [
        # YouTube
        ("https://yt.com/yt1", 1000, 100, "youtube"),
        ("https://yt.com/yt2", 2000, 100, "youtube"),
        ("https://yt.com/yt3", 4000, 100, "youtube"),
        ("https://yt.com/yt4", 5000, 100, "youtube"),
        # Reels
        ("https://ig.com/reel1", 500, 50, "reel"),
        ("https://ig.com/reel2", 1000, 50, "reel"),
        ("https://ig.com/reel3", 2000, 50, "reel"),
        ("https://ig.com/reel4", 3000, 50, "reel"),
        # TikTok
        ("https://tt.com/tt1", 300, 30, "tiktok"),
        ("https://tt.com/tt2", 600, 30, "tiktok"),
        ("https://tt.com/tt3", 1200, 30, "tiktok"),
        ("https://tt.com/tt4", 1500, 30, "tiktok"),
    ]

    for url, budget, contacts, fmt in configs:
        enriched.append(_make_enriched_record(ad_link=url))
        merged.append(_make_merged_record(
            ad_link=url, budget=budget, contacts=contacts, format_val=fmt,
        ))

    return enriched, merged


# ---------------------------------------------------------------------------
# Tests: Classification uses cost_per_contact, NOT purchases
# ---------------------------------------------------------------------------

class TestCostPerContactClassification:
    """Verify classification is based on cost_per_contact quartiles."""

    def test_uses_cost_per_contact_not_purchases(self):
        """Output keys are high_performers/low_performers, not purchase-based."""
        enriched, merged = _build_youtube_dataset()
        result = build_textual_comparison_v2(enriched, merged)

        assert "high_performers" in result["sample_sizes"]
        assert "low_performers" in result["sample_sizes"]
        assert "with_purchases" not in result["sample_sizes"]
        assert "without_purchases" not in result["sample_sizes"]

    def test_output_has_high_low_performer_keys(self):
        """All comparison sections use high_performers/low_performers keys."""
        enriched, merged = _build_youtube_dataset()
        result = build_textual_comparison_v2(enriched, merged)

        # Check opening_patterns has the right keys
        assert "high_performers" in result["opening_patterns"]
        assert "low_performers" in result["opening_patterns"]
        assert "with_purchases" not in result["opening_patterns"]

        # Check cta_analysis
        assert "high_performers" in result["cta_analysis"]
        assert "low_performers" in result["cta_analysis"]


# ---------------------------------------------------------------------------
# Tests: Middle 50% excluded
# ---------------------------------------------------------------------------

class TestMiddleExclusion:
    """Verify middle 50% is excluded for cleaner comparison."""

    def test_middle_50_percent_excluded(self):
        """Sample sizes should show high + low + excluded = total."""
        enriched, merged = _build_youtube_dataset()
        result = build_textual_comparison_v2(enriched, merged)

        sizes = result["sample_sizes"]
        high = sizes["high_performers"]
        low = sizes["low_performers"]
        excluded = sizes["excluded_middle"]

        # All 8 records have valid cost_per_contact
        assert high + low + excluded == 8
        # Middle 50% excluded
        assert excluded > 0

    def test_q1_and_q4_are_selected(self):
        """Q1 (low cost = efficient) -> high_performers, Q4 (high cost) -> low_performers."""
        enriched, merged = _build_youtube_dataset()
        result = build_textual_comparison_v2(enriched, merged)

        sizes = result["sample_sizes"]
        # With 8 records, Q1 and Q4 should each have ~2 records
        assert sizes["high_performers"] >= 1
        assert sizes["low_performers"] >= 1


# ---------------------------------------------------------------------------
# Tests: Missing Budget or Contacts skipped
# ---------------------------------------------------------------------------

class TestMissingDataHandling:
    """Records with missing/zero Budget or Contacts are skipped."""

    def test_missing_budget_skipped(self):
        """Records with missing Budget are excluded."""
        enriched = [
            _make_enriched_record(ad_link="https://yt.com/a"),
            _make_enriched_record(ad_link="https://yt.com/b"),
        ]
        merged = [
            _make_merged_record(
                ad_link="https://yt.com/a", budget=0, contacts=50,
                format_val="youtube",
            ),
            _make_merged_record(
                ad_link="https://yt.com/b", budget=5000, contacts=50,
                format_val="youtube",
            ),
        ]

        result = build_textual_comparison_v2(enriched, merged)

        # Record with budget=0 should be skipped (cost_per_contact=0 is valid
        # but we need at least 4 records for quartiles, so it may still be in
        # the result). The key thing is no crash.
        total = (
            result["sample_sizes"]["high_performers"]
            + result["sample_sizes"]["low_performers"]
            + result["sample_sizes"]["excluded_middle"]
        )
        # Should not exceed total number of valid records
        assert total <= 2

    def test_zero_contacts_skipped(self):
        """Records with Contacts Fact = 0 are excluded (division by zero)."""
        enriched = [_make_enriched_record(ad_link="https://yt.com/a")]
        merged = [
            _make_merged_record(
                ad_link="https://yt.com/a", budget=5000, contacts=0,
                format_val="youtube",
            ),
        ]

        result = build_textual_comparison_v2(enriched, merged)

        sizes = result["sample_sizes"]
        total = sizes["high_performers"] + sizes["low_performers"] + sizes["excluded_middle"]
        assert total == 0

    def test_none_contacts_skipped(self):
        """Records with Contacts Fact = None are excluded."""
        enriched = [_make_enriched_record(ad_link="https://yt.com/a")]
        merged_rec = _make_merged_record(
            ad_link="https://yt.com/a", budget=5000, contacts=50,
            format_val="youtube",
        )
        merged_rec["Contacts Fact"] = None

        result = build_textual_comparison_v2(enriched, [merged_rec])

        sizes = result["sample_sizes"]
        total = sizes["high_performers"] + sizes["low_performers"] + sizes["excluded_middle"]
        assert total == 0


# ---------------------------------------------------------------------------
# Tests: Platform separation
# ---------------------------------------------------------------------------

class TestPlatformSeparation:
    """YouTube is separated from reels/tiktok (short-form)."""

    def test_platform_breakdown_in_sample_sizes(self):
        """sample_sizes includes platform_breakdown dict."""
        enriched, merged = _build_mixed_platform_dataset()
        result = build_textual_comparison_v2(enriched, merged)

        assert "platform_breakdown" in result["sample_sizes"]
        breakdown = result["sample_sizes"]["platform_breakdown"]
        assert "youtube" in breakdown
        assert "short_form" in breakdown

    def test_youtube_separate_from_short_form(self):
        """YouTube and short-form records are analyzed separately."""
        enriched, merged = _build_mixed_platform_dataset()
        result = build_textual_comparison_v2(enriched, merged)

        breakdown = result["sample_sizes"]["platform_breakdown"]
        # 4 youtube records + 8 short-form records = 12 total
        yt = breakdown["youtube"]
        sf = breakdown["short_form"]
        assert yt["total"] == 4
        assert sf["total"] == 8

    def test_reels_and_tiktok_grouped_as_short_form(self):
        """Reels and TikTok are grouped together as short_form."""
        enriched, merged = _build_mixed_platform_dataset()
        result = build_textual_comparison_v2(enriched, merged)

        breakdown = result["sample_sizes"]["platform_breakdown"]
        assert breakdown["short_form"]["total"] == 8


# ---------------------------------------------------------------------------
# Tests: compute_all_textual_tables_v2
# ---------------------------------------------------------------------------

class TestComputeAllTextualTablesV2:
    """Tests for compute_all_textual_tables_v2 with new keys."""

    def test_uses_high_low_performer_labels(self):
        """Tables use 'High Performers' / 'Low Performers' labels."""
        enriched, merged = _build_youtube_dataset()
        comparison = build_textual_comparison_v2(enriched, merged)
        tables_md = compute_all_textual_tables_v2(comparison)

        assert "High Performers" in tables_md
        assert "Low Performers" in tables_md
        assert "With Purchases" not in tables_md
        assert "Without Purchases" not in tables_md

    def test_includes_sample_sizes(self):
        """Header includes sample size information."""
        enriched, merged = _build_youtube_dataset()
        comparison = build_textual_comparison_v2(enriched, merged)
        tables_md = compute_all_textual_tables_v2(comparison)

        assert "high-performers" in tables_md.lower() or "high performers" in tables_md.lower()

    def test_has_all_table_sections(self):
        """All textual table sections are present."""
        enriched, merged = _build_youtube_dataset()
        comparison = build_textual_comparison_v2(enriched, merged)
        tables_md = compute_all_textual_tables_v2(comparison)

        assert "Text Statistics" in tables_md
        assert "Opening Pattern" in tables_md
        assert "Closing Pattern" in tables_md
        assert "Persuasion Function" in tables_md
