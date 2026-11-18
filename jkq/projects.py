"""校验实例项目种子并补齐旧版留下的空项目目录。"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from haiknow_core.store import Store


# core identity 在缺少项目配置时写入的占位组织。
CORE_PLACEHOLDER = ("company", "演示公司")


@dataclass(frozen=True)
class ProjectSeed:
    company_id: str
    company_name: str
    project_name: str
    products_json: str


def load_project_seed(config_dir: Path) -> ProjectSeed:
    path = config_dir / "projects.yaml"
    source = f"HAIKNOW_CONFIG_DIR 项目配置 {path}"
    try:
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        raise RuntimeError(f"{source} 无法读取或不是有效的 YAML") from None

    match config:
        case {"companies": [{
            "id": str(company_id), "name": str(company_name),
            "projects": [{"id": "jkq", "name": str(project_name)} as project],
        }]} if all(value.strip() for value in (company_id, company_name, project_name)):
            products = project.get("products", [])
        case _:
            raise RuntimeError(f"{source} 必须定义一个组织及其唯一项目 jkq，并填写组织标识和名称、项目名称")

    if not isinstance(products, list) or any(
        not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"].strip()
        for item in products
    ):
        raise RuntimeError(f"{source} 中 jkq 的 products 必须是带有效 id 的对象列表")
    try:
        products_json = json.dumps(products)
    except (TypeError, ValueError):
        raise RuntimeError(f"{source} 中 jkq 的 products 必须可转换为 JSON") from None
    return ProjectSeed(company_id, company_name, project_name, products_json)


def restore_empty_projects(store: "Store", seed: ProjectSeed) -> None:
    with store._lock, store._db as db:
        store.begin_write()
        if db.execute("select 1 from projects limit 1").fetchone() is not None:
            return

        # 旧库已标记为初始化，core 不会重读种子。只补缺失行，保留真实组织和其他数据。
        # 无项目时 core 自动生成的占位组织没有任何引用，就地改成配置组织，
        # 保留其 rowid，使配置组织成为默认组织。
        placeholder = db.execute(
            "select 1 from companies where id=? and name=?", CORE_PLACEHOLDER).fetchone()
        configured = db.execute(
            "select 1 from companies where id=?", (seed.company_id,)).fetchone()
        if placeholder and not configured:
            db.execute("update companies set id=?, name=? where id=?",
                       (seed.company_id, seed.company_name, CORE_PLACEHOLDER[0]))
        else:
            db.execute("insert into companies (id, name) values (?, ?) on conflict(id) do nothing",
                       (seed.company_id, seed.company_name))
            if placeholder and seed.company_id != CORE_PLACEHOLDER[0]:
                db.execute("delete from companies where id=? and name=?", CORE_PLACEHOLDER)
        db.execute("insert into projects (id, name, company_id, products) values (?, ?, ?, ?)",
                   ("jkq", seed.project_name, seed.company_id, seed.products_json))
