"""平台回归的默认隔离与测试进程设置。"""

import gc

import pytest


@pytest.fixture(autouse=True)
def isolate_core_test(isolated_platform, reuse_loaded_routers, cheap_password_hash):
    """让直接调用 create_app 的用例也使用独立数据和配置。"""


def pytest_collection_finish(session):
    # create_app 重复构建 FastAPI 对象。放宽新生代阈值，保持老年代及时回收。
    gc.collect()
    gc.freeze()
    gc.set_threshold(20000, 20, 10)
