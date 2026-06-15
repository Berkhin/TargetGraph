# Component Specification: AI Orchestration (LangGraph)

## 1. Архитектурный подход
* **Фреймворк:** LangGraph (`StateGraph`).
* **Модель Состояния (State):** Строгая Pydantic-модель (`BaseModel`). Каждое поле имеет явный тип данных и дефолтное значение.
* **Интеграция с LLM:** Официальный пакет `langchain-google-genai` (`ChatGoogleGenerativeAI`). Для генерации структурированных данных используется метод `.with_structured_output()`.

## 2. Структура State (GraphState)
Объект, который курсирует между всеми узлами:
* `job_posting`: Данные о вакансии (Pydantic-схема из слоя БД).
* `master_profile`: Профиль кандидата.
* `extracted_requirements`: Список (List[str]) выделенных требований.
* `match_score`: Оценка совпадения (int, 0-100).
* `resume_draft`: Сгенерированное резюме (Markdown/Text).
* `cover_letter_draft`: Сгенерированное письмо (Markdown/Text).
* `review_comments`: Список замечаний от узла-ревьюера (List[str]). По умолчанию пуст.
* `revision_number`: Счетчик итераций ревью (int), защита от бесконечного цикла.

## 3. Узлы (Nodes) и Маршрутизация (Edges)
1. **Node `extract_requirements`**: Анализ текста вакансии.
2. **Node `match_profile`**: Скоринг. Если `match_score < 70`, граф завершает работу (END).
3. **Node `draft_documents`**: Параллельная или последовательная генерация резюме и письма.
4. **Node `reviewer`**: Поиск "галлюцинаций". 
5. **Conditional Edge (от `reviewer`)**: Если есть `review_comments`, возвращаемся в `draft_documents`. Если нет (или `revision_number >= 3`) — идем в END.