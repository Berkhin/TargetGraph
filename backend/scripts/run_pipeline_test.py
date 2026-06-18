import asyncio
from sqlalchemy import select
from app.db.database import AsyncSessionLocal
from app.models.sql.profile import MasterProfile
from app.repositories.job_repository import JobRepository
from app.models.schemas.job import JobCreate, JobStatus
from app.services.orchestrator import run_pipeline

async def run_full_integration_test():
    async with AsyncSessionLocal() as session:
        print("[1] Finding profile in database...")
        result = await session.execute(select(MasterProfile).limit(1))
        profile_record = result.scalar_one_or_none()

        if not profile_record:
            print("ERROR: Profile not found. Run scripts/seed_profile.py first")
            return

        print(f"OK: Profile found: {profile_record.candidate_name} (ID: {profile_record.id})")

        print("\n[2] Creating test job posting...")
        job_repo = JobRepository(session)
        test_job = JobCreate(
            company_name="TechNova Core",
            job_title="Senior AI/Frontend Engineer",
            description="""
            We are looking for a Senior Engineer to bridge the gap between AI and UI.
            You must have strong experience with React, TypeScript, and modern UI architectures.
            On the backend, you will design autonomous LLM workflows using Python and LangGraph.
            Experience with GitLab CI, Cypress, and Azure is highly desirable.
            """,
            source_url="https://example.com/job/technova",
            status=JobStatus.NEW
        )
        created_job = await job_repo.create(test_job)
        await session.commit()
        print(f"OK: Job created (ID: {created_job.id})")

        print("\n[3] Running AI Pipeline (Service Layer -> LangGraph)...")
        print("Waiting for generation and review (this may take 10-30 seconds)...\n")
        try:
            final_state = await run_pipeline(
                job_id=created_job.id,
                profile_id=profile_record.id,
                session=session,
                save_results=False  # Will save manually below for testing
            )

            # Manual save for testing
            job_repo = JobRepository(session)
            match_score = final_state.get("match_score", 0)
            cover_letter = final_state.get("cover_letter_draft", "")
            status = JobStatus.MATCHED if match_score >= 70 else JobStatus.REJECTED_BY_AI
            await job_repo.save_match_results(created_job.id, match_score, cover_letter, status)
            await session.commit()

            print("\nPipeline completed successfully!")
            print("="*60)

            score = final_state.get("match_score")
            reasoning = final_state.get("match_reasoning", "No reasoning provided")
            cover_letter = final_state.get("cover_letter_draft", "No cover letter generated.")
            revisions = final_state.get("revision_number", 0)
            comments = final_state.get("review_comments", [])

            print(f"Match Score: {score}/100")
            print(f"Reasoning:\n{reasoning}\n")

            print("-" * 60)
            print(f"Review iterations: {revisions}")

            if comments:
                print("Reviewer comments:")
                for c in comments:
                    print(f"  - {c}")
            else:
                print("Reviewer approved without comments.")

            print("-" * 60)
            print("GENERATED COVER LETTER:\n")
            print(cover_letter)
            print("\n" + "="*60)

            print("\n[4] Verifying saved results in database...")
            updated_job = await job_repo.get_by_id(created_job.id)
            if updated_job:
                print(f"Job status: {updated_job.status}")
                print(f"Match score saved: {updated_job.match_score}")
                print(f"Cover letter saved: {len(updated_job.cover_letter_draft or '')} characters")
            else:
                print("ERROR: Job not found after pipeline execution")

        except Exception as e:
            print(f"\nERROR during pipeline execution: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(run_full_integration_test())