# AI Recruiter Platform Architecture

## Workflow
1. [Apify Scraper] -> Extracts job postings & company URLs.
2. [Sourcing Task] -> Pre-screening (Gemini 3.5 Flash). Drops scores < 80% (`FILTERED_OUT`).
3. [LangGraph Orchestrator] -> User triggers matching via WebSockets.
   - Parallel Execution Node A: Tailored CV Generation.
   - Parallel Execution Node B: Hunter.io Contact Search.
   - Final Node: Cover Letter Generation (personalized with recruiter name).
4. [Gmail Client] -> Converts Markdown CV to PDF, sends via REST API.

## Core Components
- Contact Sourcing: HunterClient uses Domain Search, strictly filtering for `personal` types and specific roles (CTO, HR, Manager, Lead).
- Email Delivery: GmailClient bypasses Cloud SMTP blocks using OAuth 2.0 (`credentials.json`/`token.json`).