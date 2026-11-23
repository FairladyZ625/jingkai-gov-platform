"""只通过测试页面密码框输入夹具假口令，不注入静态配置或存储。"""
import time


def login(page, username, password):
    page.locator('[data-op="login.user"]').fill(username)
    page.locator('[data-op="login.pass"]').fill(password)
    page.locator('[data-op="login.go"]').click()
    page.locator('#btn-demo').wait_for()


def answer_switch(page, password):
    field = page.locator('[data-op="switch.password"]')
    if field.is_visible():
        field.fill(password)
        page.locator('[role="dialog"] [data-ok]').click()


def wait_segment(page, index, password, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        answer_switch(page, password)
        if page.evaluate("i => !JKDemo.state.on || JKDemo.state.i > i", index):
            return
        page.wait_for_timeout(100)
    raise AssertionError(f'段落 {index} 未完成')
