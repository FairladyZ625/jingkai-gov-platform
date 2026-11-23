def install(app, platform, current_user):
    """先安装文档服务，再注册导入、检索、统计和建议接口。"""
    from .docs import install as install_docs
    from .importer import install as install_importer
    from .search import install as install_search

    install_docs(app, platform, current_user)
    install_importer(app, platform, current_user)
    install_search(app, platform, current_user)


__all__ = ["install"]
