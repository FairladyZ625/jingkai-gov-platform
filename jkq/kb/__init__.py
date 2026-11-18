from .docs import install as install_docs


def install(app, platform, current_user):
    """先装 #24 文档服务（提供 platform.kb 与错误处理），再装 #26 检索/统计/建议。"""
    from .search import install as install_search

    install_docs(app, platform, current_user)
    install_search(app, platform, current_user)


__all__ = ["install"]
