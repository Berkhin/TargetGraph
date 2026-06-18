"""Test the FastAPI job matching endpoint.

Assumes the FastAPI server is running on http://localhost:8000.
"""

import asyncio
import httpx
import sys
from uuid import UUID
from sqlalchemy import select
from app.db.database import AsyncSessionLocal
from app.models.sql.profile import MasterProfile
from app.repositories.job_repository import JobRepository
from app.models.schemas.job import JobCreate, JobStatus


async def test_match_endpoint():
    """Test the POST /jobs/{job_id}/match endpoint."""

    # Get profile from database
    async with AsyncSessionLocal() as session:
        print("[1] Getting profile from database...")
        result = await session.execute(select(MasterProfile).limit(1))
        profile_record = result.scalar_one_or_none()

        if not profile_record:
            print("ERROR: Profile not found. Run scripts/seed_profile.py first")
            return False

        profile_id = profile_record.id
        print(f"OK: Profile ID: {profile_id}")

        # Create test job
        print("\n[2] Creating test job posting...")
        job_repo = JobRepository(session)
        test_job = JobCreate(
            company_name="TechCorp Inc",
            job_title="Full Stack Engineer",
            description="""
            Looking for a Full Stack Engineer with experience in React, TypeScript, Python, and SQL.
            You should have hands-on experience with modern cloud platforms (Azure, AWS).
            Knowledge of GraphQL and REST APIs is required.
            """,
            source_url="https://example.com/job/techcorp",
            status=JobStatus.NEW
        )
        created_job = await job_repo.create(test_job)
        await session.commit()
        job_id = created_job.id
        print(f"OK: Job created (ID: {job_id})")

    # Test the endpoint
    print("\n[3] Testing FastAPI endpoint POST /jobs/{job_id}/match...")
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            url = f"http://localhost:8000/api/v1/jobs/{job_id}/match"
            params = {"profile_id": str(profile_id)}

            print(f"Sending request to {url}?profile_id={profile_id}")
            response = await client.post(url, params=params)

            if response.status_code == 200:
                print(f"OK: Status code 200")
                data = response.json()
                print(f"  - Job ID: {data.get('id')}")
                print(f"  - Status: {data.get('status')}")
                print(f"  - Match Score: {data.get('match_score')}")
                print(f"  - Cover Letter length: {len(data.get('cover_letter_draft', ''))}")
                return True
            else:
                print(f"ERROR: Status code {response.status_code}")
                print(f"Response: {response.text}")
                return False
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    try:
        success = asyncio.run(test_match_endpoint())
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
