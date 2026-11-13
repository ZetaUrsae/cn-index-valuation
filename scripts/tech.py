# -*- coding: utf-8 -*-
import json
import _bootstrap  # noqa: F401  （把项目根加入 sys.path）
from ivdata.paths import BASE  # noqa: E402
raw = json.load(open(BASE + "data/raw.json", encoding="utf-8"))
order = ["000300.SH","000016.SH","000905.SH","399006.SZ","000688.SH"]

def ma(v,n): return sum(v[-n:])/n if len(v)>=n else None
def fmt(x,n=2): return None if x is None else round(x,n)

out={}
for c in order:
    d = sorted(raw[c]["daily"], key=lambda r:r["trade_date"])
    close = [r["close"] for r in d]
    vol = [r.get("vol") or 0 for r in d]
    last=d[-1]
    o,h,l,cl = last["open"],last["high"],last["low"],last["close"]
    pc = d[-2]["close"]
    body = abs(cl - o)
    rng = max(h - l, 1e-9)
    upsh = (h - max(o, cl)) / rng * 100
    dnsh = (min(o, cl) - l) / rng * 100
    ma20, ma60, ma250, ma120, ma5 = ma(close,20), ma(close,60), ma(close,250), ma(close,120), ma(close,5)
    hi250 = max(close[-250:])
    lo250 = min(close[-250:])
    v20 = sum(vol[-20:])/20 if len(vol)>=20 else None
    r = {
      "code":c,"name":raw[c]["name"],"date":last["trade_date"],
      "close":fmt(cl),"pct":fmt(last.get("pct_chg"),2),
      "ma5":fmt(ma5),"ma20":fmt(ma20),"ma60":fmt(ma60),"ma120":fmt(ma120),"ma250":fmt(ma250),
      "above_ma20": fmt((cl/ma20-1)*100,2) if ma20 else None,
      "above_ma60": fmt((cl/ma60-1)*100,2) if ma60 else None,
      "above_ma250": fmt((cl/ma250-1)*100,2) if ma250 else None,
      "dd_from_250high": fmt((cl/hi250-1)*100,2),
      "up_from_250low": fmt((cl/lo250-1)*100,2),
      "ret20": fmt((cl/d[-21]["close"]-1)*100,2) if len(d)>21 else None,
      "ret60": fmt((cl/d[-61]["close"]-1)*100,2) if len(d)>61 else None,
      "vol_ratio20": fmt(vol[-1]/v20,2) if v20 else None,
      "body_pct": fmt(body/rng*100,1), "upsh": fmt(upsh,1), "dnsh": fmt(dnsh,1),
      "bull_align": bool(ma5 and ma20 and ma60 and ma5>ma20>ma60),
      "bear_align": bool(ma5 and ma20 and ma60 and ma5<ma20<ma60),
      "candles": [{"d":x["trade_date"],"o":fmt(x["open"]),"h":fmt(x["high"]),"l":fmt(x["low"]),"c":fmt(x["close"]),
                   "p":fmt(x.get("pct_chg"),2)} for x in d[-5:]],
    }
    out[c]=r
    print(json.dumps({k:v for k,v in r.items() if k!="candles"}, ensure_ascii=False))
json.dump(out, open(BASE + "work/tech.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
print("saved tech.json")
