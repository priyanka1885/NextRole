"""
utils.py — shared helpers for the NextRole golden-dataset pipeline.

Pure Python / regex / stdlib. No LLM calls, no network calls, no third-party
NLP dependencies (keeps the project's existing environment/dependencies
unchanged, per user instruction).
"""
import re
import unicodedata

# ---------------------------------------------------------------------------
# PII masking
# ---------------------------------------------------------------------------
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(
    r"(\(?\+?\d{1,3}\)?[\s.\-]?)?(\(?\d{3}\)?[\s.\-]?)\d{3}[\s.\-]?\d{4}\b"
)
STREET_ADDR_RE = re.compile(
    r"\d{1,6}\s+[A-Za-z0-9.\-'’]+(\s+[A-Za-z0-9.\-'’]+){0,4}\s+"
    r"(Street|St|Avenue|Ave|Drive|Dr|Road|Rd|Lane|Ln|Boulevard|Blvd|Court|Ct|Way|Place|Pl|Suite|Ste)\b\.?,?"
    r"(\s*[A-Za-z]+,\s*[A-Z]{2}\s*\d{5}(-\d{4})?)?",
    re.IGNORECASE,
)
# Standalone "City, ST 12345" pattern not already captured above
CITY_STATE_ZIP_RE = re.compile(r"\b[A-Za-z][A-Za-z\s]{1,30},\s*[A-Z]{2}\s*\d{5}(-\d{4})?\b")


def mask_pii(text: str) -> tuple[str, dict]:
    """Mask emails, phone numbers, and street addresses. Returns (masked_text, counts)."""
    counts = {"emails": 0, "phones": 0, "addresses": 0}

    def _email_sub(m):
        counts["emails"] += 1
        return "[EMAIL]"

    def _phone_sub(m):
        counts["phones"] += 1
        return "[PHONE]"

    def _addr_sub(m):
        counts["addresses"] += 1
        return "[ADDRESS]"

    text = EMAIL_RE.sub(_email_sub, text)
    text = PHONE_RE.sub(_phone_sub, text)
    text = STREET_ADDR_RE.sub(_addr_sub, text)
    text = CITY_STATE_ZIP_RE.sub(_addr_sub, text)
    return text, counts


# ---------------------------------------------------------------------------
# Text normalization (formatting cleanup; meaning-preserving)
# ---------------------------------------------------------------------------
_PUNCT_MAP = {
    "\u2018": "'", "\u2019": "'",       # smart single quotes
    "\u201c": '"', "\u201d": '"',       # smart double quotes
    "\u2013": "-", "\u2014": "-",       # en/em dash
    "\u00a0": " ",                       # non-breaking space
    "\u200b": "",                        # zero-width space
    "\u00ad": "",                        # soft hyphen
    "\uf0d8": "- ",                      # private-use bullet glyph (Wingdings-style)
}
_BULLET_CHARS = "•●◦▪➢❖·∙"


def clean_text(text: str) -> str:
    """Normalize formatting artifacts while preserving wording/meaning.

    - Replaces smart punctuation with plain ASCII equivalents.
    - Normalizes bullet glyphs to a plain "- " marker.
    - Collapses excess whitespace, preserves line breaks between sections.
    - Does NOT strip legitimate accented letters (names, loanwords) or
      reword/rephrase any content.
    """
    if text is None:
        return ""
    for src, dst in _PUNCT_MAP.items():
        text = text.replace(src, dst)
    for ch in _BULLET_CHARS:
        text = text.replace(ch, "-")
    # Normalize unicode to NFC (canonical composed form) without stripping accents
    text = unicodedata.normalize("NFC", text)
    # Collapse runs of spaces/tabs (but keep newlines as section separators)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Label normalization
# ---------------------------------------------------------------------------
VALID_LABELS = {"Good Fit", "Potential Fit", "No Fit"}


def normalize_label(label: str) -> str | None:
    if label is None:
        return None
    norm = label.strip()
    for v in VALID_LABELS:
        if norm.lower() == v.lower():
            return v
    return None  # unrecognized


# ---------------------------------------------------------------------------
# LLM review-decision handling (golden dataset, stage 06)
# ---------------------------------------------------------------------------
REVIEW_DECISIONS = {"Fit", "No Fit", "Exclude"}


_WORD_RE = re.compile(r"[a-z0-9]+")


def unsubstantiated_claims(claimed_skills: list[str], resume_text: str) -> list[str]:
    """Best-effort, non-LLM guardrail: flag any claimed "matching skill" that
    has literally zero word-level trace in the resume text. Deliberately
    loose (word-level, not phrase-level) so it only catches blatant
    fabrication, not minor paraphrasing -- used to enforce "never invent
    skills" as a checked rule, not just a prompt instruction, for any LLM-
    generated annotation stage (e.g. dataset/scripts/07_llm_semantic_pilot.py
    and its finalization step)."""
    resume_lower = resume_text.lower()
    flagged = []
    for skill in claimed_skills:
        words = [w for w in _WORD_RE.findall(skill.lower()) if len(w) > 2]
        if words and not any(w in resume_lower for w in words):
            flagged.append(skill)
    return flagged


def is_eval_eligible(review_decision) -> bool:
    """A golden-set record is eligible for automated evaluation-metric scoring
    unless an independent reviewer explicitly recorded `review_decision ==
    "Exclude"` (e.g. the job_description_text was too thin/unusable to judge).
    Blank/NaN (not yet reviewed, or reviewed as "Fit"/"No Fit") is eligible.
    """
    if review_decision is None:
        return True
    rd = str(review_decision).strip()
    return rd != "Exclude"


# ---------------------------------------------------------------------------
# Rule-based skill-candidate extraction (syntactic pattern matching, NOT
# semantic/meaning-based judgment — satisfies the "no LLM / no semantic
# annotation" constraint).
# ---------------------------------------------------------------------------
SECTION_HEADING_RE = re.compile(
    r"(requirements?|qualifications?|skills?|what you.?ll need|must have|you have)\s*:?",
    re.IGNORECASE,
)
TRIGGER_PHRASE_RE = re.compile(
    r"(?:experience (?:in|with)|knowledge of|proficien(?:cy|t) (?:in|with)|"
    r"familiarity with|skilled in|background in|ability to)\s+"
    r"([A-Za-z][A-Za-z0-9/+.#&\- ]{2,40}?)(?:[.,;\n]|$)",
    re.IGNORECASE,
)
CAPITALIZED_PHRASE_RE = re.compile(r"\b([A-Z][a-zA-Z+#]*(?:\s+[A-Z][a-zA-Z+#]*){1,2})\b")
SINGLE_WORD_CAP_RE = re.compile(r"\b([A-Z][a-zA-Z+#.]{2,})\b")

# US state postal abbreviations (+ DC). JD text frequently stacks office
# locations like "TX Irving, TX Fort Myers, FL" with no comma between the
# state code and the city name; CAPITALIZED_PHRASE_RE (any 2-3 consecutive
# Capitalized words) then grabs "TX Irving" as if it were a skill/tool name.
# Reject any candidate containing one of these as a standalone, all-caps token.
_US_STATE_ABBR = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL",
    "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT",
    "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
    "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
}

_GENERIC_STOP = {
    "the", "this", "that", "these", "those", "we", "you", "your", "our", "a", "an",
    "job", "description", "responsibilities", "role", "position", "company",
    "about", "overview", "summary", "team", "must", "please", "also", "work",
    "life", "part", "am", "pm", "for", "and", "or", "of", "in", "on", "at",
    "to", "with", "is", "are", "be", "will", "have", "has", "all", "any",
    "ours", "duration", "available", "professional", "remote", "months",
    "office", "only", "degree", "jones", "west", "coast", "metro", "paid",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
    # Boilerplate/structural JD words that commonly start a sentence but are
    # never themselves a skill/requirement:
    "who", "us", "offer", "offers", "looking", "seeking", "join",
    "apply", "little", "big", "equal", "opportunity", "employer", "benefits",
    "location", "hybrid", "onsite", "remote",
}
# Multi-word phrases are far less likely to be noise than single capitalized
# words, so the full-stoplist membership check below is only applied to
# single-token candidates. However, a multi-word phrase whose FIRST word is
# a generic/structural word (e.g. "The Business...", "Who We Are...") is
# almost always sentence-initial capitalization bleeding into the match, not
# a genuine proper-noun/skill phrase, so that narrower check applies to all
# candidates regardless of length.


def extract_skill_candidates(jd_text: str, max_candidates: int = 15) -> list[str]:
    """Extract candidate skill/requirement phrases from a job description using
    purely syntactic cues (trigger phrases + capitalized multi-word phrases +
    bullet-list lines under a requirements/skills heading). No external
    dictionary, no semantic model.
    """
    candidates: list[str] = []
    seen = set()

    def add(phrase: str):
        p = phrase.strip(" -.,;:|\n\t")
        p = re.sub(r"\s+", " ", p)
        if not (2 <= len(p) <= 40):
            return
        key = p.lower()
        if key in seen:
            return
        words = p.split()
        is_single_word = len(words) == 1
        if is_single_word and key in _GENERIC_STOP:
            return
        if not is_single_word and all(w.lower() in _GENERIC_STOP for w in words):
            return  # multi-word but every token is generic (e.g., "For The")
        if not is_single_word and words[0].lower() in _GENERIC_STOP:
            # Leading word is generic/structural -> sentence-initial
            # capitalization bleeding into the match, not a real phrase
            # (e.g. "The Business Analyst...", "Who We Are...").
            return
        if any(w in _US_STATE_ABBR for w in words):
            return  # office-location artifact (e.g. "TX Irving"), not a skill
        seen.add(key)
        candidates.append(p)

    # 1) Trigger-phrase extraction ("experience with X", "knowledge of Y", ...)
    for m in TRIGGER_PHRASE_RE.finditer(jd_text):
        for frag in re.split(r"[;,|]|\band\b", m.group(1)):
            add(frag)

    # 2) Bullet lines under a requirements/skills/qualifications heading.
    # Split each line on common field/item delimiters to avoid merging
    # multiple distinct items (e.g., template fields crammed onto one line)
    # into a single noisy candidate.
    lines = jd_text.split("\n")
    in_section = False
    for line in lines:
        stripped = line.strip(" -•\t")
        if SECTION_HEADING_RE.search(line) and len(line.strip()) < 60:
            in_section = True
            continue
        if in_section:
            if not stripped:
                continue
            if len(stripped) > 90:  # likely a prose sentence, not a short bullet skill
                in_section = False
                continue
            for frag in re.split(r"[;,|]", stripped):
                add(frag)

    # 3) Capitalized multi-word phrases (proper nouns / tool & product names) —
    # kept permissive, since 2-3 word capitalized phrases are rarely noise.
    for m in CAPITALIZED_PHRASE_RE.finditer(jd_text):
        add(m.group(1))

    # 4) Single capitalized words (e.g., "Python", "Excel", "Salesforce") —
    # filtered against the stoplist in add() to drop generic sentence-starters.
    for m in SINGLE_WORD_CAP_RE.finditer(jd_text):
        add(m.group(1))

    return candidates[:max_candidates]


_MATCH_NORMALIZE_RE = re.compile(r"[^a-z0-9+#./ ]")


def _normalize_for_match(text: str) -> str:
    """Lowercase + collapse punctuation/whitespace variants (e.g. "Node.js" vs
    "Node JS", "C#" vs "C #") so substring matching isn't defeated by purely
    cosmetic formatting differences between the JD candidate phrase and how
    the same term happens to be written in the resume."""
    text = text.lower()
    text = _MATCH_NORMALIZE_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def split_matching_missing(candidates: list[str], resume_text: str) -> tuple[list[str], list[str]]:
    """Case/punctuation-insensitive substring match of each candidate skill
    phrase against resume text (see `_normalize_for_match`)."""
    resume_norm = _normalize_for_match(resume_text)
    matching, missing = [], []
    for c in candidates:
        c_norm = _normalize_for_match(c)
        if c_norm and c_norm in resume_norm:
            matching.append(c)
        else:
            missing.append(c)
    return matching, missing


# ---------------------------------------------------------------------------
# Experience-years extraction (regex-based, numeric comparison only)
# ---------------------------------------------------------------------------
# Prefer a years-requirement that is explicitly tied to the word "experience"
# (in either word order: "5+ years of experience" or "experience of 5+
# years") over a bare "N years" match anywhere in the JD. The bare pattern
# below is kept only as a last-resort fallback, since it can otherwise grab
# an unrelated number (e.g. a visa/warranty/contract duration) that happens
# to be followed by the word "years" with no connection to the role's actual
# experience requirement.
JD_YEARS_EXPERIENCE_FORWARD_RE = re.compile(
    r"(\d{1,2})\+?\s*(?:-\s*\d{1,2}\+?\s*)?years?\s*(?:of\s+)?"
    r"(?:relevant\s+|related\s+|professional\s+|working\s+|hands[- ]on\s+)?experience",
    re.IGNORECASE,
)
JD_YEARS_EXPERIENCE_REVERSE_RE = re.compile(
    r"experience\w*\s*(?:of|:)?\s*(\d{1,2})\+?\s*years?",
    re.IGNORECASE,
)
JD_YEARS_RE = re.compile(r"(\d{1,2})\s*\+?\s*(?:-|to)?\s*(\d{0,2})?\s*\+?\s*years?", re.IGNORECASE)
DATE_RANGE_RE = re.compile(r"\b(19|20)\d{2}\b")


def extract_required_years(jd_text: str) -> int | None:
    for pattern in (JD_YEARS_EXPERIENCE_FORWARD_RE, JD_YEARS_EXPERIENCE_REVERSE_RE, JD_YEARS_RE):
        m = pattern.search(jd_text)
        if m:
            try:
                return int(m.group(1))
            except (TypeError, ValueError):
                continue
    return None


def estimate_resume_years(resume_text: str) -> int | None:
    """Rough span estimate: max(year) - min(year) found in the resume's date mentions.
    Purely numeric/mechanical; intentionally conservative (returns None, not a guess,
    when fewer than two distinct years are found).
    """
    all_years = sorted({int(m.group(0)) for m in DATE_RANGE_RE.finditer(resume_text)})
    if len(all_years) < 2:
        return None
    span = all_years[-1] - all_years[0]
    if span <= 0 or span > 50:
        return None
    return span


def compute_experience_match(jd_text: str, resume_text: str) -> str:
    required = extract_required_years(jd_text)
    if required is None:
        return "not_specified"
    estimated = estimate_resume_years(resume_text)
    if estimated is None:
        return "needs_review"
    if estimated >= required:
        return "meets"
    if estimated >= max(required - 1, 0):
        return "close"  # within 1 year, borderline
    return "below"


# ---------------------------------------------------------------------------
# Education-level extraction (regex keyword hierarchy, numeric comparison only)
# ---------------------------------------------------------------------------
_EDU_LEVELS = [
    ("phd", 5, r"\b(ph\.?d\.?|doctorate|doctoral degree)\b"),
    # NOTE: the previous abbreviation patterns here (`m\.?[a-z]\.?[a-z]?\.?`,
    # `b\.?[a-z]\.?[a-z]?\.?`) were far too permissive -- with 0-2 optional
    # single letters and all periods optional, they matched ANY two-letter
    # word starting with "m"/"b" (e.g. plain "my", "me", "by", "be"), so
    # ordinary JD/resume prose was constantly mis-detected as holding/
    # requiring a Master's or Bachelor's degree. Replaced with an explicit
    # list of known credential abbreviations only.
    ("master", 4, r"\b(master'?s(?:\s+degree)?|m\.?b\.?a\.?|m\.?s\.?c?\.?|m\.?a\.?|m\.?eng\.?|m\.?tech\.?)\b"),
    ("bachelor", 3, r"\b(bachelor'?s(?:\s+degree)?|b\.?b\.?a\.?|b\.?s\.?c?\.?|b\.?a\.?|b\.?eng\.?|b\.?tech\.?)\b"),
    ("associate", 2, r"\b(associate'?s(?:\s+degree)?|a\.?a\.?s?\.?)\b"),
    ("high_school", 1, r"\b(high school diploma|ged)\b"),
]
_EDU_PATTERNS = [(name, lvl, re.compile(pat, re.IGNORECASE)) for name, lvl, pat in _EDU_LEVELS]


def _highest_edu_level(text: str) -> tuple[str, int] | None:
    best = None
    for name, lvl, pat in _EDU_PATTERNS:
        if pat.search(text):
            if best is None or lvl > best[1]:
                best = (name, lvl)
    return best


def compute_education_match(jd_text: str, resume_text: str) -> str:
    required = _highest_edu_level(jd_text)
    if required is None:
        return "not_specified"
    held = _highest_edu_level(resume_text)
    if held is None:
        return "needs_review"
    if held[1] >= required[1]:
        return "meets"
    return "below"
