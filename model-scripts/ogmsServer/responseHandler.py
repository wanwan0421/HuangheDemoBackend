"""
Author: DiChen
Date: 2024-08-13 16:24:22
LastEditors: DiChen
LastEditTime: 2024-08-22 22:04:02
"""

"""
Author: DiChen
Date: 2024-08-13 16:24:22
LastEditors: DiChen
LastEditTime: 2024-08-15 21:42:50
"""

from enum import Enum
from typing import Generic, TypeVar, Optional

T = TypeVar("T")


class ResultEnum(Enum):
    SUCCESS = (1, "Success")
    NO_OBJECT = (-1, "No object")
    ERROR = (-2, "Error")

    def __init__(self, code: int, msg: str):
        self._code = code
        self._msg = msg

    @property
    def code(self) -> int:
        return self._code

    @property
    def msg(self) -> str:
        return self._msg


class ResultUtils(Generic[T]):
    def __init__(
        self,
        code: int = ResultEnum.SUCCESS.code,
        msg: str = ResultEnum.SUCCESS.msg,
        data: Optional[T] = None,
    ):
        self.code = code
        self.msg = msg
        self.data = data

    @classmethod
    def success(cls, data: Optional[T] = None) -> "ResultUtils[T]":
        return cls(ResultEnum.SUCCESS.code, ResultEnum.SUCCESS.msg, data)

    @classmethod
    def error(
        cls,
        code: int = ResultEnum.ERROR.code,
        msg: str = ResultEnum.ERROR.msg,
        data: Optional[T] = None,
    ) -> "ResultUtils[T]":
        return cls(code, msg, data)

    def __repr__(self) -> str:
        return f"ResultUtils(code={self.code}, msg='{self.msg}', data={self.data})"
