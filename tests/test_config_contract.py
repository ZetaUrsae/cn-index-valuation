# -*- coding: utf-8 -*-
"""配置契约：DOMAINS 优先级链里的每个名字，必须真的注册过且声明支持该域。

这类测试防的是「改名/加源时漏改另一处」——它不会因为数据变化而误报，
却能抓住重构中最常见的一类静默失效。
"""
from ivdata import config
from ivdata.providers import PROVIDERS

BY_NAME = {p.name: p for p in PROVIDERS}


def test_provider_names_unique():
    names = [p.name for p in PROVIDERS]
    assert len(names) == len(set(names)), "provider 名字重复：%s" % names


def test_domains_reference_registered_providers():
    for domain, chain in config.DOMAINS.items():
        assert chain, "%s 的优先级链为空" % domain
        for name in chain:
            assert name in BY_NAME, "%s 引用了未注册的 provider：%s" % (domain, name)


def test_chained_provider_declares_domain():
    for domain, chain in config.DOMAINS.items():
        for name in chain:
            assert domain in BY_NAME[name].domains, (
                "%s 声明支持 %s，但被放进了 %s 的链" % (name, BY_NAME[name].domains, domain))


def test_schema_covers_all_domains():
    assert set(config.DOMAINS) == set(config.DOMAIN_SCHEMA)


def test_index_table_consistent():
    """报告主表五只指数：序号连续、代码唯一、派生映射与表一致。"""
    assert len(config.INDEXES) == 5
    orders = [x[0] for x in config.INDEXES]
    codes = [x[1] for x in config.INDEXES]
    assert orders == [1, 2, 3, 4, 5]
    assert len(codes) == len(set(codes))
    assert config.INDEX_CODES == codes
    assert config.CODE2NAME[codes[0]] == "沪深300"
    assert set(config.ETF_ALL).issuperset(config.ETF_LIST)
