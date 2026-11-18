"""反例：应用通过静态属性和 getattr 读取 SDK 内部服务。"""


def bad(ctx):
    service = ctx.records._s
    return getattr(ctx.records, "_s").projects, service
