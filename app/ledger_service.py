from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .models import ChartOfAccount, JournalEntry, JournalLine


class LedgerError(ValueError):
    """Raised when a ledger operation violates a posting rule."""


class UnbalancedJournalEntryError(LedgerError):
    """Raised when journal debits and credits differ."""


@dataclass(frozen=True)
class JournalEntryInput:
    entry_id: str
    entry_date: date
    posting_period: str
    financial_year: str
    description: str
    source_type: str
    source_id: str
    created_by: str
    created_at: datetime


@dataclass(frozen=True)
class JournalLineInput:
    line_id: str
    line_no: int
    account_code: str
    debit: Decimal
    credit: Decimal
    cost_center_department_id: str | None = None
    line_description: str | None = None


def _validate_lines(
    lines: Sequence[JournalLineInput],
) -> tuple[Decimal, Decimal]:
    if len(lines) < 2:
        raise LedgerError("A journal entry must contain at least two lines.")

    line_ids = [line.line_id for line in lines]
    if len(set(line_ids)) != len(line_ids):
        raise LedgerError("Journal line IDs must be unique within the entry.")

    line_numbers = [line.line_no for line in lines]
    if len(set(line_numbers)) != len(line_numbers):
        raise LedgerError("Journal line numbers must be unique within the entry.")

    debit_total = Decimal("0.00")
    credit_total = Decimal("0.00")
    for line in lines:
        if line.line_no <= 0:
            raise LedgerError("Journal line numbers must be positive.")
        if not isinstance(line.debit, Decimal) or not isinstance(
            line.credit, Decimal
        ):
            raise LedgerError("Debit and credit amounts must be Decimal values.")
        if not line.debit.is_finite() or not line.credit.is_finite():
            raise LedgerError("Debit and credit amounts must be finite.")
        if (
            line.debit.as_tuple().exponent < -2
            or line.credit.as_tuple().exponent < -2
        ):
            raise LedgerError(
                "Journal amounts cannot have more than two decimals."
            )
        if line.debit < 0 or line.credit < 0:
            raise LedgerError("Debit and credit amounts cannot be negative.")
        if (line.debit > 0) == (line.credit > 0):
            raise LedgerError(
                "Each journal line must have a positive debit or credit, "
                "but not both."
            )
        debit_total += line.debit
        credit_total += line.credit

    if debit_total != credit_total:
        raise UnbalancedJournalEntryError(
            f"Journal entry is unbalanced: debits {debit_total:.2f} "
            f"do not equal credits {credit_total:.2f}."
        )
    return debit_total, credit_total


def _create_journal_entry_in_transaction(
    db: Session,
    entry: JournalEntryInput,
    lines: Sequence[JournalLineInput],
    *,
    reversal_of_source_id: str | None = None,
) -> JournalEntry:
    debit_total, credit_total = _validate_lines(lines)
    account_codes = {line.account_code for line in lines}
    accounts = {
        account.account_code: account
        for account in db.scalars(
            select(ChartOfAccount).where(
                ChartOfAccount.account_code.in_(account_codes)
            )
        )
    }

    missing_accounts = sorted(account_codes - set(accounts))
    if missing_accounts:
        raise LedgerError(
            f"Unknown account code(s): {', '.join(missing_accounts)}."
        )
    for account in accounts.values():
        if account.is_active != "Y":
            raise LedgerError(
                f"Account {account.account_code} is not active."
            )
        if account.is_group == "Y":
            raise LedgerError(
                f"Group account {account.account_code} cannot receive "
                "postings."
            )

    journal_entry = JournalEntry(
        entry_id=entry.entry_id,
        entry_date=entry.entry_date,
        posting_period=entry.posting_period,
        financial_year=entry.financial_year,
        description=entry.description,
        source_type=entry.source_type,
        source_id=entry.source_id,
        status="DRAFT",
        total_debit=debit_total,
        total_credit=credit_total,
        reversal_of_source_id=reversal_of_source_id,
        created_by=entry.created_by,
        created_at=entry.created_at,
    )
    db.add(journal_entry)
    db.flush()

    db.add_all(
        JournalLine(
            line_id=line.line_id,
            entry_id=entry.entry_id,
            line_no=line.line_no,
            account_code=line.account_code,
            debit=line.debit,
            credit=line.credit,
            cost_center_department_id=line.cost_center_department_id,
            line_description=line.line_description,
        )
        for line in lines
    )
    db.flush()
    journal_entry.status = "POSTED"
    db.flush()
    return journal_entry


def create_journal_entry(
    db: Session,
    entry: JournalEntryInput,
    lines: Sequence[JournalLineInput],
    *,
    reversal_of_source_id: str | None = None,
) -> JournalEntry:
    """Create and atomically post one balanced journal entry.

    The operation owns its transaction. The supplied Session must not already
    have an active transaction so a failure cannot roll back caller work.
    """
    if db.in_transaction():
        raise LedgerError(
            "create_journal_entry requires a Session with no active transaction."
        )
    _validate_lines(lines)
    try:
        with db.begin():
            return create_journal_entry_in_transaction(
                db,
                entry,
                lines,
                reversal_of_source_id=reversal_of_source_id,
            )
    except IntegrityError as exc:
        raise LedgerError(
            f"Journal entry could not be saved because a database constraint "
            f"was violated: {exc.orig}"
        ) from exc


def create_journal_entry_in_transaction(
    db: Session,
    entry: JournalEntryInput,
    lines: Sequence[JournalLineInput],
    *,
    reversal_of_source_id: str | None = None,
) -> JournalEntry:
    """Create and post an entry inside a transaction owned by the caller."""
    if not db.in_transaction():
        raise LedgerError(
            "create_journal_entry_in_transaction requires an active transaction."
        )
    return _create_journal_entry_in_transaction(
        db,
        entry,
        lines,
        reversal_of_source_id=reversal_of_source_id,
    )


def reverse_journal_entry(
    db: Session,
    original_entry_id: str,
    reversal_entry: JournalEntryInput,
    reversal_line_ids: Sequence[str],
) -> JournalEntry:
    """Post exact opposite lines for a correction to a posted entry."""
    if db.in_transaction():
        raise LedgerError(
            "reverse_journal_entry requires a Session with no active transaction."
        )
    try:
        with db.begin():
            return reverse_journal_entry_in_transaction(
                db,
                original_entry_id,
                reversal_entry,
                reversal_line_ids,
            )
    except IntegrityError as exc:
        raise LedgerError(
            f"Reversal could not be saved because a database constraint "
            f"was violated: {exc.orig}"
        ) from exc


def reverse_journal_entry_in_transaction(
    db: Session,
    original_entry_id: str,
    reversal_entry: JournalEntryInput,
    reversal_line_ids: Sequence[str],
) -> JournalEntry:
    """Reverse a posted entry inside a transaction owned by the caller."""
    if not db.in_transaction():
        raise LedgerError(
            "reverse_journal_entry_in_transaction requires an active transaction."
        )
    original = db.scalar(
        select(JournalEntry)
        .options(selectinload(JournalEntry.lines))
        .where(JournalEntry.entry_id == original_entry_id)
    )
    if original is None:
        raise LedgerError(
            f"Journal entry {original_entry_id} does not exist."
        )
    if original.status != "POSTED":
        raise LedgerError("Only posted journal entries can be reversed.")
    if original.source_id is None:
        raise LedgerError(
            "The original journal entry has no source ID to reference."
        )
    if len(reversal_line_ids) != len(original.lines):
        raise LedgerError(
            "A reversal requires one new line ID for each original line."
        )

    reversal_lines = [
        JournalLineInput(
            line_id=line_id,
            line_no=original_line.line_no,
            account_code=original_line.account_code,
            debit=original_line.credit,
            credit=original_line.debit,
            cost_center_department_id=original_line.cost_center_department_id,
            line_description=original_line.line_description,
        )
        for original_line, line_id in zip(original.lines, reversal_line_ids)
    ]
    return _create_journal_entry_in_transaction(
        db,
        reversal_entry,
        reversal_lines,
        reversal_of_source_id=original.source_id,
    )


def account_balance(
    db: Session,
    account: ChartOfAccount | str,
    as_of_date: date,
) -> Decimal:
    """Return the normal-side balance through the given date, including children."""
    account_code = (
        account.account_code if isinstance(account, ChartOfAccount) else account
    )
    accounts = db.scalars(select(ChartOfAccount)).all()
    account_by_code = {item.account_code: item for item in accounts}
    selected = account_by_code.get(account_code)
    if selected is None:
        raise LedgerError(f"Unknown account code: {account_code}.")

    children_by_parent: dict[str, list[str]] = {}
    for item in accounts:
        if item.parent_code is not None:
            children_by_parent.setdefault(item.parent_code, []).append(
                item.account_code
            )

    included_codes = {account_code}
    pending = [account_code]
    while pending:
        for child_code in children_by_parent.get(pending.pop(), []):
            if child_code not in included_codes:
                included_codes.add(child_code)
                pending.append(child_code)

    debit_total, credit_total = db.execute(
        select(
            func.coalesce(func.sum(JournalLine.debit), 0),
            func.coalesce(func.sum(JournalLine.credit), 0),
        )
        .join(JournalEntry, JournalEntry.entry_id == JournalLine.entry_id)
        .where(
            JournalEntry.status == "POSTED",
            JournalEntry.entry_date <= as_of_date,
            JournalLine.account_code.in_(included_codes),
        )
    ).one()
    debit_total = Decimal(str(debit_total))
    credit_total = Decimal(str(credit_total))
    if selected.normal_balance == "DEBIT":
        return debit_total - credit_total
    if selected.normal_balance == "CREDIT":
        return credit_total - debit_total
    raise LedgerError(
        f"Account {selected.account_code} has an invalid normal balance."
    )
