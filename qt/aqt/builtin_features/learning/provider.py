# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Bounded, non-streaming reports, independent of the card chat UI."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from .policy import INPUT_PRICE, MAX_INPUT_BYTES, MAX_OUTPUT_TOKENS, OUTPUT_PRICE

ENDPOINT = "https://api.deepseek.com/chat/completions"
SYSTEM = """你是学习数据分析助手。只使用提供的汇总数据，用中文输出 JSON，不输出 Markdown。
实际记录与推断分开；不能把自评通过率视为考试正确率，也不能保证因果关系。
只可建议 parameter=new_per_day，前值必须等于输入，整数变化不超过 max_change，后值在 0..new_cards_max。
数据不充分、目标未填写或没有充分理由时 decision=keep、changes=[]。不建议为每天运行而改动。
禁止输出 SQL、代码、评分改写或具体卡片排程。其他参数可在推断文字中提醒人工检查。
严格输出以下六个字段：
{"snapshot_id":"原样返回输入值","decision":"keep 或 propose","summary":"摘要",
"observations":["实际数据"],"inferences":["可能原因、不确定性和观察建议"],
"changes":[{"parameter":"new_per_day","before":20,"after":18,"reason":"理由",
"evidence":["backlog","recent_recorded_seconds"]}]}
evidence 只引用输入 evidence 中实际存在的键。
"""


class ProviderError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        configuration_error: bool = False,
    ):
        super().__init__(message)
        self.retryable = retryable
        self.configuration_error = configuration_error


def request_report(
    payload: dict[str, Any], key: str, opener: Any = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not key.strip():
        raise ProviderError("请先配置 DeepSeek API Key")
    if len(key) > 16384 or any(not 33 <= ord(character) <= 126 for character in key):
        raise ProviderError("API Key 格式无效，请重新输入；未发送请求")
    data = json.dumps(
        {
            "model": "deepseek-flash",
            "thinking": {"type": "disabled"},
            "stream": False,
            "temperature": 0.2,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM},
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False, allow_nan=False),
                },
            ],
        },
        ensure_ascii=False,
    ).encode()
    if len(data) > MAX_INPUT_BYTES:
        raise ProviderError("汇总数据超过请求上限，未发送")
    req = urllib.request.Request(
        ENDPOINT,
        data=data,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    try:
        with (opener or urllib.request.urlopen)(req, timeout=60) as response:
            raw = response.read(256001)
        if len(raw) > 256000:
            raise ProviderError("API 响应超过允许长度")
        result = json.loads(raw)
        choice = result["choices"][0]
        if choice.get("finish_reason") != "stop":
            raise ProviderError("模型响应未完整结束，已拒绝报告")
        content = json.loads(
            choice["message"]["content"],
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
        usage = result.get("usage", {})
        for field in ("prompt_tokens", "completion_tokens"):
            if type(usage.get(field)) is not int or usage[field] < 0:
                raise ProviderError("缺少有效用量记录，已拒绝报告")
        return content, {
            "model": result.get("model", "deepseek-flash"),
            "request_id": str(result.get("id", ""))[:200],
            "usage": usage,
            "estimated_cost": (
                usage["prompt_tokens"] * INPUT_PRICE
                + usage["completion_tokens"] * OUTPUT_PRICE
            )
            / 1_000_000,
        }
    except urllib.error.HTTPError as exc:
        messages = {
            401: "API Key 无效",
            402: "DeepSeek 余额不足",
            429: "DeepSeek 请求限流",
            500: "DeepSeek 服务故障",
            503: "DeepSeek 服务繁忙",
        }
        raise ProviderError(
            messages.get(exc.code, f"DeepSeek 请求失败（HTTP {exc.code}）"),
            retryable=exc.code in (429, 500, 503),
            configuration_error=exc.code in (401, 402),
        ) from None
    except (TimeoutError, urllib.error.URLError):
        raise ProviderError(
            "网络失败或超时；设置未改变，用量暂按预留额度记录", retryable=True
        ) from None
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise ProviderError("API 返回的报告结构无效，设置未改变") from exc
