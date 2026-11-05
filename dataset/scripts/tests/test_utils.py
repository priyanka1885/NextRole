"""Unit tests for dataset/scripts/utils.py — pure functions, no I/O."""
import pytest

from utils import (
    VALID_LABELS,
    normalize_label,
    clean_text,
    mask_pii,
    extract_skill_candidates,
    split_matching_missing,
    compute_experience_match,
    compute_education_match,
    is_eval_eligible,
    extract_required_years,
)


# ---------------------------------------------------------------------------
# normalize_label — issue #1: must recognize exactly Good Fit / Potential Fit / No Fit
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [
    ("Good Fit", "Good Fit"),
    ("good fit", "Good Fit"),
    ("  GOOD FIT  ", "Good Fit"),
    ("Potential Fit", "Potential Fit"),
    ("potential fit", "Potential Fit"),
    ("No Fit", "No Fit"),
    ("no fit", "No Fit"),
    (" No Fit ", "No Fit"),
])
def test_normalize_label_recognizes_all_three_classes(raw, expected):
    assert normalize_label(raw) == expected


@pytest.mark.parametrize("raw", ["0", "1", "fit", "no_fit", "Maybe Fit", "", "Excellent Fit", None])
def test_normalize_label_rejects_everything_else(raw):
    assert normalize_label(raw) is None


def test_valid_labels_is_exactly_the_three_class_set():
    assert VALID_LABELS == {"Good Fit", "Potential Fit", "No Fit"}


# ---------------------------------------------------------------------------
# PII masking
# ---------------------------------------------------------------------------
def test_mask_pii_masks_email():
    text, counts = mask_pii("Contact me at jane.doe@example.com for details.")
    assert "[EMAIL]" in text
    assert "jane.doe@example.com" not in text
    assert counts["emails"] == 1


def test_mask_pii_masks_phone():
    text, counts = mask_pii("Call 555-123-4567 anytime.")
    assert "[PHONE]" in text
    assert counts["phones"] == 1


def test_mask_pii_masks_street_address():
    text, counts = mask_pii("I live at 123 Main Street, Springfield, IL 62704.")
    assert "[ADDRESS]" in text
    assert counts["addresses"] >= 1


def test_mask_pii_leaves_clean_text_untouched():
    text, counts = mask_pii("Experienced Python developer with 5 years of experience.")
    assert text == "Experienced Python developer with 5 years of experience."
    assert counts == {"emails": 0, "phones": 0, "addresses": 0}


# ---------------------------------------------------------------------------
# Text cleaning
# ---------------------------------------------------------------------------
def test_clean_text_normalizes_smart_quotes_and_bullets():
    raw = "\u2018Hello\u2019 \u2013 \u2022 bullet item"
    out = clean_text(raw)
    assert "\u2018" not in out and "\u2019" not in out
    assert "'Hello'" in out
    assert "\u2022" not in out


def test_clean_text_collapses_whitespace_but_keeps_newlines():
    out = clean_text("Line one.\n\n\n\nLine two.   has   spaces")
    assert "\n\n\n" not in out
    assert "has   spaces" not in out  # collapsed to single spaces
    assert "has spaces" in out


def test_clean_text_handles_none():
    assert clean_text(None) == ""


# ---------------------------------------------------------------------------
# Skill-candidate extraction (syntactic, no semantic model)
# ---------------------------------------------------------------------------
def test_extract_skill_candidates_finds_trigger_phrase():
    jd = "We require experience with Python and knowledge of SQL databases."
    candidates = extract_skill_candidates(jd)
    assert any("python" in c.lower() for c in candidates)


def test_split_matching_missing_is_case_insensitive_substring_match():
    candidates = ["Python", "Kubernetes"]
    resume = "Five years of python development experience."
    matching, missing = split_matching_missing(candidates, resume)
    assert matching == ["Python"]
    assert missing == ["Kubernetes"]


# ---------------------------------------------------------------------------
# Experience / education heuristics
# ---------------------------------------------------------------------------
def test_compute_experience_match_not_specified_when_jd_has_no_years():
    assert compute_experience_match("Great company, great people.", "2015 2020") == "not_specified"


def test_compute_experience_match_needs_review_when_resume_has_insufficient_dates():
    assert compute_experience_match("5+ years required", "no dates here") == "needs_review"


def test_compute_experience_match_meets_when_span_covers_requirement():
    jd = "Requires 3+ years of experience."
    resume = "Worked from 2015 to 2020 as an engineer."
    assert compute_experience_match(jd, resume) == "meets"


def test_compute_education_match_not_specified_when_jd_silent():
    assert compute_education_match("No degree mentioned.", "Bachelor's in CS") == "not_specified"


def test_compute_education_match_meets_when_resume_exceeds_requirement():
    jd = "Bachelor's degree required."
    resume = "Master's degree in Computer Science."
    assert compute_education_match(jd, resume) == "meets"


def test_compute_education_match_below_when_resume_under_requirement():
    jd = "Master's degree required."
    resume = "Bachelor's degree in Computer Science."
    assert compute_education_match(jd, resume) == "below"


# ---------------------------------------------------------------------------
# Evaluation eligibility (issue #6)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("review_decision,expected", [
    ("", True),
    (None, True),
    ("Fit", True),
    ("No Fit", True),
    ("Exclude", False),
])
def test_is_eval_eligible(review_decision, expected):
    assert is_eval_eligible(review_decision) is expected


# ---------------------------------------------------------------------------
# Regression tests for the 03_annotate.py / utils.py annotation-accuracy fixes
# ---------------------------------------------------------------------------
from utils import _highest_edu_level  # noqa: E402  (private helper, test-only import)


@pytest.mark.parametrize("text", [
    "I was hired by the company and my manager said to be ready.",
    "to be or not to be, that is the question",
])
def test_highest_edu_level_no_longer_false_matches_common_words(text):
    """Regression test: the old abbreviation regexes (`b\\.?[a-z]\\.?[a-z]?\\.?`,
    `m\\.?[a-z]\\.?[a-z]?\\.?`) matched ANY two-letter word starting with b/m
    (e.g. "by", "my"), so ordinary prose was misdetected as a Bachelor's/
    Master's credential."""
    assert _highest_edu_level(text) is None


@pytest.mark.parametrize("text,expected_level", [
    ("Candidate holds a BS in Computer Science", "bachelor"),
    ("Candidate holds a B.S. in Computer Science", "bachelor"),
    ("Bachelor's degree required", "bachelor"),
    ("Earned an MBA from State University", "master"),
    ("Master's degree preferred", "master"),
    ("PhD in Physics required", "phd"),
])
def test_highest_edu_level_still_matches_real_credentials(text, expected_level):
    result = _highest_edu_level(text)
    assert result is not None
    assert result[0] == expected_level


def test_extract_required_years_ties_to_experience_context():
    """Regression test: the old bare 'N years' regex could grab an unrelated
    number (visa/warranty/tenure duration) with no connection to the actual
    experience requirement. Forward and reverse 'years ... experience'
    phrasing must be preferred when present."""
    assert extract_required_years("We require 5+ years of professional experience in Java.") == 5
    assert extract_required_years("Candidates need experience of at least 7 years in sales.") == 7


def test_extract_skill_candidates_rejects_state_abbreviation_location_noise():
    """Regression test: JD office-location lists like 'TX Irving, TX Fort
    Myers, FL' used to be captured as if they were skill/tool names."""
    jd = "Our offices: TX Irving, TX Fort Myers, FL. Must know Python and SQL."
    candidates = extract_skill_candidates(jd)
    assert not any("TX" in c.split() for c in candidates)
    assert any(c.lower() == "python" for c in candidates)


def test_extract_skill_candidates_rejects_generic_leading_word():
    """Regression test: sentence-initial capitalization (e.g. 'The Business
    Analyst role...', 'Who We Are...') used to be captured as a multi-word
    skill phrase just because every word happened to be capitalized."""
    jd = "Who We Are: About Us. The Business Analyst role requires Python."
    candidates = [c.lower() for c in extract_skill_candidates(jd)]
    assert "who we are" not in candidates
    assert "about us" not in candidates
    assert "the business analyst" not in candidates


def test_split_matching_missing_handles_hyphen_variants():
    """Regression test: 'Full-Stack' (candidate) vs 'full stack' (resume) is
    the same term, just tokenized differently; plain substring matching
    missed this before the punctuation-normalizing match."""
    matching, missing = split_matching_missing(
        ["Full-Stack", "hands-on testing"],
        "Experienced full stack developer with hands on testing background.",
    )
    assert matching == ["Full-Stack", "hands-on testing"]
    assert missing == []
