# Component Specification: Data Layer (PostgreSQL)

## 1. Архитектурный подход
* **ORM:** SQLAlchemy 2.0 (строгая типизация через `Mapped` и `mapped_column`).
* **Драйвер:** `asyncpg` для полностью асинхронного взаимодействия.
* **Паттерн доступа:** Repository. Бизнес-логика работает только с абстракциями репозиториев (например, `JobRepository`), которые принимают и возвращают Pydantic-модели, полностью инкапсулируя объекты SQLAlchemy.
* **Управление сессиями:** Инъекция зависимостей FastAPI (Dependency Injection) передает асинхронную сессию в репозиторий.

## 2. Структура директорий
backend/app/
├── db/
│   ├── database.py       # Engine и sessionmaker
│   ├── base.py           # DeclarativeBase
│   └── migrations/       # Папка Alembic
├── models/
│   ├── sql/              # Модели SQLAlchemy (таблицы)
│   └── schemas/          # Pydantic-модели (DTO/Контракты)
└── repositories/
    ├── base.py           # Базовый абстрактный класс (опционально)
    └── job_repository.py # Имплементация для JobPosting

## 3. Базовые сущности для реализации (Этап 1)
Реализовать таблицу `job_postings` и соответствующий репозиторий с базовыми CRUD-операциями:
* Создание новой вакансии.
* Получение списка вакансий с фильтрацией по статусу (например, `NEW`, `MATCHED`).
* Обновление статуса и оценки (match_score).