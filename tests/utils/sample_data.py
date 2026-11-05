"""Shared fixture-style sample data for agent/pipeline/e2e tests."""
from __future__ import annotations

from backend.models.schemas import (
    InterviewPrepDraft,
    JDExtraction,
    QA,
    ResumeData,
    TailoredResumeDraft,
)

SAMPLE_RESUME_TEXT = """\
Jane Candidate
jane.candidate@example.com

Summary
Experienced software engineer with 5 years of experience building web applications.

Experience
Senior Software Engineer at Acme Corp from 2019 to 2024.
Built and maintained REST APIs using Python and Django.
Led a team of 3 engineers to deliver a payments platform.

Education
Bachelor of Science in Computer Science, State University, 2015.

Skills
Python, Django, SQL, REST APIs, Git
"""

SAMPLE_JD_TEXT = (
    "We are hiring a Senior Software Engineer with experience in Python, Django, "
    "and REST APIs. The candidate will lead a small team and build scalable web "
    "applications. 5+ years of experience required. Preferred: AWS experience."
)


def sample_resume_data() -> ResumeData:
    from backend.services.resume_parser import split_into_sections

    return ResumeData(sections=split_into_sections(SAMPLE_RESUME_TEXT), raw_text=SAMPLE_RESUME_TEXT)


def clean_jd_extraction() -> JDExtraction:
    return JDExtraction(
        required_skills=["Python", "Django", "REST APIs"],
        responsibilities=["lead a small team", "build scalable web applications"],
        experience_requirements=["5+ years of experience"],
        keywords=["Python", "Django", "REST APIs", "scalable web applications"],
        preferred_qualifications=["AWS experience"],
    )


def clean_tailored_draft() -> TailoredResumeDraft:
    return TailoredResumeDraft(
        sections={
            "summary": [
                "Experienced software engineer with 5 years of experience building "
                "web applications using Python and Django.",
            ],
            "experience": [
                "Senior Software Engineer at Acme Corp (2019 to 2024): built and "
                "maintained REST APIs using Python and Django.",
                "Led a team of 3 engineers to deliver a payments platform.",
            ],
            "education": [
                "Bachelor of Science in Computer Science, State University, 2015.",
            ],
            "skills": [
                "Python, Django, SQL, REST APIs, Git",
            ],
        }
    )


def fabricated_tailored_draft() -> TailoredResumeDraft:
    """A draft containing fabricated, non-traceable content (for guardrail tests)."""
    return TailoredResumeDraft(
        sections={
            "summary": [
                "Experienced software engineer with 5 years of experience building "
                "web applications using Python and Django.",
            ],
            "experience": [
                "Senior Software Engineer at Acme Corp (2019 to 2024): built and "
                "maintained REST APIs using Python and Django.",
                "Increased company revenue by 200% through blockchain innovations.",
            ],
        }
    )


def clean_interview_prep_draft() -> InterviewPrepDraft:
    return InterviewPrepDraft(
        self_introduction=(
            "I am a software engineer with 5 years of experience building web "
            "applications using Python and Django."
        ),
        technical_questions=[
            QA(
                question="Tell me about a REST API you built.",
                star_answer=(
                    "At Acme Corp I built and maintained REST APIs using Python "
                    "and Django as part of a payments platform."
                ),
            )
        ],
        hr_questions=[
            QA(
                question="Tell me about a time you led a team.",
                star_answer="I led a team of 3 engineers at Acme Corp to deliver a payments platform.",
            )
        ],
        project_questions=[
            QA(
                question="Describe the payments platform project.",
                star_answer=(
                    "At Acme Corp, I led a team of 3 engineers to deliver a payments "
                    "platform using Python and Django."
                ),
            )
        ],
    )
