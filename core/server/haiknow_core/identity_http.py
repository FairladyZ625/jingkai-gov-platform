"""身份管理的请求边界与错误信封，不改变既有 v1/SDK 错误契约。"""
from typing import Annotated

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field
from haiknow_sdk import DataError

Identifier = Annotated[str, Field(min_length=1, max_length=64, pattern=r'^[a-zA-Z0-9][a-zA-Z0-9_.@-]*$')]
Name = Annotated[str, Field(min_length=1, max_length=100, pattern=r'\S')]
Password = Annotated[str, Field(min_length=8, max_length=1024)]


class Body(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class IdentityError(Exception):
    def __init__(self, status, code, message):
        self.status = status
        self.error = {'code': code, 'message': message}


class IdentityRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def handle(request):
            try:
                return await handler(request)
            except RequestValidationError:
                return JSONResponse({'error': {'code': 'invalid_request', 'message': '请求字段缺失或类型不正确'}}, status_code=400)
            except DataError as error:
                return JSONResponse({'error': error.error}, status_code=error.status)
            except HTTPException as error:
                code = {401: 'unauthenticated', 403: 'forbidden', 404: 'not_found'}.get(error.status_code, 'invalid_request')
                return JSONResponse({'error': {'code': code, 'message': str(error.detail)}}, status_code=error.status_code)
        return handle
