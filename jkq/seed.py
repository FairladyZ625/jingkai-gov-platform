"""通过同一实例工厂初始化 SQLite 项目目录。"""

from .app import create_app


def main() -> None:
    platform = create_app().state.platform
    projects = "、".join(sorted(platform.directory.projects()))
    print(f"实例项目已初始化：{projects}")


if __name__ == "__main__":
    main()
