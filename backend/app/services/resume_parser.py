"""Resume PDF parser using LLM for structured extraction.

Extracts text from a PDF resume and uses Gemini with structured output
to parse candidate name, experiences, skills, and target job titles.
"""

from __future__ import annotations

import datetime
import io
import logging
from typing import Any

import pdfplumber
from pydantic import BaseModel, Field

from app.ai.llm import get_llm
from app.core.config import AISettings
from app.models.schemas.profile import (
    ExperienceCreate,
    ProfileCreate,
    SkillCreate,
)

logger = logging.getLogger(__name__)


class ParsedExperience(BaseModel):
    """Extracted work experience from resume."""

    company: str = Field(description="Company name")
    role: str = Field(description="Job title/role")
    start_date: datetime.date = Field(description="Start date (YYYY-MM-DD)")
    end_date: datetime.date | None = Field(
        default=None, description="End date (YYYY-MM-DD), null if current"
    )
    highlights: list[str] = Field(
        default_factory=list, description="Key achievements or responsibilities"
    )


class ParsedSkill(BaseModel):
    """Extracted skill group from resume."""

    category: str = Field(description="Skill category (e.g., 'Languages', 'Tools')")
    skills: list[str] = Field(description="List of skills in this category")


class ParsedResume(BaseModel):
    """Structured resume data extracted by LLM."""

    candidate_name: str = Field(description="Full name of the candidate")
    target_titles: list[str] = Field(
        description="Target job titles the candidate is interested in"
    )
    experiences: list[ParsedExperience] = Field(
        default_factory=list, description="Work history"
    )
    skills: list[ParsedSkill] = Field(
        default_factory=list, description="Skills grouped by category"
    )


async def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extract plain text from a PDF file.

    Uses pdfplumber to parse all pages and concatenate text.
    Wraps I/O in asyncio.to_thread since pdfplumber is synchronous.
    """
    import asyncio

    def _extract() -> str:
        try:
            pdf_file = io.BytesIO(pdf_bytes)
            text_parts: list[str] = []
            with pdfplumber.open(pdf_file) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
            return "\n\n".join(text_parts)
        except Exception as e:
            logger.error("Failed to extract text from PDF", extra={"error": str(e)})
            return ""

    return await asyncio.to_thread(_extract)


async def parse_resume_with_llm(
    resume_text: str,
) -> ParsedResume | None:
    """Parse resume text into structured data using Gemini LLM.

    Uses langchain_google_genai with .with_structured_output() to force
    a ParsedResume schema. Wraps LLM call in asyncio.to_thread for consistency.
    """
    import asyncio

    if not resume_text or not resume_text.strip():
        logger.warning("Resume text is empty, cannot parse")
        return None

    def _parse() -> ParsedResume | None:
        try:
            model = get_llm()
            structured_model = model.with_structured_output(ParsedResume)
            prompt = f"""Parse the following resume and extract structured information.
Focus on:
- Candidate's full name
- Target job titles (infer from resume summary, experience, or skills if not explicit)
- Work experience (company, role, dates, key achievements)
- Skills grouped by category

Resume text:
{resume_text}

Extract all information carefully. For dates, use YYYY-MM-DD format.
If end_date is not specified or current, set to null."""

            result = structured_model.invoke(prompt)
            return result
        except Exception as e:
            logger.error(
                "LLM parsing failed",
                extra={"error": str(e)},
            )
            return None

    return await asyncio.to_thread(_parse)


async def create_profile_from_resume(
    pdf_bytes: bytes,
) -> ProfileCreate | None:
    """End-to-end: extract PDF → parse with LLM → create ProfileCreate DTO.

    Returns None if extraction or parsing fails (fail-soft).
    """
    try:
        # Extract text from PDF
        resume_text = await extract_text_from_pdf(pdf_bytes)
        if not resume_text:
            logger.warning("Could not extract text from PDF")
            return None

        # Parse with LLM
        parsed = await parse_resume_with_llm(resume_text)
        if parsed is None:
            logger.warning("LLM parsing returned None")
            return None

        # Convert to ProfileCreate DTO
        experiences = [
            ExperienceCreate(
                company=exp.company,
                role=exp.role,
                start_date=exp.start_date,
                end_date=exp.end_date,
                highlights=exp.highlights,
            )
            for exp in parsed.experiences
        ]

        skills = [
            SkillCreate(category=skill.category, skills=skill.skills)
            for skill in parsed.skills
        ]

        profile = ProfileCreate(
            candidate_name=parsed.candidate_name,
            target_titles=parsed.target_titles,
            preferences={},
            experiences=experiences,
            skills=skills,
        )

        logger.info(
            "resume_parsed_successfully",
            extra={"candidate_name": parsed.candidate_name},
        )
        return profile

    except Exception as e:
        logger.error(
            "create_profile_from_resume failed",
            extra={"error": str(e)},
        )
        return None
