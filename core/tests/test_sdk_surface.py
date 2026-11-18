"""冻结 SDK 1.0 自有公共名字、签名与 v1 契约；更新必须评审 ADR 与版本。"""
import ast
import json
import inspect
import runpy

import pytest

from conftest import ROOT

SNAPSHOT = ROOT / 'tests/compat/sdk1-surface.json'


def python_surface():
    def definitions(nodes):
        result = {}
        for node in nodes:
            name = getattr(node, 'name', '')
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (not name.startswith('_') or name == '__init__'):
                result[name] = dict(async_=isinstance(node, ast.AsyncFunctionDef), args=ast.unparse(node.args), returns=ast.unparse(node.returns) if node.returns else None,
                                    decorators=[ast.unparse(d) for d in node.decorator_list])
            elif isinstance(node, ast.ClassDef) and not name.startswith('_'):
                result[name] = dict(bases=[ast.unparse(b) for b in node.bases], members=definitions(node.body),
                                    decorators=[ast.unparse(d) for d in node.decorator_list])
                # 异常等对象公开的实例属性也属于契约。
                result[name]['attributes'] = sorted({n.targets[0].attr for n in ast.walk(node)
                    if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Attribute)
                    and isinstance(n.targets[0].value, ast.Name) and n.targets[0].value.id == 'self'
                    and not n.targets[0].attr.startswith('_')})
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and not node.target.id.startswith('_'):
                result[node.target.id] = ast.unparse(node)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and (not target.id.startswith('_') or target.id == '__all__'):
                        result[target.id] = ast.unparse(node.value)
            elif isinstance(node, ast.ImportFrom) and node.level:
                for alias in node.names:
                    result[alias.asname or alias.name] = f'from {"." * node.level}{node.module or ""} import {alias.name}'
        return result
    import haiknow_sdk
    result = {str(p.relative_to(ROOT / 'core/sdk')): definitions(ast.parse(p.read_text()).body)
              for p in sorted((ROOT / 'core/sdk/haiknow_sdk').rglob('*.py')) if 'preview' not in p.parts}
    # CEO 对 #14 的 preview 入口裁决：实验句柄不纳入 SDK 1.x 冻结面。
    result['haiknow_sdk/__init__.py']['AppContext']['members'].pop('preview', None)
    result['dataclass_constructors'] = {name: str(inspect.signature(getattr(haiknow_sdk, name)))
                                       for name in ['User', 'AppContext']}
    return result


def sdk_surface():
    extract = runpy.run_path(str(ROOT / 'tests/compat/js_surface.py'))['surface']
    return dict(python=python_surface(), javascript=extract((ROOT / 'core/sdk/js/haiknow.js').read_text()),
                javascript_ui=extract((ROOT / 'core/sdk/js/ui/index.js').read_text(), require_context=False),
                contracts={str(p.relative_to(ROOT)): p.read_text() for p in sorted((ROOT / 'tests/fixtures/v1').rglob('*')) if p.is_file()})


def test_sdk1_public_surface():
    assert sdk_surface() == json.loads(SNAPSHOT.read_text()), '公共面变化：先修改 ADR、升版本并请 CODEOWNERS 评审，禁止直接刷新快照消红'


def test_js_signature_extraction_ignores_implementation_and_finds_nested_api():
    extract = runpy.run_path(str(ROOT / 'tests/compat/js_surface.py'))['surface']
    source = '''
// export function fake(a) {}
export async function request(path, options = { message: '){}' }) { return 'export function fake() {}'; }
export function createContext(app) {
  const ignored = `body ${app.id ? `${app.id}` : '}'}`;
  return { app, nested: { get: (id, version = null) => request(`${id}/${version}`) } };
}
'''
    parsed = extract(source)
    assert set(parsed['exports']) == {'request', 'createContext'}
    assert parsed['exports']['request'] == {'signature': "(path, options = { message: '){}' })", 'async': True}
    assert parsed['context'] == {'app': 'reference:app', 'nested': {'get': '(id, version = null)'}}
    assert extract(source.replace("return 'export function fake() {}'", "throw new Error('改实现')")) == parsed
    assert extract(source.replace('(id, version = null)', '(id, revision = null)')) != parsed
    assert extract(source.replace('nested: { get:', 'nested: { read:')) != parsed


def test_js_unknown_export_fails_instead_of_omitting_public_api():
    extract = runpy.run_path(str(ROOT / 'tests/compat/js_surface.py'))['surface']
    with pytest.raises(AssertionError, match='新增导出写法'):
        extract('export class AddedApi {}')
    with pytest.raises(AssertionError, match='新增导出写法'):
        extract('export class AddedApi {}', require_context=False)


def test_js_modules_without_create_context_need_explicit_opt_out():
    extract = runpy.run_path(str(ROOT / 'tests/compat/js_surface.py'))['surface']
    source = 'export const SIZE = 3;\nexport function Button(label) { return label; }'
    with pytest.raises(AssertionError):
        extract(source)
    parsed = extract(source, require_context=False)
    assert parsed['context'] is None
    assert parsed['exports'] == {'SIZE': 3, 'Button': {'signature': '(label)', 'async': False}}
    with pytest.raises(AssertionError, match='createContext'):
        extract('export function createContext(app) { return app; }', require_context=False)
    assert extract('export function createContext(app) { return { app }; }', require_context=False)['context'] == {'app': 'reference:app'}


def test_ui_component_surface_is_frozen():
    """组件库改签名或删导出必须红；改函数体、未知导出写法照旧处理。"""
    extract = runpy.run_path(str(ROOT / 'tests/compat/js_surface.py'))['surface']
    source = (ROOT / 'core/sdk/js/ui/index.js').read_text()
    frozen = json.loads(SNAPSHOT.read_text())['javascript_ui']
    assert extract(source, require_context=False) == frozen
    assert len(frozen['exports']) == 36

    body = source.replace('export function getTheme() {', 'export function getTheme() {\n  const ignored = 1;')
    assert extract(body, require_context=False) == frozen, '改函数体不应让快照变红'

    signature = source.replace('export function Button(labelOrProps, onClickOrOpts, maybeOpts = {})',
                               'export function Button(labelOrProps, onClickOrOpts = {}, maybeOpts = {})')
    assert extract(signature, require_context=False) != frozen, '改签名必须让快照变红'

    removed = source.replace('export function Toast(', 'function Toast(')
    assert extract(removed, require_context=False) != frozen, '删除导出必须让快照变红'

    status = source.replace("label: '草稿'", "label: '草稿（改）'")
    assert extract(status, require_context=False) != frozen, '公共状态词变了必须让快照变红'
