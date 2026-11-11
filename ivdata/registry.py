# -*- coding: utf-8 -*-
"""ivdata.registry —— provider 注册表 + 降级链调度。

调用方只需要 ``Registry.get().fetch("valuation", ...)``，
不必关心背后是新浪、中证、东财还是交易所官方接口。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from .config import DOMAINS, DOMAIN_SCHEMA, SETTINGS
from .contracts import Prov, Provider, ProviderError, ProviderUnavailable
from .provenance import Provenance


class Registry:
    _inst: Optional["Registry"] = None

    def __init__(self):
        self.providers: Dict[str, Provider] = {}
        self.prov: Provenance = Provenance()
        self.decisions: Dict[str, str] = {}

    # -------------------------------------------------- 单例
    @classmethod
    def get(cls) -> "Registry":
        if cls._inst is None:
            cls._inst = Registry()
            cls._inst._autoload()
        return cls._inst

    def _autoload(self) -> None:
        from .providers import PROVIDERS
        for klass in PROVIDERS:
            try:
                p = klass()
            except Exception as e:                      # noqa: BLE001
                print(f"  [registry] 跳过 {klass.__name__}: {e}", flush=True)
                continue
            self.providers[p.name] = p

    # -------------------------------------------------- 注册
    def register(self, provider: Provider) -> None:
        self.providers[provider.name] = provider

    def list_domains(self) -> Dict[str, List[str]]:
        return dict(DOMAINS)

    # -------------------------------------------------- 调度
    def fetch(self, domain: str, *args, _skip=(), **kwargs) -> Any:
        """按优先级链取数，返回第一个成功的结果。

        失败时抛 ProviderError（保留每个源的错误信息）。

        ``_skip``：本次跳过的 provider 名。用于「主源给了可疑结果，换下一个
        源重取」的场景（例如深交所快照疑似还没刷新，见 Pipeline.sync_etfs）。
        它只影响调度，不会传给 provider 的 fetch_* 方法。
        """
        chain = [c for c in DOMAINS.get(domain, []) if c not in _skip]
        forced = SETTINGS.forced(domain)
        if forced and forced not in _skip:
            chain = [forced] + [c for c in chain if c != forced]

        schema = DOMAIN_SCHEMA.get(domain, {})
        errors: List[str] = []
        tried: List[str] = []

        for name in chain:
            p = self.providers.get(name)
            if p is None:
                errors.append(f"{name}: 未注册")
                continue
            if domain not in p.domains:
                errors.append(f"{name}: 不支持 {domain}")
                continue
            try:
                if not p.available():
                    errors.append(f"{name}: 依赖不可用")
                    continue
            except Exception as e:                      # noqa: BLE001
                errors.append(f"{name}: available() 异常 {e}")
                continue

            t0 = time.time()
            try:
                data = self._dispatch(p, domain, *args, **kwargs)
                _check(data, schema)
                el = time.time() - t0
                rows = len(data) if hasattr(data, "__len__") else 0
                self.prov.add(Prov(domain=domain, provider=name, ok=True, rows=rows,
                                   elapsed=round(el, 2), fallback_from=tried,
                                   asof=SETTINGS.asof))
                self.decisions[domain] = name
                return data
            except ProviderUnavailable as e:
                # 依赖问题，不算失败，继续下一个
                errors.append(f"{name}: 不可用({str(e)[:60]})")
                continue
            except Exception as e:                      # noqa: BLE001
                el = time.time() - t0
                errors.append(f"{name}: {type(e).__name__} {str(e)[:110]}")
                self.prov.add(Prov(domain=domain, provider=name, ok=False,
                                   elapsed=round(el, 2), error=str(e)[:200],
                                   asof=SETTINGS.asof))
                tried.append(name)
                continue

        raise ProviderError("域 %s 所有数据源均失败:\n  - %s"
                            % (domain, "\n  - ".join(errors)))

    # -------------------------------------------------- 查询
    def fallbacks(self) -> List[str]:
        """返回「降级到备选源」的域列表，便于在日报里一眼看出哪里抖了。"""
        return [r.domain for r in self.prov.records if r.ok and r.fallback_from]

    # -------------------------------------------------- 内部
    @staticmethod
    def _dispatch(p: Provider, domain: str, *args, **kwargs) -> Any:
        fn = getattr(p, "fetch_" + domain, None)
        if fn is None:
            raise ProviderUnavailable(f"{p.name} 无 fetch_{domain}")
        return fn(*args, **kwargs)


def _check(data: Any, schema: Dict) -> None:
    """轻量质量校验：行数下限 + 必需字段。"""
    if data is None:
        raise ProviderError("返回 None")
    if not hasattr(data, "__len__"):
        return
    if len(data) == 0:
        raise ProviderError("返回空集")
    min_rows = schema.get("min_rows", 0)
    if min_rows and len(data) < min_rows:
        raise ProviderError(f"行数 {len(data)} < 下限 {min_rows}")
    fields = schema.get("fields") or []
    if fields:
        first = data[0]
        if isinstance(first, dict):
            missing = [f for f in fields if f not in first]
            if missing:
                raise ProviderError(f"缺字段 {missing}")
