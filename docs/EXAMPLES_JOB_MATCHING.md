# Job Matching Pipeline Examples

## Endpoint: `POST /api/v1/jobs/{job_id}/match`

Запускает AI-пайплайн для сопоставления профиля кандидата с вакансией. После выполнения сохраняет результаты (match_score, cover_letter_draft, status) обратно в БД.

### Request

```bash
curl -X POST "http://localhost:8000/api/v1/jobs/{job_id}/match" \
  -H "Content-Type: application/json" \
  -G --data-urlencode "profile_id={profile_id}"
```

**Path Parameters:**
- `job_id` (UUID) - ID вакансии для сопоставления

**Query Parameters:**
- `profile_id` (UUID) - ID профиля кандидата для сопоставления

### Response (200 OK)

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "company_name": "TechNova Core",
  "job_title": "Senior AI/Frontend Engineer",
  "description": "We are looking for a Senior Engineer...",
  "source_url": "https://example.com/job/technova",
  "match_score": 100,
  "cover_letter_draft": "I am writing to express my interest in the Senior AI/Frontend Engineer position...",
  "status": "MATCHED",
  "created_at": "2026-06-15T10:30:00",
  "updated_at": "2026-06-15T10:35:45"
}
```

### Response (404 Not Found)

**Если вакансия не найдена:**
```json
{
  "detail": "job posting 550e8400-e29b-41d4-a716-446655440000 not found"
}
```

**Если профиль не найден:**
```json
{
  "detail": "profile 550e8400-e29b-41d4-a716-446655440000 not found"
}
```

## How it Works

1. **Input:** Получает ID вакансии и ID профиля из параметров.
2. **Pipeline Execution:** Запускает LangGraph-пайплайн с шагами:
   - Extract Requirements (извлечение требований из описания вакансии)
   - Match Profile (оценка соответствия профиля требованиям)
   - Draft Documents (генерация сопроводительного письма)
   - Review (ревью и итеративное улучшение письма)
3. **Result Saving:** Сохраняет результаты в БД:
   - `match_score` (0-100)
   - `cover_letter_draft` (сгенерированное письмо)
   - `status` (MATCHED если скор >= 70, иначе REJECTED_BY_AI)
4. **Return:** Возвращает обновленный объект вакансии

## Status Logic

- **MATCHED** (скор >= 70) - Профиль хорошо подходит для вакансии
- **REJECTED_BY_AI** (скор < 70) - Профиль не достаточно соответствует требованиям вакансии

## Example Usage (Python)

```python
import httpx
import uuid

async def run_matching():
    job_id = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
    profile_id = uuid.UUID("bacfe977-5cd4-470f-a5b0-51fffc592e2e")
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"http://localhost:8000/api/v1/jobs/{job_id}/match",
            params={"profile_id": str(profile_id)}
        )
        
        if response.status_code == 200:
            job = response.json()
            print(f"Match Score: {job['match_score']}/100")
            print(f"Status: {job['status']}")
            print(f"Cover Letter:\n{job['cover_letter_draft']}")
        else:
            print(f"Error: {response.status_code}")
            print(response.json())

# Run it
import asyncio
asyncio.run(run_matching())
```

## Notes

- The endpoint is **synchronous** — it waits for the full pipeline to complete before returning (10-30 seconds typical)
- The response always includes the full `JobRead` schema with all fields populated
- Transaction management is handled by the FastAPI endpoint — the service layer (`run_pipeline`) only flushes, never commits
