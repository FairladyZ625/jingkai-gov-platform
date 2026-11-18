import pytest

from scripts import check


@pytest.mark.parametrize(("path", "source", "codes"), [
    ("enterprise/api/ledger_store.py", 'import sqlite3\np = os.environ["JKQ_ENTERPRISE_PRIVATE_DB"]', []),
    ("enterprise/api/ledger_store.py", 'p = os.environ["OTHER"]', ["CHK-APP-12"]),
    ("enterprise/api/ledger_store.py", 'os.environ["JKQ_ENTERPRISE_PRIVATE_DB"] = "x"', ["CHK-APP-12"]),
    ("enterprise/api/ledger_store.py", 'del os.environ["JKQ_ENTERPRISE_PRIVATE_DB"]', ["CHK-APP-12"]),
    ("enterprise/api/ledger_store.py", 'from os import environ', ["CHK-APP-12"]),
    ("enterprise/api/ledger_store.py", 'import subprocess', ["CHK-APP-10"]),
    ("enterprise/api/other.py", 'import sqlite3\np = os.environ["JKQ_ENTERPRISE_PRIVATE_DB"]',
     ["CHK-APP-10", "CHK-APP-12"]),
    ("other/api/ledger_store.py", 'import sqlite3\np = os.environ["JKQ_ENTERPRISE_PRIVATE_DB"]',
     ["CHK-APP-10", "CHK-APP-12"]),
])
def test_private_store_exception(tmp_path, monkeypatch, path, source, codes):
    monkeypatch.setattr(check, "ROOT", tmp_path)
    module = tmp_path / "apps" / path
    module.parent.mkdir(parents=True)
    module.write_text(source, encoding="utf-8")
    report = check.Report()
    check._check_backend(report, module.parents[1])
    assert [message.split("[")[1].split("]")[0] for message in report.errors] == codes
