import asyncio
from app.ai.nodes import extract_requirements
from app.ai.state import GraphState

async def run_test():
    # Имитируем сырой текст, который принес скрейпер
    sample_job_text = """
    We are looking for a Senior Full Stack & AI Engineer to join our core team.
    You will be responsible for building scalable web interfaces and integrating LLM-based autonomous agents.
    
    Requirements:
    - 5+ years of experience in Frontend development.
    - Deep knowledge of React, TypeScript, and modern state management (Zustand/Redux).
    - Strong background in Python and asynchronous programming.
    - Hands-on experience with LLM orchestration frameworks (LangGraph, LangChain) is a must.
    - Experience with CI/CD pipelines (GitLab CI) and cloud deployments (Azure).
    
    Nice to have:
    - Familiarity with Auth0 or similar OIDC providers.
    - E2E testing experience (Cypress).
    """

    # Инициализируем стейт с этим текстом
    initial_state = GraphState(
        job_text=sample_job_text,
        profile_text="" # Пока пустой, профиль понадобится на следующем узле
    )

    print("🚀 Запускаем узел extract_requirements...")
    
    # Вызываем функцию узла
    try:
        updated_state_dict = await extract_requirements(initial_state)
        
        print("\n✅ Узел отработал успешно! Результат извлечения:")
        reqs = updated_state_dict.get("extracted_requirements")
        if reqs is not None:
            print(" Hard skills:")
            for item in reqs.hard_skills:
                print(f"   - {item}")
            print(" Soft skills:")
            for item in reqs.soft_skills:
                print(f"   - {item}")
            print(" Core responsibilities:")
            for item in reqs.core_responsibilities:
                print(f"   - {item}")
            
    except Exception as e:
        print(f"\n❌ Ошибка при вызове LLM: {e}")

if __name__ == "__main__":
    asyncio.run(run_test())