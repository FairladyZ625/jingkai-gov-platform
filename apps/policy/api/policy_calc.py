"""用 SDK C03 的受限公式对政策金额试算。"""

from __future__ import annotations

import math
from decimal import Decimal

from haiknow_sdk.preview.components.c03 import Formula, calculate


def positive_amount(value: object) -> bool:
    return type(value) in (int, float) and 0 < value < math.inf


def _number(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _money(value: int | float | Decimal) -> str:
    amount = Decimal(str(value))
    if amount >= 10000:
        return f"{_number(amount / 10000)} 万元"
    return f"{_number(amount)} 元"


def estimate(rule: dict, base: int | float | None) -> dict | None:
    if rule.get("manual"):
        return None
    if "fixed" in rule:
        amount = rule["fixed"]
        up_to = bool(rule.get("upTo"))
        label = "最高" if up_to else "定额"
        return {"amount": amount, "kind": "fixed", "text": f"{label} {_money(amount)}", "capped": False, "upTo": up_to}
    if not rule.get("base") or "ratio" not in rule or not positive_amount(base):
        return None

    ratio = Decimal(str(rule["ratio"]))
    base_number, base_scale = Decimal(str(base)).as_integer_ratio()
    rate_number, rate_scale = ratio.as_integer_ratio()
    scale = base_scale * rate_scale
    values = {"base": base_number, "rate": rate_number}
    # 将比例结果和封顶额按同一分母换算成整数，精确比较等于或超过封顶。
    formulas = [Formula("raw", "base * rate")]
    cap = rule.get("cap")
    if cap is not None:
        cap_number, cap_scale = Decimal(str(cap)).as_integer_ratio()
        values["base"] *= cap_scale
        values["cap"] = cap_number * scale
        scale *= cap_scale
        formulas.append(Formula("payable", "min(raw, cap)"))
    computed = calculate([values], formulas)
    if not computed.ok:
        return None
    numbers = computed.rows[0]
    raw = numbers["raw"]
    capped = cap is not None and raw > values["cap"]
    text = f"{_money(base)} × {_number(ratio * 100)}% = {_money(Decimal(raw) / scale)}"
    if capped:
        text += f"，超过封顶，按 {_money(cap)}"
    quotient, remainder = divmod(numbers.get("payable", raw), scale)
    amount = float(Decimal(quotient) + Decimal(remainder) / scale) if remainder else quotient
    return {"amount": amount, "base": base, "kind": "ratio", "text": text, "capped": capped}
