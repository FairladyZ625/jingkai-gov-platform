"""C01/C02/C03/C04/C06/C07 的 Python 与前端版本号必须一致且是 semver。"""
import re
from pathlib import Path

from haiknow_sdk.preview.components import c01, c02, c03, c04, c06, c07
from haiknow_sdk.preview.components import common

ROOT = Path(__file__).resolve().parents[2]
JS_DIR = ROOT / "core" / "sdk" / "js" / "preview" / "components"
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def test_python_and_js_versions_match():
    python_versions = {"c01": c01.VERSION, "c02": c02.VERSION, "c03": c03.VERSION, "c04": c04.VERSION, "c06": c06.VERSION, "c07": c07.VERSION}
    js_versions = {}
    for name in python_versions:
        text = (JS_DIR / f"{name}.js").read_text(encoding="utf-8")
        match = re.search(r"export const VERSION = '([^']+)'", text)
        assert match, f"{name}.js 缺少 VERSION"
        js_versions[name] = match.group(1)

    assert python_versions == js_versions
    assert common.VERSION == c01.VERSION


def test_versions_are_semver():
    for version in (c01.VERSION, c02.VERSION, c03.VERSION, c04.VERSION, c06.VERSION, c07.VERSION, common.VERSION):
        assert SEMVER.match(version), version