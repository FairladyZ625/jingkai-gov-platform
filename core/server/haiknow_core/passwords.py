"""标准库 scrypt 口令散列；盐逐人生成，明文不持久化。"""
import hashlib
import hmac
import secrets

# 生产成本参数。模块级变量只为让测试夹具降低成本（见仓库根 conftest.py）；
# 运行时代码不得改它，tests/test_identity_auth.py 在干净子进程里断言这三个值。
SCRYPT_N, SCRYPT_R, SCRYPT_P = 16384, 8, 1


def _scrypt(password: str, salt: str) -> str:
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P).hex()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    return f'scrypt${salt}${_scrypt(password, salt)}'


def verify_password(password: str, stored: str) -> bool:
    _, salt, expected = stored.split('$')
    return hmac.compare_digest(_scrypt(password, salt), expected)
