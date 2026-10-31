import csv
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    create_engine,
    event,
    select,
    update,
)
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.ledger_service import (
    JournalEntryInput,
    JournalLineInput,
    LedgerError,
    UnbalancedJournalEntryError,
    account_balance,
    create_journal_entry,
    reverse_journal_entry,
)
from app.models import (
    ChartOfAccount,
    Department,
    JournalEntry,
    JournalLine,
)
from app.payroll_ledger_service import post_payroll_run
from scripts.export_ledger import export_ledger_tables


@pytest.fixture
def ledger_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'ledger-test.db'}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = session_factory()
    db.add_all(
        [
            Department(
                department_id="D01",
                department_name="Finance",
                cost_center="CC01",
            ),
            ChartOfAccount(
                account_code="1000",
                account_name="Cash",
                account_type="ASSET",
                normal_balance="DEBIT",
                parent_code=None,
                is_group="Y",
                statement="BALANCE_SHEET",
                is_active="Y",
            ),
            ChartOfAccount(
                account_code="1001",
                account_name="Bank",
                account_type="ASSET",
                normal_balance="DEBIT",
                parent_code="1000",
                is_group="N",
                statement="BALANCE_SHEET",
                is_active="Y",
            ),
            ChartOfAccount(
                account_code="1002",
                account_name="Cash on hand",
                account_type="ASSET",
                normal_balance="DEBIT",
                parent_code="1000",
                is_group="N",
                statement="BALANCE_SHEET",
                is_active="Y",
            ),
            ChartOfAccount(
                account_code="1300",
                account_name="Employee Advances & Loans",
                account_type="ASSET",
                normal_balance="DEBIT",
                parent_code="1000",
                is_group="N",
                statement="BALANCE_SHEET",
                is_active="Y",
            ),
            ChartOfAccount(
                account_code="2000",
                account_name="Payables",
                account_type="LIABILITY",
                normal_balance="CREDIT",
                parent_code=None,
                is_group="Y",
                statement="BALANCE_SHEET",
                is_active="Y",
            ),
            ChartOfAccount(
                account_code="2001",
                account_name="Trade payable",
                account_type="LIABILITY",
                normal_balance="CREDIT",
                parent_code="2000",
                is_group="N",
                statement="BALANCE_SHEET",
                is_active="Y",
            ),
            *[
                ChartOfAccount(
                    account_code=code,
                    account_name=name,
                    account_type="LIABILITY",
                    normal_balance="CREDIT",
                    parent_code="2000",
                    is_group="N",
                    statement="BALANCE_SHEET",
                    is_active="Y",
                )
                for code, name in (
                    ("2100", "Salaries Payable"),
                    ("2110", "PF Payable"),
                    ("2120", "ESI Payable"),
                    ("2130", "TDS Payable"),
                    ("2140", "Professional Tax Payable"),
                )
            ],
            ChartOfAccount(
                account_code="5000",
                account_name="Expenses",
                account_type="EXPENSE",
                normal_balance="DEBIT",
                parent_code=None,
                is_group="Y",
                statement="INCOME_STATEMENT",
                is_active="Y",
            ),
            *[
                ChartOfAccount(
                    account_code=code,
                    account_name=name,
                    account_type="EXPENSE",
                    normal_balance="DEBIT",
                    parent_code="5000",
                    is_group="N",
                    statement="INCOME_STATEMENT",
                    is_active="Y",
                )
                for code, name in (
                    ("5001", "Salaries & Wages"),
                    ("5002", "Overtime Expense"),
                    ("5003", "Incentives & Bonus"),
                    ("5004", "Employer PF Contribution"),
                    ("5005", "Employer ESI Contribution"),
                )
            ],
            ChartOfAccount(
                account_code="3001",
                account_name="Inactive account",
                account_type="EQUITY",
                normal_balance="CREDIT",
                parent_code=None,
                is_group="N",
                statement="BALANCE_SHEET",
                is_active="N",
            ),
        ]
    )
    db.commit()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def _entry(entry_id="JE-TEST", entry_date=date(2025, 4, 1)):
    return JournalEntryInput(
        entry_id=entry_id,
        entry_date=entry_date,
        posting_period="2025-04",
        financial_year="2025-26",
        description="Training journal entry",
        source_type="MANUAL",
        source_id=f"SRC-{entry_id}",
        created_by="tester",
        created_at=datetime(2025, 4, 1, 9, 0),
    )


def _lines(
    debit=Decimal("10.00"),
    credit=Decimal("10.00"),
    account_code="1001",
    prefix="TEST",
):
    return [
        JournalLineInput(
            line_id=f"JL-{prefix}-1",
            line_no=1,
            account_code=account_code,
            debit=debit,
            credit=Decimal("0.00"),
            cost_center_department_id="D01",
        ),
        JournalLineInput(
            line_id=f"JL-{prefix}-2",
            line_no=2,
            account_code="2001",
            debit=Decimal("0.00"),
            credit=credit,
        ),
    ]


def _create_payroll_sources(db, *, total_gross="1150.00"):
    metadata = MetaData()
    runs = Table(
        "payroll_runs",
        metadata,
        Column("run_id", String(30), primary_key=True),
        Column("period_start", Date, nullable=False),
        Column("period_end", Date, nullable=False),
        Column("pay_date", Date, nullable=False),
        Column("status", String(20), nullable=False),
        Column("total_gross", Numeric(18, 2), nullable=False),
        Column("total_deductions", Numeric(18, 2), nullable=False),
        Column("total_net", Numeric(18, 2), nullable=False),
        Column("total_employer_contributions", Numeric(18, 2), nullable=False),
        Column("total_employer_cost", Numeric(18, 2), nullable=False),
        Column("journal_entry_id", String(30), nullable=True),
    )
    items = Table(
        "payroll_items",
        metadata,
        Column("payroll_item_id", String(30), primary_key=True),
        Column("run_id", String(30), nullable=False),
        Column("employee_id", String(30), nullable=False),
        Column("department_id", String(10), nullable=False),
        Column("gross_pay", Numeric(18, 2), nullable=False),
        Column("total_deductions", Numeric(18, 2), nullable=False),
        Column("earned_fixed_pay", Numeric(18, 2), nullable=False),
        Column("overtime_pay", Numeric(18, 2), nullable=False),
        Column("variable_pay", Numeric(18, 2), nullable=False),
        Column("pf_employee", Numeric(18, 2), nullable=False),
        Column("esi_employee", Numeric(18, 2), nullable=False),
        Column("professional_tax", Numeric(18, 2), nullable=False),
        Column("tds", Numeric(18, 2), nullable=False),
        Column("other_deductions", Numeric(18, 2), nullable=False),
        Column("net_pay", Numeric(18, 2), nullable=False),
        Column("pf_employer", Numeric(18, 2), nullable=False),
        Column("esi_employer", Numeric(18, 2), nullable=False),
    )
    metadata.create_all(db.get_bind())
    with db.get_bind().begin() as connection:
        connection.execute(
            runs.insert().values(
                run_id="PR-2025-04",
                period_start=date(2025, 4, 1),
                period_end=date(2025, 4, 30),
                pay_date=date(2025, 5, 1),
                status="PAID",
                total_gross=Decimal(total_gross),
                total_deductions=Decimal("260.00"),
                total_net=Decimal("890.00"),
                total_employer_contributions=Decimal("140.00"),
                total_employer_cost=Decimal("1290.00"),
                journal_entry_id=None,
            )
        )
        connection.execute(
            items.insert().values(
                payroll_item_id="PI-TEST-1",
                run_id="PR-2025-04",
                employee_id="EMP-TEST-1",
                department_id="D01",
                gross_pay=Decimal("1150.00"),
                total_deductions=Decimal("260.00"),
                earned_fixed_pay=Decimal("1000.00"),
                overtime_pay=Decimal("100.00"),
                variable_pay=Decimal("50.00"),
                pf_employee=Decimal("120.00"),
                esi_employee=Decimal("10.00"),
                professional_tax=Decimal("30.00"),
                tds=Decimal("40.00"),
                other_deductions=Decimal("60.00"),
                net_pay=Decimal("890.00"),
                pf_employer=Decimal("120.00"),
                esi_employer=Decimal("20.00"),
            )
        )
    return runs, items


def test_posts_balanced_entry_with_exact_decimal_totals(ledger_db):
    entry = create_journal_entry(ledger_db, _entry(), _lines())

    assert entry.status == "POSTED"
    assert entry.total_debit == Decimal("10.00")
    assert entry.total_credit == Decimal("10.00")
    assert len(entry.lines) == 2


def test_rejects_unbalanced_entry_with_totals_in_message(ledger_db):
    with pytest.raises(
        UnbalancedJournalEntryError,
        match=r"debits 10\.00 do not equal credits 9\.99",
    ):
        create_journal_entry(
            ledger_db,
            _entry(),
            _lines(Decimal("10.00"), Decimal("9.99")),
        )

    assert ledger_db.scalar(select(JournalEntry)) is None


@pytest.mark.parametrize("line_count", [0, 1])
def test_rejects_entries_without_at_least_two_lines(ledger_db, line_count):
    with pytest.raises(LedgerError, match="at least two lines"):
        create_journal_entry(
            ledger_db,
            _entry(),
            _lines()[:line_count],
        )


def test_rejects_unknown_inactive_and_group_accounts(ledger_db):
    for account_code, message in (
        ("9999", "Unknown account code"),
        ("3001", "not active"),
        ("1000", "cannot receive postings"),
    ):
        lines = _lines(account_code=account_code)
        with pytest.raises(LedgerError, match=message):
            create_journal_entry(ledger_db, _entry(), lines)
        ledger_db.rollback()

    assert ledger_db.scalar(select(JournalEntry)) is None


@pytest.mark.parametrize(
    ("debit", "credit", "message"),
    [
        (Decimal("-1.00"), Decimal("1.00"), "cannot be negative"),
        (Decimal("1.001"), Decimal("1.001"), "more than two decimals"),
        (1.0, Decimal("1.00"), "must be Decimal"),
        (Decimal("1.00"), Decimal("1.00"), "positive debit or credit"),
        (Decimal("0.00"), Decimal("0.00"), "positive debit or credit"),
    ],
)
def test_rejects_invalid_line_amounts(ledger_db, debit, credit, message):
    lines = _lines()
    lines[0] = JournalLineInput(
        line_id="JL-INVALID",
        line_no=1,
        account_code="1001",
        debit=debit,
        credit=credit,
    )
    with pytest.raises(LedgerError, match=message):
        create_journal_entry(ledger_db, _entry(), lines)


def test_rejects_duplicate_entry_and_line_ids(ledger_db):
    create_journal_entry(ledger_db, _entry(), _lines())
    with pytest.raises(LedgerError, match="database constraint"):
        create_journal_entry(ledger_db, _entry(), _lines())

    duplicate_lines = _lines()
    duplicate_lines[1] = JournalLineInput(
        line_id=duplicate_lines[0].line_id,
        line_no=2,
        account_code="2001",
        debit=Decimal("0.00"),
        credit=Decimal("10.00"),
    )
    with pytest.raises(LedgerError, match="line IDs must be unique"):
        create_journal_entry(ledger_db, _entry("JE-DUP-LINE"), duplicate_lines)


def test_database_failure_rolls_back_entry_and_lines(ledger_db):
    def fail_line_insert(_mapper, _connection, target):
        if target.line_id == "JL-TEST-2":
            raise RuntimeError("simulated line insert failure")

    event.listen(JournalLine, "before_insert", fail_line_insert)
    try:
        with pytest.raises(RuntimeError, match="simulated line insert failure"):
            create_journal_entry(ledger_db, _entry(), _lines())
    finally:
        event.remove(JournalLine, "before_insert", fail_line_insert)

    assert ledger_db.scalar(
        select(JournalEntry).where(JournalEntry.entry_id == "JE-TEST")
    ) is None
    assert ledger_db.scalars(select(JournalLine)).all() == []


def test_posted_entry_and_lines_are_immutable(ledger_db):
    create_journal_entry(ledger_db, _entry(), _lines())
    line = ledger_db.get(JournalLine, "JL-TEST-1")
    line.debit = Decimal("11.00")
    with pytest.raises(ValueError, match="immutable"):
        ledger_db.flush()
    ledger_db.rollback()

    entry = ledger_db.get(JournalEntry, "JE-TEST")
    entry.description = "edited"
    with pytest.raises(ValueError, match="immutable"):
        ledger_db.flush()
    ledger_db.rollback()

    entry = ledger_db.get(JournalEntry, "JE-TEST")
    with pytest.raises(ValueError, match="immutable"):
        ledger_db.delete(entry)
        ledger_db.flush()
    ledger_db.rollback()

    ledger_db.add(
        JournalLine(
            line_id="JL-APPEND",
            entry_id="JE-TEST",
            line_no=3,
            account_code="1001",
            debit=Decimal("1.00"),
            credit=Decimal("0.00"),
        )
    )
    with pytest.raises(ValueError, match="cannot be added"):
        ledger_db.flush()
    ledger_db.rollback()

    with pytest.raises(ValueError, match="Bulk journal updates and deletes"):
        ledger_db.execute(
            update(JournalEntry)
            .where(JournalEntry.entry_id == "JE-TEST")
            .values(description="bulk edit")
        )
    ledger_db.rollback()


def test_reversal_posts_opposite_lines_and_references_source(ledger_db):
    create_journal_entry(ledger_db, _entry(), _lines())
    reversal = reverse_journal_entry(
        ledger_db,
        "JE-TEST",
        _entry("JE-REVERSAL", date(2025, 4, 2)),
        ["JL-REV-1", "JL-REV-2"],
    )

    assert reversal.status == "POSTED"
    assert reversal.reversal_of_source_id == "SRC-JE-TEST"
    assert [(line.debit, line.credit) for line in reversal.lines] == [
        (Decimal("0.00"), Decimal("10.00")),
        (Decimal("10.00"), Decimal("0.00")),
    ]
    original = ledger_db.get(JournalEntry, "JE-TEST")
    assert original.total_debit == Decimal("10.00")
    assert original.reversal_of_source_id is None
    assert account_balance(ledger_db, "1001", date(2025, 4, 2)) == Decimal(
        "0.00"
    )


def test_chart_of_accounts_has_expected_hierarchy(ledger_db):
    assets = ledger_db.get(ChartOfAccount, "1000")
    bank = ledger_db.get(ChartOfAccount, "1001")
    expenses = ledger_db.get(ChartOfAccount, "5000")
    wages = ledger_db.get(ChartOfAccount, "5001")

    assert assets.is_group == "Y"
    assert assets.account_type == "ASSET"
    assert bank.parent_code == assets.account_code
    assert bank.normal_balance == "DEBIT"
    assert expenses.is_group == "Y"
    assert expenses.account_type == "EXPENSE"
    assert wages.parent_code == expenses.account_code
    assert wages.normal_balance == "DEBIT"


def test_payroll_run_posts_balanced_lines_once_and_links_source(ledger_db):
    runs, _items = _create_payroll_sources(ledger_db)
    posted_at = datetime(2025, 5, 1, 9, 0)

    posted = post_payroll_run(
        ledger_db,
        "PR-2025-04",
        created_by="payroll-test",
        created_at=posted_at,
    )
    repeated = post_payroll_run(
        ledger_db,
        "PR-2025-04",
        created_by="payroll-test",
        created_at=posted_at,
    )

    assert repeated.entry_id == posted.entry_id
    assert posted.status == "POSTED"
    assert posted.source_type == "PAYROLL_RUN"
    assert posted.source_id == "PR-2025-04"
    assert posted.entry_date == date(2025, 5, 1)
    assert posted.posting_period == "2025-04"
    assert posted.financial_year == "FY2025-26"
    assert posted.total_debit == Decimal("1290.00")
    assert posted.total_credit == Decimal("1290.00")
    assert len(ledger_db.scalars(select(JournalEntry)).all()) == 1
    by_account = {}
    for line in posted.lines:
        by_account[line.account_code] = (
            by_account.get(line.account_code, Decimal("0.00"))
            + line.debit
            + line.credit
        )
    assert by_account == {
        "5001": Decimal("1000.00"),
        "5002": Decimal("100.00"),
        "5003": Decimal("50.00"),
        "5004": Decimal("120.00"),
        "5005": Decimal("20.00"),
        "2100": Decimal("890.00"),
        "2110": Decimal("240.00"),
        "2120": Decimal("30.00"),
        "2130": Decimal("40.00"),
        "2140": Decimal("30.00"),
        "1300": Decimal("60.00"),
    }
    assert all(
        line.cost_center_department_id == "D01"
        for line in posted.lines
        if line.account_code.startswith("5")
    )
    with ledger_db.get_bind().connect() as connection:
        run = connection.execute(
            select(runs.c.journal_entry_id).where(
                runs.c.run_id == "PR-2025-04"
            )
        ).scalar_one()
    assert run == posted.entry_id


def test_payroll_posting_does_not_duplicate_existing_source_entry(ledger_db):
    runs, _items = _create_payroll_sources(ledger_db)
    existing = create_journal_entry(
        ledger_db,
        JournalEntryInput(
            entry_id="JE-IMPORTED-PAYROLL",
            entry_date=date(2025, 5, 1),
            posting_period="2025-04",
            financial_year="FY2025-26",
            description="Imported historical payroll posting",
            source_type="PAYROLL_RUN",
            source_id="PR-2025-04",
            created_by="import",
            created_at=datetime(2025, 5, 1, 9, 0),
        ),
        _lines(prefix="IMPORTED"),
    )

    result = post_payroll_run(
        ledger_db,
        "PR-2025-04",
        created_by="payroll-test",
    )

    assert result.entry_id == existing.entry_id
    assert len(ledger_db.scalars(select(JournalEntry)).all()) == 1
    with ledger_db.get_bind().connect() as connection:
        linked_id = connection.execute(
            select(runs.c.journal_entry_id).where(
                runs.c.run_id == "PR-2025-04"
            )
        ).scalar_one()
    assert linked_id == existing.entry_id


def test_payroll_posting_rejects_mismatched_run_totals_without_posting(
    ledger_db,
):
    _create_payroll_sources(ledger_db, total_gross="1150.01")

    with pytest.raises(LedgerError, match="total_gross"):
        post_payroll_run(
            ledger_db,
            "PR-2025-04",
            created_by="payroll-test",
        )

    assert ledger_db.scalars(select(JournalEntry)).all() == []
    assert ledger_db.scalars(select(JournalLine)).all() == []


def test_payroll_posting_rejects_unapproved_run(ledger_db):
    runs, _items = _create_payroll_sources(ledger_db)
    with ledger_db.get_bind().begin() as connection:
        connection.execute(
            runs.update()
            .where(runs.c.run_id == "PR-2025-04")
            .values(status="DRAFT")
        )

    with pytest.raises(LedgerError, match="not approved"):
        post_payroll_run(
            ledger_db,
            "PR-2025-04",
            created_by="payroll-test",
        )

    assert ledger_db.scalars(select(JournalEntry)).all() == []


def test_account_balance_uses_normal_side_hierarchy_and_cutoff(ledger_db):
    create_journal_entry(
        ledger_db,
        _entry("JE-APR", date(2025, 4, 1)),
        _lines(Decimal("10.00"), Decimal("10.00"), prefix="APR"),
    )
    create_journal_entry(
        ledger_db,
        _entry("JE-MAY", date(2025, 5, 1)),
        [
            JournalLineInput(
                "JL-MAY-1", 1, "1002", Decimal("5.00"), Decimal("0.00")
            ),
            JournalLineInput(
                "JL-MAY-2", 2, "2001", Decimal("0.00"), Decimal("5.00")
            ),
        ],
    )
    create_journal_entry(
        ledger_db,
        _entry("JE-JUNE", date(2025, 6, 1)),
        _lines(Decimal("7.00"), Decimal("7.00"), prefix="JUNE"),
    )

    assert account_balance(ledger_db, "1000", date(2025, 5, 31)) == Decimal(
        "15.00"
    )
    assert account_balance(ledger_db, "1001", date(2025, 5, 31)) == Decimal(
        "10.00"
    )
    assert account_balance(ledger_db, "2000", date(2025, 5, 31)) == Decimal(
        "15.00"
    )


def test_export_writes_source_compatible_tables_without_overwriting(
    ledger_db, tmp_path
):
    create_journal_entry(ledger_db, _entry(), _lines())
    output_dir = tmp_path / "ledger-export"
    paths = export_ledger_tables(ledger_db, output_dir)

    assert [path.name for path in paths] == [
        "chart_of_accounts.csv",
        "journal_entries.csv",
        "journal_lines.csv",
    ]
    with paths[1].open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    assert rows[0]["total_debit"] == "10.00"
    assert rows[0]["total_credit"] == "10.00"
    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        export_ledger_tables(ledger_db, output_dir)
