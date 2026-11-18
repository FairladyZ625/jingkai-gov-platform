"""经开区知识库导入。"""


def install(app, platform, current_user, *, reader=None, title_threshold=0.62):
    """在知识库文档服务安装后登记导入接口。"""
    from ..spaces import visible_spaces
    from .mineru import parser_for
    from .repository import DocumentsImportRepository
    from .routes import build_router
    from .service import ImportService, SpaceAccess

    def spaces_for(user):
        actions = platform.rbac.actions(user, "kb")
        visible = frozenset(visible_spaces(user))
        return SpaceAccess(
            visible if "view" in actions else frozenset(),
            visible if "operate" in actions else frozenset(),
        )

    service = ImportService(
        DocumentsImportRepository(platform.kb), spaces_for, reader=reader,
        parser_for=lambda user, space, classification: parser_for(platform, user, space, classification),
        title_threshold=title_threshold,
    )
    app.include_router(build_router(service, current_user))
