# LedgerForge — Employee, Payroll & Accounting API

LedgerForge is a Python-based backend project developed as part of the Aura Workforce Python Developers training track. It evolves from a FastAPI starter application into an employee management, salary, attendance, payroll, and accounting platform.

The project focuses on REST API development, relational database modelling, data seeding, effective-dated salary structures, salary revision history, and automated testing.

## Project Information

| Item | Details |
|---|---|
| Project | LedgerForge |
| Track | Aura Workforce — Python Developers |
| Language | Python |
| Framework | FastAPI |
| ORM | SQLAlchemy |
| Validation | Pydantic |
| Database | SQLite starter configuration |
| Migrations | Alembic |
| Testing | Pytest |
| Repository | [05_Starter_Project](https://github.com/Sudharsana27/05_Starter_Project) |
| Phase tag | `phase-1` |
| Current task branch | `lf-05-salary-structures` |

**Training project:** All company and business data used in LedgerForge is fictional and intended for educational purposes only.

## Features

### Application foundation
- FastAPI application with interactive Swagger documentation.
- Health-check endpoint at `GET /health`.
- Environment-based configuration.
- SQLAlchemy database integration.
- Alembic migration support.
- Git-based development workflow.

### Data management
- Department, employee, role, and employee-assignment models.
- CSV data seeding support.
- Relational database constraints and relationships.
- Employee and department API functionality.

### Employee and team management
- Employee creation, retrieval, and update functionality.
- Employee search, department filtering, and pagination.
- Manager–team relationships using employee identifiers.
- Team-member retrieval.
- Soft-delete support using an employee exit date.

### Salary structure and revision
- SQLAlchemy models for salary components, salary structures, and salary revisions.
- Effective-date-based salary structure retrieval.
- Salary revision functionality that closes previous records and creates new records.
- Revision history with reasons for changes.
- Automated tests for salary API functionality.

## Technology Stack

| Technology | Purpose |
|---|---|
| Python | Application logic |
| FastAPI | REST API development |
| SQLAlchemy | Database models and queries |
| Pydantic | Request validation and response schemas |
| SQLite | Local development database |
| Alembic | Database schema migrations |
| Pytest | Automated testing |
| Git and GitHub | Version control and collaboration |

## Prerequisites

Install the following before running the project:

- Python 3.12 recommended.
- Git.
- Visual Studio Code or another Python IDE.
- PowerShell, Command Prompt, or another terminal.

Docker Desktop is required only for workflows that use the project's Docker configuration.

## Getting Started

### 1. Clone the repository

```powershell
git clone https://github.com/Sudharsana27/05_Starter_Project.git
cd 05_Starter_Project
```

### 2. Create a virtual environment

```powershell
python -m venv .venv
```

### 3. Activate the virtual environment

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
```

### 4. Install dependencies

```powershell
python -m pip install -r requirements.txt
```

### 5. Configure environment variables

Create a local `.env` file using the example configuration provided in the repository.

```powershell
Copy-Item .env.example .env
```

Review the database URL and other settings in `.env`. Keep secrets and environment-specific values out of Git.

### 6. Prepare the database

Use the project's Alembic migration workflow when setting up a fresh database:

```powershell
python -m alembic upgrade head
```

Follow the project's seeding instructions for the relevant dataset. The example seeder and the full CSV data seeder serve different purposes.

### 7. Start the API

```powershell
uvicorn app.main:app --reload
```

Open these addresses in your browser:

- API base URL: http://127.0.0.1:8000
- Interactive Swagger documentation: http://127.0.0.1:8000/docs
- OpenAPI schema: http://127.0.0.1:8000/openapi.json

Keep the terminal running while testing the API. Press `Ctrl+C` to stop the server.

### 8. Run automated tests

```powershell
python -m pytest -q
```

To run the salary, department, and employee test suites specifically:

```powershell
python -m pytest tests/test_salary.py tests/test_departments.py tests/test_employees.py -q
```

The salary, department, and employee test suites returned **16 passed** in the recorded test run. Run the tests again after subsequent changes to confirm the current result.

## API Documentation

The application exposes interactive API documentation through Swagger at `/docs`.

The API includes functionality for:

| Area | Functionality |
|---|---|
| System | Health check |
| Departments | Department listing and lookup |
| Employees | Employee creation, retrieval, updates, search, and filtering |
| Teams | Retrieval of an employee's direct reports |
| Salary | Salary structure retrieval and salary revision operations |

Consult `/docs` for the exact route paths, HTTP methods, request schemas, and response formats available in the current checkout.

## Salary Structure and Revision Design

Salary information is modelled using three main entities:

- **Salary components:** Represent individual elements of compensation.
- **Salary structures:** Represent the applicable salary components over an effective period.
- **Salary revisions:** Record changes to an employee's salary, including the revision date and reason.

The salary service supports retrieving the structure applicable to an employee on a specified date and revising salary records by closing the previous effective period and creating the new records.

Effective-date boundaries are important: the implementation and its tests should ensure that a date returns the correct structure and that salary revision history preserves previous changes.

## Project Structure

```text
05_Starter_Project/
├── app/
│   ├── config.py
│   ├── database.py
│   ├── main.py
│   ├── models.py
│   ├── schemas.py
│   ├── salary_service.py
│   └── routers/
│       ├── departments.py
│       ├── employees.py
│       └── salary.py
├── scripts/
├── tests/
│   ├── test_departments.py
│   ├── test_employees.py
│   └── test_salary.py
├── alembic/
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

Some directories may contain additional files as development continues.

## Development Guidelines

- Use a separate Git branch for each task.
- Use SQLAlchemy models for database entities and Pydantic schemas for request validation.
- Write automated tests for API endpoints and business rules.
- Use `Decimal` rather than floating-point arithmetic for monetary calculations.
- Use database migrations to manage schema changes.
- Validate effective-date ranges to avoid overlaps and incorrect salary history.
- Never commit `.env`, virtual environments, database files, or secrets.
- Commit and push completed work regularly.

## Git Workflow

Create a branch for a new task:

```powershell
git switch -c lf-06-next-task
```

Run tests and review changes:

```powershell
python -m pytest -q
git status
git diff
```

Stage only the files intended for the commit:

```powershell
git add README.md
git diff --cached --check
git diff --cached
```

Commit and push:

```powershell
git commit -m "docs: update LedgerForge README"
git push
```

For a new branch without an upstream, use:

```powershell
git push -u origin lf-06-next-task
```

## Training Roadmap

| Milestones | Scope |
|---|---|
| LF-01 | Project bootstrap and repository setup |
| LF-02 | Employee, department, role, and assignment data model |
| LF-03 | One-command CSV data seeder |
| LF-04 | Employee and team APIs |
| LF-05 | Salary structures and revision history |
| LF-06–LF-08 | Attendance, leave, payroll, and payslips |
| LF-09–LF-12 | Accounting ledger, invoices, expenses, and payroll posting |
| LF-13–LF-16 | Authentication, tax reports, financial reports, and release candidate |
| LF-17–LF-20 | Deployment, reliability, exports, final audit, and submission |

## Current Development Status

The project has progressed beyond its original starter application. The current working branch is `lf-05-salary-structures`, which contains the salary structure and revision API work.

The recorded verification run for the salary, department, and employee test suites completed with 16 passing tests. Further milestones will extend the application with attendance, payroll, accounting, authentication, reporting, and deployment capabilities.

## Learning Outcomes

This project provides practical experience with:

- Building REST APIs using FastAPI.
- Modelling relational data with SQLAlchemy.
- Validating input with Pydantic.
- Managing database schema changes with Alembic.
- Loading CSV data into a database.
- Writing automated tests using Pytest.
- Maintaining a task-based Git workflow.

---

**LedgerForge · Aura Workforce · Python Developers Training Track**
