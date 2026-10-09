"""分析師共識預估(Yahoo Finance 匯總):今年 / 明年 EPS 預估、目標價。

輸出 data/estimates/latest.json,並每天存一份 data/estimates/YYYY-MM-DD.json 快照
(免費來源沒有歷史共識,只能從現在開始累積,之後才能回測)。
  {代號: {"eps0": 今年 EPS 預估, "eps1": 明年, "n0", "n1": 分析師數, "tgt": 平均目標價, "tgt_lo", "tgt_hi", "n_tgt", "sym"}}
只抓起漲雷達名單、觀察名單與板塊成分股(全市場一檔一檔抓太久)。

用法:python scripts/estimates.py
"""
import json
import logging
import os
import sys
import time
import warnings
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "estimates")
TZ = timezone(timedelta(hours=8))


def num(v):
    try:
        v = float(v)
        return None if v != v else round(v, 2)
    except (TypeError, ValueError):
        return None


def universe():
    codes = set()
    for p, key in (("data/radar/latest.json", ("rank", "rev", "breakout")), ("data/watch/latest.json", ("picks",))):
        try:
            d = json.load(open(os.path.join(ROOT, p), encoding="utf-8"))
        except FileNotFoundError:
            continue
        for k in key:
            codes |= {x["code"] for x in d.get(k, [])}
    try:
        for t in json.load(open(os.path.join(ROOT, "data/sectors/themes.json"), encoding="utf-8")):
            codes |= set(t["codes"])
    except FileNotFoundError:
        pass
    return sorted(codes)


def fetch(code, known_sym=None):
    import yfinance as yf
    for sym in ([known_sym] if known_sym else []) + [code + ".TW", code + ".TWO"]:
        try:
            t = yf.Ticker(sym)
            ee = t.earnings_estimate
            pt = t.analyst_price_targets or {}
        except Exception:  # noqa: BLE001  查無此代號、限流等,換下一個後綴
            continue
        rec = {"sym": sym}
        if ee is not None and len(ee) and "avg" in ee.columns:
            def g(row, col):
                return num(ee.loc[row, col]) if row in ee.index and col in ee.columns else None
            rec.update(eps0=g("0y", "avg"), eps1=g("+1y", "avg"), n0=g("0y", "numberOfAnalysts"), n1=g("+1y", "numberOfAnalysts"))
            # Yahoo 有些台股(例:富世達)的 EPS 預估是美元,股價與目標價卻是台幣。用同一來源的台幣 forwardEps 對照,
            # 兩者差一個匯率(20~45 倍)就換算回台幣
            try:
                fwd = num((t.info or {}).get("forwardEps"))
            except Exception:  # noqa: BLE001
                fwd = None
            if fwd and rec.get("eps1") and rec["eps1"] > 0 and 20 < fwd / rec["eps1"] < 45:
                fx = fwd / rec["eps1"]
                rec["eps0"] = None if rec.get("eps0") is None else round(rec["eps0"] * fx, 2)
                rec["eps1"] = round(rec["eps1"] * fx, 2)
                rec["usd_fixed"] = round(fx, 2)
        if pt and num(pt.get("mean")):
            rec.update(tgt=num(pt.get("mean")), tgt_lo=num(pt.get("low")), tgt_hi=num(pt.get("high")))
        if len(rec) > 1:
            return rec
    return None


def main():
    warnings.filterwarnings("ignore")
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    os.makedirs(OUT, exist_ok=True)
    try:
        old = json.load(open(os.path.join(OUT, "latest.json"), encoding="utf-8"))
    except FileNotFoundError:
        old = {}
    prev = old.get("s", {})
    # 共識一天變動不大,12 小時內抓過就不重抓(排程一天跑好幾次)
    fresh = old.get("fetched_at") and datetime.now(TZ) - datetime.fromisoformat(old["fetched_at"]) < timedelta(hours=12)
    if fresh and "--force" not in sys.argv:
        print("estimates: 12 小時內已更新,略過", file=sys.stderr)
        return
    codes = universe()
    out, t0 = {}, time.time()
    for c in codes:
        rec = fetch(c, (prev.get(c) or {}).get("sym"))
        if rec:
            out[c] = rec
        time.sleep(0.3)
    now = datetime.now(TZ)
    doc = {"fetched_at": now.isoformat(timespec="minutes"), "source": "Yahoo Finance(分析師共識)", "n": len(codes), "s": out}
    for name in ("latest.json", now.strftime("%Y-%m-%d") + ".json"):
        with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    print("estimates: %d / %d 檔有資料,%.0f 秒" % (len(out), len(codes), time.time() - t0), file=sys.stderr)


if __name__ == "__main__":
    main()
