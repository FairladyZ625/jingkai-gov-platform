"""CSV 使用业务字段名作表头，复合字段用 JSON 单元格。"""
import csv
import io
import json

from .company import Enterprise, InvalidRow


class UnrecoverableCsv(InvalidRow):
    """引号未闭合等无法判定后续记录边界的文件级错误。"""

COMPLEX = {"formerNames", "tags", "license", "contacts", "amounts", "revenue",
           "qualifications", "fieldStatus"}


def rows(text):
    source = csv.reader(io.StringIO(text.removeprefix("\ufeff"), newline=""), strict=True)
    header = next(source, [])
    if ("name" not in header or len(set(header)) != len(header)
            or set(header) - Enterprise.model_fields.keys()):
        raise InvalidRow("表头必须包含 name，且字段须有效、唯一")
    while True:
        start = source.line_num + 1
        try:
            cells = next(source)
        except StopIteration:
            return
        except csv.Error as exc:
            raise UnrecoverableCsv(
                f"第 {start} 行起 CSV 格式错误，无法判断后续记录边界，已拒绝整份文件"
            ) from exc
        if len(cells) != len(header):
            yield start, None, "字段数量与表头不符"
            continue
        row = dict(zip(header, cells))
        try:
            for key in COMPLEX.intersection(row):
                if row[key]:
                    row[key] = json.loads(row[key])
                else:
                    del row[key]
            for key in ("employees", "yearsInZone", "lastVisitDays", "regInZone"):
                if row.get(key) == "":
                    del row[key]
        except ValueError:
            yield start, None, "复合字段需要 JSON"
            continue
        yield start, row, None


def render(items):
    fields = [key for key in Enterprise.model_fields if any(key in item for item in items)] or ["name"]
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(fields)
    for item in items:
        cells = []
        for key in fields:
            value = item.get(key, "")
            if isinstance(value, (list, dict, bool)):
                value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            value = str(value)
            if value.startswith(("\t", "\r", "\n")) or value.lstrip().startswith(("=", "+", "-", "@", "＝", "＋", "－", "＠")):
                value = "'" + value
            cells.append(value)
        writer.writerow(cells)
    return {"filename": "企业台账.csv", "csv": stream.getvalue()}
