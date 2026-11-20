"""检查规则测试：每个反例都被拦下，现有应用保持全绿，规则目录与实现不漂移。"""
from __future__ import annotations

import ast
import importlib.util
import json
import re
import shutil
from datetime import date
from pathlib import Path

import pytest

from conftest import ROOT


def _load_check():
    spec = importlib.util.spec_from_file_location("repo_check", ROOT / "scripts" / "check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check = _load_check()
FIXTURES = ROOT / "tests" / "fixtures" / "bad-app"
CODE = re.compile(r"\[(CHK-[A-Z]+-\d{2})\]")


@pytest.fixture
def fixture_root(monkeypatch):
    """把门的仓库根指到夹具目录，夹具里没有 .git，files() 自动走全量扫描。"""
    monkeypatch.setattr(check, "ROOT", FIXTURES)
    return FIXTURES


def run(gate: str, app: str | None = None):
    report = check.Report()
    check.CHECKS[gate](report, app)
    return report


def codes(report) -> set[str]:
    return {m.group(1) for e in report.errors for m in [CODE.search(e)] if m}


def message(report, code: str) -> str:
    return next(e for e in report.errors if f"[{code}]" in e)


def test_error_format_is_location_code_problem_fix(fixture_root):
    report = run("manifest", "bad-json")
    assert re.fullmatch(r"apps/bad-json/app\.json:\d+ \[CHK-APP-02\] .+ → .+", report.errors[0])


def test_manifest_missing_file(fixture_root):
    assert codes(run("manifest", "no-manifest")) == {"CHK-APP-01"}


def test_manifest_invalid_json(fixture_root):
    assert codes(run("manifest", "bad-json")) == {"CHK-APP-02"}


def test_manifest_json_not_object(fixture_root):
    assert codes(run("manifest", "bad-root")) == {"CHK-APP-02"}


def test_manifest_required_field(fixture_root):
    report = run("manifest", "bad-manifest")
    assert "CHK-APP-03" in codes(report) and "owner" in message(report, "CHK-APP-03")


def test_owner_empty_rejected(fixture_root):
    report = run("manifest", "empty-owner")
    assert {"CHK-APP-03", "CHK-APP-06"} <= codes(report)
    assert "不能为空" in message(report, "CHK-APP-03")
    assert any(re.search(r"empty-owner/app\.json:\d+ \[CHK-APP-03\]", e) for e in report.errors)


def test_manifest_requires_sdk_declaration(fixture_root):
    report = run("manifest", "legacy-no-sdk")
    assert codes(report) == {"CHK-APP-03"}
    assert "sdk" in message(report, "CHK-APP-03")


def test_manifest_invalid_value(fixture_root):
    report = run("manifest", "bad-values")
    assert "CHK-APP-04" in codes(report)


def test_module_requires_web_entry(fixture_root):
    assert "CHK-APP-05" in codes(run("manifest", "no-web"))


def test_owner_missing_from_codeowners(fixture_root):
    report = run("manifest", "unregistered")
    assert codes(report) == {"CHK-APP-06"}
    assert "/apps/unregistered/" in message(report, "CHK-APP-06")


def test_owner_mismatch_with_codeowners(fixture_root):
    report = run("manifest", "other-owner")
    assert codes(report) == {"CHK-APP-06"}
    assert "不一致" in message(report, "CHK-APP-06")


def test_readme_missing(fixture_root):
    assert codes(run("readme", "no-readme")) == {"CHK-APP-07"}


def test_readme_missing_section(fixture_root):
    assert "CHK-APP-08" in codes(run("readme", "bad-readme"))


def test_readme_empty_section(fixture_root):
    assert "CHK-APP-09" in codes(run("readme", "bad-readme"))


def test_backend_forbidden_import(fixture_root):
    assert "CHK-APP-10" in codes(run("boundary", "bad-backend"))


def test_backend_unlisted_dependency(fixture_root):
    assert "CHK-APP-11" in codes(run("boundary", "bad-backend"))


def test_backend_environment_access(fixture_root):
    assert "CHK-APP-12" in codes(run("boundary", "bad-backend"))


def test_backend_syntax_error(fixture_root):
    assert codes(run("boundary", "bad-syntax")) == {"CHK-APP-13"}


def test_backend_sdk_private_attributes_and_dynamic_getattr_rejected(fixture_root):
    report = run("boundary", "private-sdk")
    assert codes(report) == {"CHK-APP-14"}
    assert len(report.errors) == 2
    assert all("CHK-BOUNDARY" in item for item in report.errors)


def test_frontend_import_whitelist(fixture_root):
    assert "CHK-WEB-01" in codes(run("boundary", "bad-web"))


def test_frontend_relative_import_escape(fixture_root):
    assert "CHK-WEB-02" in codes(run("boundary", "bad-web"))


def test_frontend_direct_fetch(fixture_root):
    report = run("boundary", "bad-web")
    fetch_errors = [e for e in report.errors if "[CHK-WEB-03]" in e]
    assert len(fetch_errors) == 2
    assert any("/api/v1/" in e for e in fetch_errors)


def test_web_color_literals(fixture_root):
    report = run("boundary", "bad-style")
    assert sum("[CHK-WEB-04]" in e for e in report.errors) >= 2


def test_web_inline_style(fixture_root):
    report = run("boundary", "bad-style")
    assert sum("[CHK-WEB-05]" in e for e in report.errors) == 2


def test_style_allowlist_exempts_file(fixture_root, monkeypatch):
    monkeypatch.setattr(check, "STYLE_ALLOWED", {"apps/bad-style/web/index.js": "测试用白名单"})
    report = run("boundary", "bad-style")
    assert "CHK-WEB-05" not in codes(report)
    assert "CHK-WEB-04" in codes(report)


def _ui_repo(tmp_path, monkeypatch, *names, exemptions=None):
    """临时仓库根：夹具应用 + 真实组件/外壳 CSS + 可选豁免文件。"""
    root = tmp_path / "repo"
    for name in names:
        shutil.copytree(FIXTURES / "apps" / name, root / "apps" / name)
    for relpath in (check.UI_UI_CSS, check.UI_TOKENS_CSS, check.UI_SHELL_CSS):
        dst = root / relpath
        dst.parent.mkdir(parents=True, exist_ok=True)
        if relpath == check.UI_UI_CSS:
            shutil.copy(ROOT / relpath, dst)
        elif relpath == check.UI_SHELL_CSS:
            dst.write_text(f".hk-panel {{}}\n/* {check.UI_PUBLIC_SHELL_MARKER} */\n.hk-row {{}}\n.hk-card {{}}")
    if exemptions is not None:
        path = root / check.UI_EXEMPTIONS
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(exemptions, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(check, "ROOT", root)
    return root


def test_ui_entry_must_import_component(fixture_root):
    report = run("boundary", "bad-ui-import")
    assert "CHK-APP-15" in codes(report)
    assert "没有从 /sdk/ui/index.js 导入组件" in message(report, "CHK-APP-15")
    assert "§1.4" in message(report, "CHK-APP-15")


def test_ui_status_map_and_direct_literal_rejected(fixture_root):
    report = run("boundary", "bad-ui-status")
    status_errors = [e for e in report.errors if "[CHK-APP-16]" in e]
    assert len(status_errors) == 4, status_errors
    assert any("待审核" in e for e in status_errors)
    assert any("已退回" in e for e in status_errors)
    assert all("§4.1" in e for e in status_errors)
    assert not any("已导出 CSV" in e for e in report.errors), "toast 不是状态标签，不能误报"


def test_ui_class_must_exist_in_component_or_public_shell_styles(tmp_path, monkeypatch):
    _ui_repo(tmp_path, monkeypatch, "bad-ui-class")
    report = run("boundary", "bad-ui-class")
    text = "\n".join(report.errors)
    assert "[CHK-APP-17] 类名 hk-card" in text
    assert "[CHK-APP-17] 类名 hk-row" in text
    assert "hk-field" not in text, "hk-field 在 ui.css 里有定义，不能误报"
    assert "§1.4" in text


def test_ui_positive_fixture_passes(tmp_path, monkeypatch):
    _ui_repo(tmp_path, monkeypatch, "good-ui")
    assert run("boundary", "good-ui").errors == []


def test_ui_class_sources_exclude_legacy_shell_block(tmp_path, monkeypatch):
    root = _ui_repo(tmp_path, monkeypatch)
    defined = check._ui_defined_classes()
    assert "hk-panel" in defined
    assert "hk-card" not in defined and "hk-row" not in defined
    assert check.UI_PUBLIC_SHELL_MARKER in (root / check.UI_SHELL_CSS).read_text(encoding="utf-8")


def test_ui_import_requires_a_component_not_just_ensure_styles():
    imported = check._ui_component_imports("import { ensureStyles } from '/sdk/ui/index.js';")
    assert not (imported & check.UI_COMPONENTS)


def test_ui_exemption_active_on_expiry_day_then_red(tmp_path, monkeypatch):
    """豁免只到 expires 当天；夹具应用同时违反 15/16/17，次日三条都要转红。"""
    _ui_repo(
        tmp_path,
        monkeypatch,
        "bad-ui-all",
        exemptions={
            "apps/bad-ui-all": {
                "issue": "#60",
                "expires": "2026-11-14",
                "rules": list(check.UI_RULES),
            }
        },
    )
    monkeypatch.setattr(check, "_ui_today", lambda: date(2026, 11, 14))
    assert run("boundary", "bad-ui-all").errors == []
    monkeypatch.setattr(check, "_ui_today", lambda: date(2026, 11, 15))
    assert codes(run("boundary", "bad-ui-all")) == set(check.UI_RULES)


def test_ui_new_app_is_not_exempt(tmp_path, monkeypatch):
    """新应用没有豁免入口：不发豁免文件就必须报三条规则。"""
    _ui_repo(tmp_path, monkeypatch, "bad-ui-all")
    assert codes(run("boundary", "bad-ui-all")) == set(check.UI_RULES)


@pytest.mark.parametrize(
    "entry",
    [
        {"expires": "2026-11-14", "rules": list(check.UI_RULES)},
        {"issue": "#60", "rules": list(check.UI_RULES)},
    ],
    ids=["missing-issue", "missing-expiry"],
)
def test_ui_exemption_without_issue_or_expiry_is_ignored(tmp_path, monkeypatch, entry):
    _ui_repo(tmp_path, monkeypatch, "bad-ui-all", exemptions={"apps/bad-ui-all": entry})
    monkeypatch.setattr(check, "_ui_today", lambda: date(2026, 11, 7))
    assert codes(run("boundary", "bad-ui-all")) == set(check.UI_RULES)


def test_ui_exemption_is_per_rule(tmp_path, monkeypatch):
    _ui_repo(
        tmp_path,
        monkeypatch,
        "bad-ui-class",
        exemptions={
            "apps/bad-ui-class": {
                "issue": "#1",
                "expires": "2026-11-14",
                "rules": ["CHK-APP-15"],
            }
        },
    )
    monkeypatch.setattr(check, "_ui_today", lambda: date(2026, 11, 7))
    report = run("boundary", "bad-ui-class")
    assert "CHK-APP-17" in codes(report), "只豁免了 15，不能顺手放过 17"


def test_ui_exemptions_file_entries_are_well_formed():
    """真实豁免数据只校验格式；登记哪些应用、何时撤掉，不绑定任何应用当前是否违规。"""
    path = ROOT / check.UI_EXEMPTIONS
    if not path.is_file():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    for app, entry in data.items():
        assert re.fullmatch(r"apps/[a-z0-9-]+", app)
        assert isinstance(entry, dict), app
        assert re.fullmatch(r"#\d+", str(entry.get("issue", ""))), app
        date.fromisoformat(str(entry.get("expires", "")))
        rules = entry.get("rules")
        assert isinstance(rules, list) and rules, app
        assert set(rules) <= set(check.UI_RULES), app


def test_backend_without_tests(fixture_root):
    assert codes(_static_tests("no-tests")) == {"CHK-TEST-01"}


def test_tests_without_permission_case(fixture_root):
    assert codes(_static_tests("bad-tests")) == {"CHK-TEST-02"}


def test_fake_permission_case_rejected(fixture_root):
    assert codes(_static_tests("bad-tests-fake")) == {"CHK-TEST-02"}


@pytest.mark.parametrize(
    "source",
    [
        "def test_x(r):\n    assert not (r.status_code == 403)\n",
        "def test_x(r):\n    assert r.status_code == 403 or True\n",
        "def test_x(r):\n    assert (r.status_code == 403) is False\n",
        "def test_x(r):\n    assert False and r.status_code == 403\n",
        "def test_x(r):\n    pytest.raises(PermissionDenied)\n",
    ],
)
def test_permission_polarity_bypass_rejected(source):
    assert check._has_permission_case(ast.parse(source)) is False


@pytest.mark.parametrize(
    "source",
    [
        "def test_x(r):\n    assert r.status_code == 403\n",
        "def test_x(r):\n    assert 403 == r.status_code\n",
        "def test_x(r):\n    assert r.status_code == 403 and r.text\n",
        "def test_x(r):\n    with pytest.raises(PermissionDenied):\n        r.get('/x')\n",
        "def test_x(r):\n    with raises(PermissionDenied):\n        r.get('/x')\n",
    ],
)
def test_permission_positive_forms_accepted(source):
    assert check._has_permission_case(ast.parse(source)) is True


def test_owner_trailing_space_matches_codeowners(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    app = root / "apps" / "space-owner"
    (app / "web").mkdir(parents=True)
    (app / "web" / "index.js").write_text("export async function mount() {}\n", encoding="utf-8")
    (app / "app.json").write_text(
        '{"contract": 1, "sdk": "1", "id": "space-owner", "name": "尾随空格", "sector": "other", '
        '"kind": "module", "owner": "fixture-owner ", "status": "idea"}',
        encoding="utf-8",
    )
    (root / "CODEOWNERS").write_text("/apps/space-owner/ @fixture-owner\n", encoding="utf-8")
    monkeypatch.setattr(check, "ROOT", root)
    assert run("manifest", "space-owner").errors == []


def test_permission_assert_forms_accepted(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    app = root / "apps" / "ok"
    (app / "api").mkdir(parents=True)
    (app / "api" / "router.py").write_text("", encoding="utf-8")
    (app / "tests").mkdir()
    (app / "tests" / "test_api.py").write_text(
        "import pytest\n"
        "from haiknow_sdk import PermissionDenied\n\n"
        "def test_raises(client_for):\n"
        "    with pytest.raises(PermissionDenied):\n"
        "        client_for('ok').get('/x')\n\n"
        "def test_reverse(client_for):\n"
        "    assert 403 == client_for('ok').get('/x').status_code\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(check, "ROOT", root)
    assert _static_tests("ok").errors == []


def test_pytest_failure_reported(fixture_root, monkeypatch):
    class Result:
        returncode = 1

    monkeypatch.setattr(check.subprocess, "run", lambda *a, **k: Result())
    report = check.Report()
    check.check_tests(report, "bad-tests")
    assert "CHK-TEST-03" in codes(report)


def _static_tests(app: str):
    report = check.Report()
    check.check_test_files(report, app)
    return report


def test_large_app_file_rejected(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    app = root / "apps" / "big"
    app.mkdir(parents=True)
    (app / "data.bin").write_bytes(b"0" * (check.MAX_APP_FILE + 1))
    monkeypatch.setattr(check, "ROOT", root)
    report = run("size")
    assert codes(report) == {"CHK-REPO-01"}
    assert "超过 2MB" in report.errors[0]


def test_large_file_outside_apps_ignored(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "data.bin").write_bytes(b"0" * (check.MAX_APP_FILE + 1))
    monkeypatch.setattr(check, "ROOT", root)
    assert run("size").errors == []


def test_secret_file_rejected(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "apps" / "x").mkdir(parents=True)
    (root / "apps" / "x" / "key.txt").write_text("sk-" + "a" * 30, encoding="utf-8")
    monkeypatch.setattr(check, "ROOT", root)
    assert codes(run("secrets")) == {"CHK-REPO-03"}


def test_env_file_rejected(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".env").write_text("HAIKNOW_MODEL_API_KEY=x\n", encoding="utf-8")
    monkeypatch.setattr(check, "ROOT", root)
    assert codes(run("secrets")) == {"CHK-REPO-04"}


def test_harness_ledger_rejected(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "harness" / "task").mkdir(parents=True)
    (root / "harness" / "task" / "INDEX.md").write_text("x", encoding="utf-8")
    monkeypatch.setattr(check, "ROOT", root)
    assert codes(run("ledger")) == {"CHK-REPO-05"}


def test_dead_link_and_missing_docs_readme(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "docs" / "process").mkdir(parents=True)
    (root / "docs" / "README.md").write_text("# 文档索引\n", encoding="utf-8")
    (root / "docs" / "bad.md").write_text("[死链](不存在.md)\n", encoding="utf-8")
    monkeypatch.setattr(check, "ROOT", root)
    assert codes(run("docs")) == {"CHK-REPO-06", "CHK-REPO-07"}


def test_platform_path_classification():
    assert not check.is_platform_path("apps/sample-app/web/index.js")
    assert check.is_platform_path("apps/_template/app.json")
    assert check.is_platform_path("apps/README.md")
    assert check.is_platform_path("apps/_shared/theme.css")
    assert check.is_platform_path("core/server/haiknow_core/main.py")
    assert check.is_platform_path("CODEOWNERS")


def test_codeowners_lookup_follows_repository(tmp_path, monkeypatch):
    (tmp_path / "CODEOWNERS").write_text("/core/ @maintainer\n/apps/sample-app/ @tester\n")
    monkeypatch.setattr(check, "ROOT", tmp_path)
    assert check.codeowners_for("core/server/haiknow_core/main.py") == ["@maintainer"]
    assert check.codeowners_for("apps/sample-app/web/index.js") == ["@tester"]


def test_platform_change_emits_codeowners_notice(fixture_root, monkeypatch):
    monkeypatch.setattr(check, "changed_paths", lambda: ["core/server/haiknow_core/main.py", "docs/specs/检查规则.md"])
    report = run("owners")
    assert report.errors == []
    assert len(report.notices) == 1 and "[CHK-REPO-02]" in report.notices[0]
    assert "@fixture-owner" in report.notices[0]


def test_app_only_change_emits_no_notice(fixture_root, monkeypatch):
    monkeypatch.setattr(check, "changed_paths", lambda: ["apps/sample-app/web/index.js"])
    assert run("owners").notices == []


def test_missing_git_falls_back_to_notice(fixture_root, monkeypatch):
    monkeypatch.setenv("CI_MERGE_REQUEST_IID", "18")
    monkeypatch.setattr(check, "changed_paths", lambda: None)
    report = run("owners")
    assert report.errors == []
    assert "[CHK-REPO-02]" in report.notices[0] and "无法读取改动清单" in report.notices[0]


def test_missing_git_on_main_push_is_silent(fixture_root, monkeypatch):
    monkeypatch.delenv("CI_MERGE_REQUEST_IID", raising=False)
    monkeypatch.setattr(check, "changed_paths", lambda: None)
    assert run("owners").notices == []


def test_existing_apps_pass_application_rules(monkeypatch):
    # 固定在存量示例应用的豁免日内，避免 #65 迁移完成前后套件随日期变红；到期行为由夹具测试覆盖。
    monkeypatch.setattr(check, "_ui_today", lambda: date(2026, 11, 7))
    report = check.Report()
    check.check_manifest(report, None)
    check.check_readme(report, None)
    check.check_boundary(report, None)
    check.check_test_files(report, None)
    check.check_size(report, None)
    assert report.errors == []


CATALOG = ROOT / "docs" / "specs" / "检查规则.md"
LEGACY_CI_PREFIX = re.compile(r"(?<![A-Z])HK-(?:APP|WEB|REPO)-\d{2}")


def test_ci_rule_prefix_is_chk():
    """CI 侧只用 CHK-，旧前缀不得残留在门、目录、测试与夹具里。"""
    assert all(code.startswith("CHK-") for code in check.RULES)
    paths = [
        ROOT / "scripts" / "check.py",
        CATALOG,
        ROOT / "docs" / "specs" / "README.md",
        ROOT / "tests" / "test_check_rules.py",
        *sorted((ROOT / "tests" / "fixtures" / "bad-app").rglob("*")),
    ]
    for p in paths:
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        assert not LEGACY_CI_PREFIX.search(text), f"{p.relative_to(ROOT)} 仍用旧前缀"

# ---- 错误码中文映射门（CHK-ERR）----
def _fixture_app_root(tmp_path, monkeypatch, name):
    """把一个夹具应用连同真实平台码表放进临时仓库根。"""
    import shutil
    monkeypatch.setattr(check, "ROOT", tmp_path)
    shutil.copytree(ROOT / "tests" / "fixtures" / "bad-app" / "apps" / name, tmp_path / "apps" / name)
    errors_js = tmp_path / "core" / "sdk" / "js" / "preview" / "errors.js"
    errors_js.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "core" / "sdk" / "js" / "preview" / "errors.js", errors_js)


def test_err_web_blocks_code_in_text_and_raw_message(fixture_root):
    report = run("errors", "bad-err-web")
    assert codes(report) == {"CHK-ERR-01", "CHK-ERR-02"}
    lines = {int(re.search(r"index\.js:(\d+)", e).group(1)) for e in report.errors if "CHK-ERR-01" in e}
    assert lines == {8, 9, 11}, "模板拼接、字符串相加、ErrorState 传 code 三类都要拦，注释里的示例不算"
    assert sum("CHK-ERR-02" in e for e in report.errors) == 2


def test_err_unregistered_backend_code_fails_with_fix(tmp_path, monkeypatch):
    _fixture_app_root(tmp_path, monkeypatch, "bad-err-code")
    report = run("errors", "bad-err-code")
    assert codes(report) == {"CHK-ERR-03"}
    assert any("XXX_FAILED" in e and "errors.json" in e for e in report.errors)
    assert any("typo_failed" in e for e in report.errors)
    assert not any("not_found" in e for e in report.errors), "平台码无需登记"
    assert "apps/<id>/web/errors.json" in message(report, "CHK-ERR-03")


def test_err_registry_values_must_be_chinese_and_not_override_platform(tmp_path, monkeypatch):
    _fixture_app_root(tmp_path, monkeypatch, "bad-err-registry")
    report = run("errors", "bad-err-registry")
    text = "\n".join(report.errors)
    assert codes(report) == {"CHK-ERR-03"}
    assert "Bad-Key" in text and "english_only" in text and "forbidden 是平台码" in text


def test_err_registered_code_passes(tmp_path, monkeypatch):
    _fixture_app_root(tmp_path, monkeypatch, "bad-err-registry")
    app = tmp_path / "apps" / "good-err"
    (app / "api").mkdir(parents=True)
    (app / "web").mkdir()
    (app / "api" / "router.py").write_text('from haiknow_sdk import DataError\nraise DataError("XXX_FAILED", "导出失败")\n', encoding="utf-8")
    (app / "web" / "errors.json").write_text('{"XXX_FAILED": "导出失败，请稍后重试"}\n', encoding="utf-8")
    (app / "web" / "index.js").write_text("export async function mount(el, ctx) { try {} catch (e) { if (e.code === 'XXX_FAILED') ctx.toast(ctx.preview.errors.message(e), 'error'); } }\n", encoding="utf-8")
    assert run("errors", "good-err").errors == []


def test_health_error_literal_must_be_uppercase(tmp_path, monkeypatch):
    _fixture_app_root(tmp_path, monkeypatch, "bad-err-code")
    router = tmp_path / "apps/bad-err-code/api/router.py"
    for code, rejected in [("FORBIDDEN", False), ("forbidden", True)]:
        router.write_text(f'body = {{"error": {{"code": "{code}"}}}}', encoding="utf-8")
        errors = run("errors", "bad-err-code").errors
        assert any("api/router.py" in error for error in errors) == rejected


def _platform_root(tmp_path, monkeypatch, table: str, doc_codes=(), server_src: str = ""):
    monkeypatch.setattr(check, "ROOT", tmp_path)
    js = tmp_path / "core" / "sdk" / "js" / "preview" / "errors.js"
    js.parent.mkdir(parents=True)
    js.write_text(
        f"export const PLATFORM_ERROR_MESSAGES = {{\n{table}\n}};\n"
        "export const ISSUE_MESSAGES = {\n  required: '必填项缺失',\n};\n",
        encoding="utf-8",
    )
    doc = tmp_path / check.PLATFORM_API_DOC
    doc.parent.mkdir(parents=True)
    doc.write_text("| HTTP | code | 含义 |\n|---|---|---|\n" + "".join(f"`{c.upper()} 403`\n" for c in doc_codes), encoding="utf-8")
    srv = tmp_path / "core" / "server" / "haiknow_core" / "x.py"
    srv.parent.mkdir(parents=True)
    srv.write_text(server_src, encoding="utf-8")


def test_platform_table_must_cover_documented_and_server_codes(tmp_path, monkeypatch):
    _platform_root(tmp_path, monkeypatch, "  forbidden: '没有权限',", doc_codes=["forbidden", "self_review"],
                   server_src="raise DataError('brand_new', '新错误')\nraise IdentityError(409, 'dup_user', '重复')\n")
    report = run("errors")
    text = "\n".join(report.errors)
    assert codes(report) == {"CHK-ERR-04"}
    assert "self_review" in text and "接口规范.md" in text
    assert "brand_new" in text and "dup_user" in text
    assert len(report.errors) == 3


def test_platform_table_values_must_be_chinese_without_code(tmp_path, monkeypatch):
    _platform_root(tmp_path, monkeypatch, "  forbidden: 'forbidden',\n  not_found: 'missing',")
    report = run("errors")
    text = "\n".join(report.errors)
    assert codes(report) == {"CHK-ERR-04"}
    assert "forbidden 的提示" in text and "not_found 的提示" in text


def test_real_repo_error_gate_is_green():
    report = check.Report()
    check.CHECKS["errors"](report, None)
    assert report.errors == []

def _sdk_component_root(tmp_path, monkeypatch):
    """把违例组件夹具和真实平台码表放进临时仓库根。"""
    import shutil
    monkeypatch.setattr(check, "ROOT", tmp_path)
    shutil.copytree(ROOT / "tests" / "fixtures" / "bad-components" / "core", tmp_path / "core")
    shutil.copy(
        ROOT / "core" / "sdk" / "js" / "preview" / "errors.js",
        tmp_path / "core" / "sdk" / "js" / "preview" / "errors.js",
    )


def test_component_badge_with_issue_code_is_blocked(tmp_path, monkeypatch):
    _sdk_component_root(tmp_path, monkeypatch)
    report = run("errors")
    assert codes(report) == {"CHK-ERR-01"}
    assert "components/c99.js:5" in message(report, "CHK-ERR-01")


def test_component_badge_with_chinese_category_passes(tmp_path, monkeypatch):
    _sdk_component_root(tmp_path, monkeypatch)
    (tmp_path / "core" / "sdk" / "js" / "preview" / "components" / "c99.js").write_text(
        "import { badge } from '/sdk/haiknow.js';\n"
        "import { issueMessage } from '/sdk/preview/errors.js';\n\n"
        "export function issueList(issues) {\n"
        "  return issues.map((issue) => badge(issueMessage(issue.code), 'bad'));\n"
        "}\n",
        encoding="utf-8",
    )
    assert run("errors").errors == []


def test_component_issue_code_must_be_registered(tmp_path, monkeypatch):
    _sdk_component_root(tmp_path, monkeypatch)
    (tmp_path / "core" / "sdk" / "js" / "preview" / "components" / "c99.js").write_text(
        "export const ok = true;\n", encoding="utf-8"
    )
    backend = tmp_path / "core" / "sdk" / "haiknow_sdk" / "preview" / "components"
    backend.mkdir(parents=True)
    (backend / "c09.py").write_text('Issue("brand_new", "新问题")\n', encoding="utf-8")
    report = run("errors")
    assert codes(report) == {"CHK-ERR-04"}
    assert "brand_new" in message(report, "CHK-ERR-04")
