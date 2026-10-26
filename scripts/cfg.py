# -*- coding: utf-8 -*-
"""统一配置：自动推导参考交易日 ASOF（今天之前最近的一个开市日）。

可用环境变量 ASOF=YYYYMMDD 强制指定（便于回补/重算）。
"""
import os
import sys
import datetime
import calendar

BASE = "D:/QClaw/Stock/index_valuation/"
DATA = BASE + "data/"        # 持久数据/历史库（增量缓存，勿随手删除）
WORK = BASE + "work/"        # 每次运行生成的中间产物（可清理，会重建）
REPORTS = BASE + "reports/"  # 日报 HTML 产出
for _d in (DATA, WORK, REPORTS, REPORTS + "archive"):
    os.makedirs(_d, exist_ok=True)
SKILL = r"C:/Users/zky12/.workbuddy/skills/tushare-data/scripts"


def _report_tag() -> str:
    """试运行标记：IV_REPORT_TAG=test → 报告名 index_val_report_<ASOF>_test.html。

    定时任务的判重只看**无标记**的正式文件名，所以手工试运行不会再让它误判为
    「今天已经跑过」而跳过（见 run_daily.py --check）。
    """
    raw = (os.environ.get("IV_REPORT_TAG") or "").strip()
    if not raw:
        return ""
    keep = "".join(c if (c.isalnum() or c in "-_") else "-" for c in raw)[:16].strip("-_")
    return ("_" + keep) if keep else ""


REPORT_TAG = _report_tag()


def report_path(asof: str, tag: str = "") -> str:
    """报告文件绝对路径。tag 为空时是定时任务使用的正式文件名。"""
    return REPORTS + "index_val_report_%s%s.html" % (asof, tag)


def pro_api():
    """返回 Tushare pro_api 实例"""
    if SKILL not in sys.path:
        sys.path.insert(0, SKILL)
    from get_token import get_token
    import tushare as ts
    return ts.pro_api(get_token())


def shift(ymd, days=0, months=0, years=0):
    """在 YYYYMMDD 基础上平移天/月/年，返回 YYYYMMDD"""
    y, m, d = int(ymd[:4]), int(ymd[4:6]), int(ymd[6:8])
    y += years
    m += months
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    d = min(d, calendar.monthrange(y, m)[1])
    dt = datetime.date(y, m, d) + datetime.timedelta(days=days)
    return dt.strftime("%Y%m%d")


def fmt(ymd):
    """YYYYMMDD -> YYYY-MM-DD"""
    return f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"


def prev_trading_day():
    """最近一个已开市交易日；ASOF 环境变量优先。

    v2.5.7 起改走上交所日历（与 ivdata 主管线同源），**不再调用 Tushare**——
    旧实现 `pro.trade_cal` 导致每次 import cfg 都发一次 waditu 请求，
    违反"日常零 Tushare"（run_daily 的加工子进程因带了 ASOF 环境变量才一直没暴露）。
    日历不可用时退化为工作日近似并告警，不抛异常。
    """
    env = os.environ.get("ASOF", "").strip()
    if env:
        return env
    today = datetime.date.today()
    end = today.strftime("%Y%m%d")
    start = shift(end, days=-45)
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if root not in sys.path:                 # 独立跑 scripts/*.py 时也能 import ivdata
            sys.path.insert(0, root)
        from ivdata.providers.exchange import SseCalendar
        cal = SseCalendar().fetch_calendar(start, end)
        days = sorted(
            (c["cal_date"] if isinstance(c, dict) else str(c))
            for c in cal
            if (c.get("is_open") in ("1", 1, True) if isinstance(c, dict) else True)
        )
        days = [d for d in days if d < end]
        if days:
            return days[-1]
        print("[cfg] 上交所日历近 45 天无开市日，退化为工作日近似", flush=True)
    except Exception as e:                       # noqa: BLE001
        print("[cfg] 上交所日历不可用（%s），退化为工作日近似" % str(e)[:80], flush=True)
    d = today
    while d.weekday() >= 5:                      # 周六/周日
        d -= datetime.timedelta(days=1)
    return d.strftime("%Y%m%d")


# 参考交易日（全局）
ASOF = prev_trading_day()
ASOF_FMT = fmt(ASOF)


def load_manual():
    """读取补充输入（仅研究文本：外资投行观点 views / 一句话结论 syn）。

    报告内的数值（行情、PE/PB、PCR、份额、10Y）全部由管线自动落库，
    股息率与 bond10y 两个旁路已于 v2.4.x 删除。
    """
    import json
    p = BASE + "data/manual_inputs.json"
    if os.path.exists(p):
        return json.load(open(p, encoding="utf-8"))
    return {}


if __name__ == "__main__":
    print("ASOF =", ASOF, "(", ASOF_FMT, ")")
