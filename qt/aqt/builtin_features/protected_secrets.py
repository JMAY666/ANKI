# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Windows user-bound encryption with read compatibility for existing local keys."""

from __future__ import annotations

import base64
import ctypes
import json
import os
from ctypes import wintypes
from pathlib import Path

from .storage import read_object, write_object


class _Blob(ctypes.Structure):
    _fields_ = [("length", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_byte))]


def _crypt(data: bytes, decrypt: bool) -> bytes:
    if os.name != "nt":
        raise OSError("此版本的加密凭据存储需要 Windows；不会回退到明文保存")
    buffer = ctypes.create_string_buffer(data)
    source = _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    target = _Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [
        ctypes.POINTER(_Blob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_Blob),
    ]
    function.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not function(
        ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)
    ):
        raise OSError("无法访问本 Windows 用户的加密凭据，请重新输入 Key")
    try:
        return ctypes.string_at(target.data, target.length)
    finally:
        kernel.LocalFree(target.data)


def read_secrets(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    value = read_object(path)
    if value.get("format") == "dpapi-v1":
        value = json.loads(
            _crypt(base64.b64decode(value["payload"], validate=True), True)
        )
    if not isinstance(value, dict) or any(
        not isinstance(key, str) or not isinstance(item, str)
        for key, item in value.items()
    ):
        raise ValueError("凭据文件格式无效")
    return value


def write_secrets(path: Path, value: dict[str, str]) -> None:
    protected = _crypt(json.dumps(value, ensure_ascii=False).encode(), False)
    write_object(
        path, {"format": "dpapi-v1", "payload": base64.b64encode(protected).decode()}
    )
