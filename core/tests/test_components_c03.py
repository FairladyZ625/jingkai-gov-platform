"""C03 对表计算：正常样例、出错样例、单位换算与公式留痕。"""
import pytest

from haiknow_sdk.preview.components import c03

LEFT = """code,name,qty
M-01A,螺栓,500 g
M-02,螺母,2
M-03,垫片,3
"""

RIGHT = """code,name,qty
M-01,螺栓,0.5 kg
M-02,螺母,2
M-03,垫片,3.5
"""

BAD_LEFT = """code,name,qty
M-01,螺栓,500 g
M-01,螺栓,500 g
M-02,螺母,2 箱
M-03,垫片,3
"""

UNITS = {"kg": 1, "g": 0.001}
ALIASES = {"M-01A": "M-01"}
COMPARE = (c03.Compare("qty", unit="kg", tolerance=0.01),)


def codes(result):
    return [issue.code for issue in result.errors]


def test_read_csv_normal_and_bom():
    table = c03.read_csv("\ufeffcode,name\nM-1,螺栓\n\nM-2,螺母\n")
    assert table.ok is True
    assert table.columns == ["code", "name"]
    assert table.rows == [{"code": "M-1", "name": "螺栓"}, {"code": "M-2", "name": "螺母"}]
    # 文件行号：表头第 1 行，数据第 2、4 行（空行跳过但行号保留）
    assert table.row_numbers == [2, 4]


def test_read_csv_tab_delimiter():
    table = c03.read_csv("code\tqty\nM-1\t2\n", delimiter="\t")
    assert table.ok is True and table.rows[0]["qty"] == "2"


def test_read_csv_errors():
    assert codes(c03.read_csv("")) == ["empty_table"]
    assert codes(c03.read_csv("code,qty\n")) == ["empty_table"]
    assert codes(c03.read_csv("code,qty\nM-1,1,extra\n")) == ["row_columns"]
    assert codes(c03.read_csv("code,,qty\nM-1,1,2\n")) == ["bad_header"]
    assert codes(c03.read_csv("code,code\n1,2\n")) == ["bad_header"]


def test_reconcile_normal_by_alias_and_units():
    result = c03.reconcile(
        c03.read_csv(LEFT), c03.read_csv(RIGHT),
        on="code", aliases=ALIASES, compare=COMPARE, units=UNITS,
    )

    assert result.ok is True
    assert len(result.matches) == 3
    assert result.only_left == [] and result.only_right == []
    assert result.duplicates == {"left": [], "right": []}

    diffs = [diff for match in result.matches for diff in match.diffs]
    assert [diff.status for diff in diffs] == ["same", "same", "diff"]
    assert diffs[0].left == 0.5 and diffs[0].right == 0.5 and diffs[0].delta == 0
    assert diffs[2].delta == 0.5 and diffs[2].unit == "kg"


def test_reconcile_duplicate_key_and_unknown_unit():
    result = c03.reconcile(
        c03.read_csv(BAD_LEFT), c03.read_csv(RIGHT),
        on="code", aliases=ALIASES, compare=COMPARE, units=UNITS,
    )

    assert result.ok is False
    assert sorted(codes(result)) == ["duplicate_key", "unit_unknown"]
    assert result.duplicates["left"] == ["M-01"]
    assert result.duplicates["right"] == []
    # 重复键不参与匹配；右表 M-01 变成仅右
    assert [row["code"] for row in result.only_right] == ["M-01"]
    # 错单位的行仍出现在匹配里，但该列标 error
    m02 = next(match for match in result.matches if match.key == "M-02")
    assert m02.diffs[0].status == "error" and m02.diffs[0].delta is None


def test_reconcile_empty_key_and_empty_value():
    empty_key = c03.reconcile(
        c03.read_csv("code,qty\n,1\nM-2,2\n"), c03.read_csv("code,qty\nM-2,2\n"),
        on="code", compare=COMPARE, units=UNITS,
    )
    assert "empty_key" in codes(empty_key)

    empty_value = c03.reconcile(
        c03.read_csv("code,qty\nM-1,\n"), c03.read_csv("code,qty\nM-1,2\n"),
        on="code", compare=COMPARE, units=UNITS,
    )
    assert "empty_value" in codes(empty_value)
    assert empty_value.matches[0].diffs[0].status == "error"


def test_reconcile_no_column():
    result = c03.reconcile(
        c03.read_csv("code,qty\nM-1,1\n"), c03.read_csv("code,qty\nM-1,1\n"),
        on="code", compare=(c03.Compare("price"),), units=UNITS,
    )
    assert codes(result) == ["no_column"]


def test_reconcile_without_units_rejects_unit_text():
    result = c03.reconcile(
        c03.read_csv("code,qty\nM-1,500 g\n"), c03.read_csv("code,qty\nM-1,0.5\n"),
        on="code", compare=COMPARE,
    )
    assert "unit_unknown" in codes(result)


def test_reconcile_stops_on_table_errors():
    broken = c03.read_csv("code,qty\nM-1,1,extra\n")
    result = c03.reconcile(broken, c03.read_csv(RIGHT), on="code", compare=COMPARE, units=UNITS)
    assert result.ok is False and result.matches == []
    assert codes(result) == ["row_columns"]


def test_calculate_normal_and_trace_inputs():
    calc = c03.calculate(
        c03.read_csv(LEFT), (c03.Formula("amount", "qty * 2", unit="元"),), units=UNITS,
    )

    assert calc.ok is True
    assert [row["amount"] for row in calc.rows] == [1, 4, 6]
    first = calc.traces[0]
    assert first.row == 2 and first.name == "amount" and first.expr == "qty * 2"
    assert first.result == 1 and first.unit == "元"
    assert first.inputs == {"qty": 0.5}


def test_calculate_chains_formulas_and_functions():
    calc = c03.calculate(
        c03.read_csv("qty\n3\n"), (
            c03.Formula("a", "qty + 1"),
            c03.Formula("b", "round(a / 3, 2)"),
            c03.Formula("c", "max(min(b, 10), 0)"),
            c03.Formula("d", "abs(qty - 5)"),
        ),
    )

    assert calc.ok is True
    assert calc.rows[0]["a"] == 4 and calc.rows[0]["b"] == 1.33
    assert calc.rows[0]["c"] == 1.33 and calc.rows[0]["d"] == 2
    assert calc.traces[1].inputs == {"a": 4}


def test_calculate_formula_errors():
    unknown = c03.calculate(c03.read_csv("qty\n2\n"), (c03.Formula("x", "qty * price"),))
    assert codes(unknown) == ["unknown_name"]

    zero = c03.calculate(c03.read_csv("qty\n2\n"), (c03.Formula("x", "qty / 0"),))
    assert codes(zero) == ["divide_by_zero"]

    huge = c03.calculate(c03.read_csv("qty\n2\n"), (c03.Formula("x", "qty ** 2000"),))
    assert codes(huge) == ["formula_error"]

    syntax = c03.calculate(c03.read_csv("qty\n2\n"), (c03.Formula("x", "qty *"),))
    assert codes(syntax) == ["formula_error"]

    not_number = c03.calculate(c03.read_csv("qty\nabc\n"), (c03.Formula("x", "qty * 2"),))
    assert codes(not_number) == ["not_number"]


def test_calculate_rejects_unsafe_syntax():
    calc = c03.calculate(c03.read_csv("qty\n2\n"), (c03.Formula("x", "__import__('os').system('id')"),))
    assert codes(calc) == ["formula_error"]


def test_formula_contract_errors():
    with pytest.raises(ValueError, match="合法标识符"):
        c03.Formula("a-b", "qty * 2")
    with pytest.raises(ValueError, match="不能为空"):
        c03.Formula("x", "  ")
    with pytest.raises(ValueError, match="tolerance"):
        c03.Compare("qty", tolerance=-1)


def test_reconcile_to_dict_shape():
    result = c03.reconcile(
        c03.read_csv(LEFT), c03.read_csv(RIGHT),
        on="code", aliases=ALIASES, compare=COMPARE, units=UNITS,
    )
    data = result.to_dict()
    assert set(data) == {"ok", "matches", "only_left", "only_right", "duplicates", "errors"}
    assert data["matches"][0]["diffs"][0]["status"] == "same"

def test_reconcile_preserves_large_integers():
    result = c03.reconcile(
        [{"id": "a", "n": 9007199254740993}],
        [{"id": "a", "n": 9007199254740992}],
        on="id", compare=(c03.Compare("n"),),
    )

    assert result.ok is True
    diff = result.matches[0].diffs[0]
    assert diff.left == 9007199254740993
    assert diff.right == 9007199254740992
    assert diff.delta == -1 and diff.status == "diff"


def test_reconcile_overflow_is_an_issue_not_an_exception():
    result = c03.reconcile(
        [{"id": "a", "n": "1e309"}], [{"id": "a", "n": "1"}],
        on="id", compare=(c03.Compare("n"),),
    )

    assert result.ok is False
    assert [issue.code for issue in result.errors] == ["not_number"]
    assert result.matches[0].diffs[0].status == "error"
    assert result.matches[0].diffs[0].left is None


def test_reconcile_unit_conversion_overflow_is_an_issue():
    # 1e309 本身超出 float 可表示范围；在换算前就应报 not_number
    result = c03.reconcile(
        [{"id": "a", "n": "1e309 kg"}], [{"id": "a", "n": "1 kg"}],
        on="id", compare=(c03.Compare("n"),), units={"kg": 1},
    )

    assert result.ok is False
    assert {issue.code for issue in result.errors} == {"not_number"}
    assert result.matches[0].diffs[0].status == "error"


def test_reconcile_unit_conversion_preserves_huge_integral_values():
    # 1e308 kg × 1000 = 1e311，整数可精确表示，不应误报溢出
    result = c03.reconcile(
        [{"id": "a", "n": "1e308 kg"}], [{"id": "a", "n": "1e308 kg"}],
        on="id", compare=(c03.Compare("n", unit="kg"),), units={"kg": 1000},
    )

    assert result.ok is True
    diff = result.matches[0].diffs[0]
    assert diff.left == 10 ** 311 and diff.right == 10 ** 311
    assert diff.status == "same"


def test_calculate_keeps_small_decimals_exact():
    calc = c03.calculate(
        [{"qty": "0.00000000001"}], (c03.Formula("out", "qty * 2"),),
    )
    assert calc.ok is True
    assert calc.traces[0].result == 2e-11
    assert calc.traces[0].inputs == {"qty": 1e-11}

    converted = c03.calculate(
        [{"qty": "0.00000000001 g"}], (c03.Formula("out", "qty * 2"),),
        units={"kg": 1, "g": 0.001},
    )
    assert converted.ok is True
    assert converted.traces[0].result == 2e-14
    assert converted.traces[0].inputs == {"qty": 1e-14}


def test_calculate_overflow_is_an_issue():
    calc = c03.calculate([{"qty": "1e309"}], (c03.Formula("out", "qty * 2"),))
    assert calc.ok is False
    assert [issue.code for issue in calc.errors] == ["not_number"]


def test_read_csv_strict_parsing_errors():
    unclosed = c03.read_csv('id,qty\na,"2')
    assert unclosed.ok is False
    assert [issue.code for issue in unclosed.errors] == ["csv_error"]
    assert unclosed.errors[0].row == 2

    oversized = c03.read_csv("id,qty\na," + "2" * 131073)
    assert oversized.ok is False
    assert [issue.code for issue in oversized.errors] == ["csv_error"]

    # 合法引号（含逗号）仍应正常解析
    quoted = c03.read_csv('id,name\n1,"a, b"')
    assert quoted.ok is True and quoted.rows[0]["name"] == "a, b"


def test_reconcile_huge_int_vs_float_does_not_overflow():
    result = c03.reconcile(
        [{"id": "a", "n": 10 ** 400}], [{"id": "a", "n": 1.5}],
        on="id", compare=(c03.Compare("n"),),
    )

    assert result.ok is True
    diff = result.matches[0].diffs[0]
    assert diff.status == "diff" and diff.delta is None


def test_oversized_numeric_string_is_an_issue_not_an_exception():
    result = c03.reconcile(
        [{"id": "a", "n": "9" * 5000}], [{"id": "a", "n": 1}],
        on="id", compare=(c03.Compare("n"),),
    )
    assert result.ok is False
    assert [issue.code for issue in result.errors] == ["not_number"]
    assert result.matches[0].diffs[0].status == "error"


def test_unit_conversion_preserves_large_integers():
    # 大整数 × 非 1 整数系数：先做精确十进制换算，再对表
    result = c03.reconcile(
        [{"id": "a", "qty": "9007199254740993 g"}],
        [{"id": "a", "qty": "9007199254740992 g"}],
        on="id", compare=(c03.Compare("qty", unit="u", tolerance=0),), units={"g": 2},
    )
    diff = result.matches[0].diffs[0]
    assert diff.left == 18014398509481986
    assert diff.right == 18014398509481984
    assert diff.delta == -2 and diff.status == "diff"

    # 系数 1 不转换，大整数原样参与比较
    exact = c03.reconcile(
        [{"id": "a", "qty": "100000000000000000100 g"}],
        [{"id": "a", "qty": "100000000000000000000 g"}],
        on="id", compare=(c03.Compare("qty", unit="g", tolerance=0),), units={"g": 1},
    )
    assert exact.matches[0].diffs[0].delta == -100
    assert exact.matches[0].diffs[0].status == "diff"


def test_unit_conversion_that_cannot_be_exact_is_rejected():
    # 100000000000000000100 g = 100000000000000000.1 kg；float 无法无损表示，必须报错
    result = c03.reconcile(
        [{"id": "a", "qty": "100000000000000000100 g"}],
        [{"id": "a", "qty": "100000000000000000000 g"}],
        on="id", compare=(c03.Compare("qty", unit="kg", tolerance=0.01),),
        units={"g": 0.001, "kg": 1},
    )
    assert result.ok is False
    assert [issue.code for issue in result.errors] == ["not_number"]
    assert "换算后精度" in result.errors[0].message
    diff = result.matches[0].diffs[0]
    assert diff.status == "error" and diff.delta is None


def test_calculate_unit_conversion_precision_is_not_silent():
    calc = c03.calculate(
        [{"qty": "100000000000000000100 g"}],
        (c03.Formula("out", "qty * 2"),),
        units={"g": 0.001, "kg": 1},
    )
    assert calc.ok is False
    assert [issue.code for issue in calc.errors] == ["not_number"]
