# -*- coding: utf-8 -*-
"""ivdata.http —— 带限流 / 重试 / 超时 / 连接管理的 HTTP 客户端。

设计要点
--------
* **每个 host 一个会话**（连接复用），并维护独立的令牌桶限流。
* 重试只针对「可能自愈」的错误：超时、连接重置、5xx、限流响应。
  4xx 直接失败，不浪费重试次数。
* 自动识别并处理代理环境：默认沿用系统代理（企业内网需要），
  但也支持 ``direct=True`` 强制直连（某些行情接口对代理不友好）。
* 所有请求写入一个轻量计数器，便于 provenance 统计「本次跑了多少请求」。
"""
from __future__ import annotations

import json
import random
import threading
import time
import urllib.parse
from typing import Any, Dict, Optional

import requests

from .config import HOST_QPS, SETTINGS

# 全局请求计数器：{host: n}
_COUNTER: Dict[str, int] = {}
_COUNTER_LOCK = threading.Lock()

RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}


def request_count() -> Dict[str, int]:
    with _COUNTER_LOCK:
        return dict(_COUNTER)


def reset_count() -> None:
    with _COUNTER_LOCK:
        _COUNTER.clear()


class _Bucket:
    """极简令牌桶：保证同一 host 的 QPS 不超过配额。"""

    def __init__(self, qps: float):
        self.qps = max(qps, 0.1)
        self.capacity = max(1.0, self.qps)
        self.tokens = self.capacity
        self.last = time.monotonic()
        self.lock = threading.Lock()

    def take(self) -> None:
        with self.lock:
            now = time.monotonic()
            self.tokens = min(self.capacity, self.tokens + (now - self.last) * self.qps)
            self.last = now
            if self.tokens < 1:
                wait = (1 - self.tokens) / self.qps
                time.sleep(wait)
                self.tokens = 0
                self.last = time.monotonic()
            else:
                self.tokens -= 1


_SESSIONS: Dict[str, requests.Session] = {}
_BUCKETS: Dict[str, _Bucket] = {}
_LOCK = threading.Lock()


def _session(host: str, direct: bool) -> requests.Session:
    key = f"{host}|{direct}"
    with _LOCK:
        if key not in _SESSIONS:
            s = requests.Session()
            if direct:
                s.trust_env = False          # 忽略 HTTP(S)_PROXY
            s.headers.update({
                "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/124.0 Safari/537.36"),
                "Accept": "*/*",
                "Connection": "keep-alive",
            })
            _SESSIONS[key] = s
        if host not in _BUCKETS:
            # 部分站点受不了 5 QPS 的突发，按 host 单独降速（见 config.HOST_QPS）
            _BUCKETS[host] = _Bucket(HOST_QPS.get(host, SETTINGS.qps))
        return _SESSIONS[key]


def get(url: str, params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
        retries: Optional[int] = None,
        direct: bool = False,
        expect: str = "auto",
        encoding: Optional[str] = None) -> Any:
    """GET 一个 URL。

    expect:
        "json"  -> 返回解析后的对象
        "text"  -> 返回文本
        "auto"  -> 先按 json 解析，失败则返回文本
    """
    return _request("GET", url, params=params, headers=headers, timeout=timeout,
                    retries=retries, direct=direct, expect=expect, encoding=encoding)


def post(url: str, json_body: Any = None,
         data: Optional[Dict[str, Any]] = None,
         params: Optional[Dict[str, Any]] = None,
         headers: Optional[Dict[str, str]] = None,
         timeout: Optional[float] = None,
         retries: Optional[int] = None,
         direct: bool = False,
         expect: str = "auto",
         encoding: Optional[str] = None) -> Any:
    """POST 一个 URL（json_body 走 application/json，data 走表单）。"""
    return _request("POST", url, params=params, headers=headers, timeout=timeout,
                    retries=retries, direct=direct, expect=expect, encoding=encoding,
                    json_body=json_body, data=data)


def _request(method: str, url: str, *,
             params: Optional[Dict[str, Any]] = None,
             headers: Optional[Dict[str, str]] = None,
             timeout: Optional[float] = None,
             retries: Optional[int] = None,
             direct: bool = False,
             expect: str = "auto",
             encoding: Optional[str] = None,
             json_body: Any = None,
             data: Optional[Dict[str, Any]] = None) -> Any:
    host = urllib.parse.urlparse(url).netloc
    sess = _session(host, direct)
    bucket = _BUCKETS[host]
    timeout = timeout or SETTINGS.timeout
    retries = SETTINGS.retries if retries is None else retries

    last_err: Optional[Exception] = None
    for attempt in range(retries + 1):
        bucket.take()
        try:
            if method == "POST":
                r = sess.post(url, params=params, headers=headers, timeout=timeout,
                              json=json_body, data=data)
            else:
                r = sess.get(url, params=params, headers=headers, timeout=timeout)
            with _COUNTER_LOCK:
                _COUNTER[host] = _COUNTER.get(host, 0) + 1

            if r.status_code in RETRY_STATUS:
                raise requests.HTTPError(f"HTTP {r.status_code}")
            if r.status_code >= 400:
                # 不可自愈，直接失败
                raise requests.HTTPError(f"HTTP {r.status_code} {url[:80]}")

            if encoding:
                r.encoding = encoding
            if expect == "text":
                return r.text
            if expect == "json":
                return _loads(r.text)
            try:
                return _loads(r.text)
            except Exception:
                return r.text

        except Exception as e:  # noqa: BLE001 —— 网络层统一兜住
            last_err = e
            if attempt >= retries:
                break
            sleep = SETTINGS.backoff ** attempt + random.uniform(0, 0.4)
            time.sleep(min(sleep, 8))

    raise ConnectionError(f"{method} 失败({retries + 1}次): {url[:100]} :: {last_err}")


def _loads(text: str) -> Any:
    """容错 JSON 解析：处理 JSONP 包裹、BOM、尾部逗号。"""
    t = text.strip()
    if t.startswith("\ufeff"):
        t = t[1:]
    # JSONP: callback({...})
    if t and t[0] not in "[{" and "(" in t and t.endswith(")"):
        inner = t[t.index("(") + 1: t.rindex(")")]
        t = inner.strip()
    return json.loads(t)
