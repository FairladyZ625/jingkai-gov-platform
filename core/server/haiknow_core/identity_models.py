"""管理接口输入模型；关联存在性由写入事务检查。"""
from typing import Literal

from pydantic import Field

from .identity_http import Body, Identifier, Name, Password


class UserCreate(Body):
    username: Identifier
    name: Name
    password: Password
    departments: list[Identifier] = Field(default_factory=list, max_length=200)
    positions: list[Identifier] = Field(default_factory=list, max_length=200)
    roles: list[Identifier] = Field(default_factory=list, max_length=200)


class UserPatch(Body):
    name: Name = None
    status: Literal['active', 'disabled'] = None
    departments: list[Identifier] = Field(default=None, max_length=200)
    positions: list[Identifier] = Field(default=None, max_length=200)
    roles: list[Identifier] = Field(default=None, max_length=200)


class ResetPassword(Body):
    password: Password


class DepartmentCreate(Body):
    id: Identifier | None = None
    name: Name
    parentId: Identifier | None = None


class DepartmentPatch(Body):
    name: Name = None
    parentId: Identifier | None = None


class PositionCreate(Body):
    id: Identifier | None = None
    name: Name
    departmentId: Identifier | None = None


class PositionPatch(Body):
    name: Name = None
    departmentId: Identifier | None = None


class RoleCreate(Body):
    id: Identifier
    name: Name


class RolePatch(Body):
    name: Name


GRANT_ACTIONS = ['view', 'operate', 'approve', 'admin']


class Grants(Body):
    actions: list[Literal['view', 'operate', 'approve', 'admin']] = Field(max_length=4)


class CrossProjectGrant(Body):
    appId: Identifier
    subjectField: Identifier
    subjectValue: str | None = Field(default=None, max_length=200)
    principalType: Literal['user', 'role']
    principalId: Identifier


class Product(Body):
    id: Identifier
    name: Name


class ProjectCreate(Body):
    id: Identifier | None = None
    name: Name
    companyId: Identifier | None = None
    members: list[Identifier] = Field(default_factory=list, max_length=10000)
    products: list[Product] = Field(default_factory=list, max_length=1000)


class Members(Body):
    members: list[Identifier] = Field(max_length=10000)


class Settings(Body):
    platformName: Name = None
    defaultHome: str = Field(default=None, max_length=100, pattern=r'^#/[a-z][a-z0-9/-]*$')
    sessionMinutes: int = Field(default=None, ge=1, le=43200)
