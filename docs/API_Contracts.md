# API Contracts & Communication Protocols

## 1. REST API (Управление сущностями)
* **`POST /api/v1/jobs`** - Добавление новой вакансии (ссылка или сырой текст).
* **`GET /api/v1/jobs`** - Получение списка вакансий с фильтрацией по статусам.
* **`POST /api/v1/applications/{job_id}/generate`** - Запуск пайплайна генерации документов (возвращает `202 Accepted` и Job ID для отслеживания через WS).
* **`POST /api/v1/applications/{job_id}/send`** - Утверждение и ручной триггер отправки письма рекрутеру.

## 2. Webhook API (Интеграция с Google Cloud Pub/Sub)
* **`POST /api/v1/webhooks/gmail`**
    * **Описание:** Endpoint для приема push-уведомлений от Google при поступлении новых писем.
    * **Payload:** Стандартный конверт Pub/Sub (содержит `historyId` для запроса изменений через Gmail API).

## 3. WebSocket API (Real-time события)
* **Endpoint:** `ws://localhost:8000/ws/pipeline-status`
* **Направление:** Server -> Client
* **TypeScript Types (Frontend):**

## 4. Инфраструктура и Интеграции
    * **Frontend-Backend Sync:** WebSocket соединение для стриминга логов выполнения фоновых задач (поиск почты, LLM-генерация) в реальном времени.
    * **Inbox Parsing:** Использование Google Cloud Pub/Sub. При поступлении входящего письма Google отправляет POST-запрос на наш Webhook, после чего FastAPI фоном скачивает письмо, прогоняет через LLM для определения статуса (interview, rejection, info) и обновляет БД. Для локальной разработки Webhook пробрасывается через ngrok или localtunnel.

```typescript
// Strict type definitions (No interfaces)
export type PipelineStage = 
  | "Sourcing" 
  | "Matching" 
  | "Email_Discovery" 
  | "Document_Generation" 
  | "Completed" 
  | "Failed";

export type PipelineEvent = {
  jobId: string;
  stage: PipelineStage;
  progress: number; // 0-100
  message: string; // например: "SMTP ping successful for alex@company.com"
  timestamp: string; // ISO 8601
  payload?: Record<string, unknown>; // Дополнительные данные, если нужны
};
