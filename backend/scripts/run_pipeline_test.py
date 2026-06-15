import asyncio
from sqlalchemy import select
from app.db.database import AsyncSessionLocal
from app.models.sql.profile import MasterProfile
from app.repositories.job_repository import JobRepository
from app.models.schemas.job import JobCreate, JobStatus
from app.services.orchestrator import run_pipeline

async def run_full_integration_test():
    async with AsyncSessionLocal() as session:
        print("🔍 Шаг 1: Поиск профиля в базе данных...")
        # Достаем первый попавшийся профиль (наш засидированный Master Profile)
        result = await session.execute(select(MasterProfile).limit(1))
        profile_record = result.scalar_one_or_none()
        
        if not profile_record:
            print("❌ Профиль не найден. Запусти сначала scripts/seed_profile.py")
            return
            
        print(f"✅ Профиль найден: {profile_record.candidate_name} (ID: {profile_record.id})")

        print("\n📝 Шаг 2: Создание тестовой вакансии...")
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
        await session.commit() # Фиксируем создание вакансии
        print(f"✅ Вакансия создана (ID: {created_job.id})")

        print("\n🧠 Шаг 3: Запуск AI Pipeline (Service Layer -> LangGraph)...")
        try:
            # Передаем ID вакансии, ID профиля и открытую сессию в наш сервис
            final_state = await run_pipeline(
                job_id=created_job.id, 
                profile_id=profile_record.id, 
                session=session
            )
            
            print("\n🎉 Пайплайн успешно завершен!")
            print("="*50)
            
            # Проверяем структуру стейта (названия ключей могут слегка отличаться в зависимости от твоей схемы)
            extracted = final_state.get("extracted_requirements")
            score = final_state.get("match_score")
            reasoning = final_state.get("match_reasoning", "Нет обоснования")

            print(f"🎯 Match Score: {score}/100")
            print(f"💡 Обоснование оценки:\n{reasoning}\n")
            
            print("📋 Извлеченные требования (Hard Skills):")
            if hasattr(extracted, 'hard_skills'):
                for skill in extracted.hard_skills:
                    print(f" - {skill}")
            elif isinstance(extracted, list):
                 for item in extracted:
                    print(f" - {item}")
            else:
                 print(f" - {extracted}")
                    
            print("="*50)
            
        except Exception as e:
            print(f"\n❌ Ошибка во время выполнения пайплайна: {e}")

if __name__ == "__main__":
    asyncio.run(run_full_integration_test())