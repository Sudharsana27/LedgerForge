
# LedgerForge — Organization ER Diagram

```mermaid
erDiagram
    DEPARTMENTS ||--o{ ROLES : contains
    DEPARTMENTS ||--o{ EMPLOYEES : assigns
    ROLES ||--o{ EMPLOYEES : defines
    EMPLOYEES o|--o{ EMPLOYEES : manages
    EMPLOYEES ||--o{ EMPLOYEE_ASSIGNMENTS : has
    DEPARTMENTS ||--o{ EMPLOYEE_ASSIGNMENTS : records
    ROLES ||--o{ EMPLOYEE_ASSIGNMENTS : records

    DEPARTMENTS {
        string department_id PK
        string department_name
        string cost_center
    }

    ROLES {
        string role_id PK
        string department_id FK
        string role_title
    }

    EMPLOYEES {
        string employee_id PK
        string work_email UK
        string department_id FK
        string role_id FK
        string manager_id FK
    }

    EMPLOYEE_ASSIGNMENTS {
        string assignment_id PK
        string employee_id FK
        date effective_from
        date effective_to
        string department_id FK
        string role_id FK
        string manager_id FK
    }
```

## Nullable columns: why they may be empty

- `manager_id` can be NULL when an employee has no manager assigned, such as the top-level leader.
- `exit_date`, `resignation_date`, `exit_type`, and `exit_reason` can be NULL while an employee is still employed or when exit details are not applicable.
- `effective_to` can be NULL for the current employee assignment because it has no known end date yet.
