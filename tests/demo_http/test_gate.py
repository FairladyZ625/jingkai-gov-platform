from pathlib import Path
from xml.etree import ElementTree as XML
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "web/config/demo-script.js"


@pytest.mark.parametrize("change,expected", [
    ("all", 0), ("skip", 1), ("failure", 1), ("missing", 1), ("duplicate", 1), ("unknown", 1),
])
def test_twelve_names_and_results(tmp_path, change, expected):
    import re

    titles = re.findall(r"\{ title: '([^']+)', steps:", SCRIPT.read_text(encoding="utf-8"))
    suite = XML.Element("testsuite")
    for title in titles:
        case = XML.SubElement(suite, "testcase", name=f"test_segment[{title}]")
    if change in {"skip", "failure"}:
        XML.SubElement(case, "skipped" if change == "skip" else "failure")
    elif change == "missing":
        suite.remove(case)
    elif change == "duplicate":
        case.set("name", suite[0].get("name"))
    elif change == "unknown":
        case.set("name", "test_segment[未知]")
    path = tmp_path / "result.xml"
    XML.ElementTree(suite).write(path, encoding="utf-8")
    result = subprocess.run([sys.executable, str(Path(__file__).with_name("check_segments.py")), str(path)])
    assert result.returncode == expected
