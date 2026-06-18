import asyncio
import sys
from datetime import date

# The Windows console defaults to cp1252, which can't encode the ✅ emoji below.
# Force UTF-8 on stdout so the success message never crashes the script.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.db.database import AsyncSessionLocal
from app.repositories.profile_repository import ProfileRepository
from app.models.schemas.profile import (
    ProfileCreate, ExperienceCreate, SkillCreate
)

async def seed_db():
    async with AsyncSessionLocal() as session:
        repo = ProfileRepository(session)
        
        new_profile = ProfileCreate(
            candidate_name="EVGENIY BERKHIN", #[cite: 1]
            target_titles=[
                "Full Stack Engineer", 
                "Senior Software Engineer", 
                "AI Engineer", 
                "Frontend Engineer"
            ], #[cite: 1]
            preferences={
                "location": "Tel Aviv", #[cite: 1]
                "phone": "053-8926314", #[cite: 1]
                "email": "berkhindev@gmail.com", #[cite: 1]
                "linkedin": "https://www.linkedin.com/in/evgeniy-berkhin" #[cite: 1]
            },
            experiences=[
                ExperienceCreate(
                    company="Siemens, Israel", #[cite: 1]
                    role="Al & Full Stack Engineer", #[cite: 1]
                    start_date=date(2024, 1, 1), #[cite: 1]
                    end_date=None, # Present[cite: 1]
                    highlights=[
                        "Working on the Frontend of a large PLM platform, focusing on architecture, performance, reliability.", #[cite: 1]
                        "Designed a modular React + TypeScript architecture with minimal coupling and defined public type contracts for predictable data flow.", #[cite: 1]
                        "Built a Cypress-based E2E testing framework integrated with GitLab Cl, including automated reports, flaky test detection, and execution metrics.", #[cite: 1]
                        "Implemented AuthO + Siemens ID (OIDC) login/logout flows and resolved multi-environment consistency issues.", #[cite: 1]
                        "Integrated GitLab Flow pipelines with SOPS for secure secrets management.", #[cite: 1]
                        "Implemented a code-first OpenAPI workflow for Python Azure Functions using annotation-driven spec generation, pre-commit validation, and reusable Bicep modules.", #[cite: 1]
                        "Standardized Azure API Management deployment across 4 repositories and about 20 APIs." #[cite: 1]
                    ]
                ),
                ExperienceCreate(
                    company="Independent Product Hypothesis Test", #[cite: 1]
                    role="Al-Driven Arbitrage & Smart-Search MVP", #[cite: 1]
                    start_date=date(2026, 1, 1), #[cite: 1]
                    end_date=None, # Present[cite: 1]
                    highlights=[
                        "Designed and launched a fully automated Telegram-based MVP to test the hypothesis that LLM orchestration can replace manual secondary market discovery.", #[cite: 1]
                        "Engineered an asynchronous Python pipeline integrating three specialized LLMs for intent analysis, listing validation, and expert financial analysis.", #[cite: 1]
                        "Architected the data processing pipeline using LangGraph and designed a highly scalable worker distribution system for Al requests with concurrent request deduplication.", #[cite: 1]
                        "Integrated one-hour cycle web scraping mechanisms with the LLM pipeline, fully automating the product discovery and risk evaluation funnel." #[cite: 1]
                    ]
                ),
                ExperienceCreate(
                    company="Shield, Ramat Gan, Israel", #[cite: 1]
                    role="Frontend Engineer", #[cite: 1]
                    start_date=date(2022, 1, 1), #[cite: 1]
                    end_date=date(2024, 1, 1), #[cite: 1]
                    highlights=[
                        "Developed reusable interface components and complex domain features in a compliance monitoring platform.", #[cite: 1]
                        "Built reusable React + TypeScript Ul components, including generic tables, modals, filters, and custom buttons, and delivered new pages, admin-panel features, and chat-related functionality.", #[cite: 1]
                        "Integrated frontend features with backend APIs for admin functions, role and permission management, status updates, and card operations.", #[cite: 1]
                        "Performed pre-release regression testing and API validation for business-critical search, filtering, alerts, cases, admin, and reporting flows.", #[cite: 1]
                        "Investigated production issues affecting customer-facing functionality, using browser DevTools, logs, and Postman to troubleshoot UI, API, integration, and role/permission defects." #[cite: 1]
                    ]
                ),
                ExperienceCreate(
                    company="Peleng, Minsk, Belarus", #[cite: 1]
                    role="Frontend Engineer", #[cite: 1]
                    start_date=date(2017, 1, 1), #[cite: 1]
                    end_date=date(2022, 1, 1), #[cite: 1]
                    highlights=[
                        "End-to-end development of a recruitment portal: UI, authorization, resume builder, search, and filters.", #[cite: 1]
                        "Developed React and JavaScript frontend features for a recruitment platform, including authorization flows, resume builder functionality, search, filtering, and account-related workflows.", #[cite: 1]
                        "Built user-facing and admin-facing frontend modules for messaging, content management, and user settings.", #[cite: 1]
                        "Built internal web interfaces for HR, training, and performance management workflows.", #[cite: 1]
                        "Integrated frontend applications with Moodle and internal authentication services." #[cite: 1]
                    ]
                )
            ],
            skills=[
                SkillCreate(
                    category="Languages", 
                    skills=["Hebrew", "English", "Russian"] #[cite: 1]
                ),
                SkillCreate(
                    category="Frontend", 
                    skills=["React", "TypeScript", "JavaScript", "Zustand", "Redux Toolkit", "Redux", "Angular", "NgRx", "RxJS", "HTML5", "CSS3", "CSS Modules", "Frontend Architecture", "Component-Based UI Architecture"] #[cite: 1]
                ),
                SkillCreate(
                    category="Testing & Quality", 
                    skills=["Cypress", "End-to-End Testing", "Regression Testing", "API Validation", "REST API Integration", "Postman", "Production Troubleshooting"] #[cite: 1]
                ),
                SkillCreate(
                    category="CI/CD/DevOps / Cloud", 
                    skills=["GitLab CI/CD", "Continuous Integration", "Git", "Vite", "Developer Experience", "SOPS", "Azure", "OpenAPI", "Bicep", "API Management (APIM)", "Pre-commit Validation"] #[cite: 1]
                ),
                SkillCreate(
                    category="Authentication / Backend / Additional", 
                    skills=["Authentication", "Auth0 Integration", "OIDC", "Python", "Python Async", "Azure Functions", "Node.js", "LangGraph", "LLM Agentic Workflows", "LangSmith", "Prisma"] #[cite: 1]
                )
            ]
        )
        
        created = await repo.create_full_profile(new_profile)
        # The repository only flushes; commit the unit of work here.
        await session.commit()
        print(f"✅ Профиль успешно создан! ID: {created.id}")

if __name__ == "__main__":
    asyncio.run(seed_db())