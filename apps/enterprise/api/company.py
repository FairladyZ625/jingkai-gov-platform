"""企业字段与对外投影，供台账和后续走访、诉求接口复用。"""
from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class Enterprise(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    name: str
    short: str = ""
    creditCode: str = ""
    formerNames: list[str] = Field(default_factory=list)
    industry: str = ""
    scale: str = ""
    tags: list[str] = Field(default_factory=list)
    license: list[str] = Field(default_factory=list)
    subjectType: str = ""
    established: str = ""
    yearsInZone: int = 0
    regInZone: bool = True
    employees: int = 0
    revenue: dict[str, str | float] = Field(default_factory=dict)
    amounts: dict[str, str | float] = Field(default_factory=dict)
    addr: str = ""
    regAddr: str = ""
    opAddr: str = ""
    contact: str = ""
    phone: str = ""
    contacts: list[dict[str, str | bool]] = Field(default_factory=list)
    servicer: str = ""
    lastVisit: str = ""
    lastVisitDays: int = 0
    qualifications: list[dict[str, str]] = Field(default_factory=list)
    products: str = ""
    fieldStatus: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("企业名称不能为空")
        return value


class InvalidRow(ValueError):
    pass


class Duplicate(InvalidRow):
    pass


def validate(row):
    try:
        return Enterprise.model_validate(row).model_dump(exclude_unset=True)
    except ValidationError as exc:
        field = exc.errors(include_input=False)[0]["loc"][0]
        raise InvalidRow(f"字段 {field} 缺失或格式错误") from None


def public(row):
    # #14 的接口适配点。所有 HTTP、历史和核心版本共用此边界。
    result = dict(row)

    def phone(value):
        return value[:3] + "****" + value[-4:] if len(value) > 7 else "****"

    if row.get("phone"):
        result["phone"] = phone(row["phone"])
    if "contacts" in row:
        result["contacts"] = [
            {**person, "phone": phone(str(person["phone"]))} if person.get("phone") else person
            for person in row["contacts"]
        ]
    if "amounts" in row:
        result["amounts"] = {key: "****" for key in row["amounts"]}
    if "revenue" in row and "value" in row["revenue"]:
        result["revenue"] = {**row["revenue"], "value": "****"}
    return result


def has_alert(row, today):
    if row.get("lastVisitDays", 0) > 90 and (
        row.get("scale") != "微型" or "重点服务" in row.get("tags", [])
    ):
        return True
    for item in row.get("qualifications", []):
        try:
            expires = date.fromisoformat(item.get("validTo", ""))
        except ValueError:
            continue
        if today <= expires <= today + timedelta(days=60):
            return True
    return False
