from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class TaxSlabOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    slab_id: str
    regime: str
    financial_year: str
    income_from: Decimal
    income_to: Decimal | None
    rate_percent: Decimal
    effective_from: date
    note: str | None


class TaxSlabUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rate_percent: Decimal = Field(
        ge=0, le=100, max_digits=7, decimal_places=4
    )
    effective_from: date


class TaxParameterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    parameter: str
    effective_from: date | None
    value: Decimal
    note: str | None


class TaxParameterUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: Decimal = Field(ge=0, max_digits=18, decimal_places=4)
    effective_from: date


class StatutoryRateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    parameter: str
    value: Decimal
    unit: str
    note: str | None
    effective_from: date


class StatutoryRateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: Decimal = Field(ge=0, max_digits=18, decimal_places=4)
    effective_from: date
    source_note: str = Field(min_length=1, max_length=300)
