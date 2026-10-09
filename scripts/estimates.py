"""分析師共識預估(Yahoo Finance 匯總):今年 / 明年 EPS 預估、目標價。

輸出 data/estimates/latest.json,並每天存一份 data/estimates/YYYY-MM-DD.json 快照
(免費來源沒有歷史共識,只能從現在開始累積,之後才能回測)。
  {代號: {"eps0": 今年 EPS 預估, "eps1": 明年, "n0", "n1": 分析師數, "tgt": 平均目標價, "tgt_lo", "tgt_hi", "n_tgt", "sym"}}
起漲雷達名單、觀察名單與板塊成分股每 12 小時更新;其他股票每次輪流補最舊的 300 檔(全市場一次抓完會超過排程時限)。

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


EXTRA_PER_RUN = int(os.environ.get("EST_EXTRA", 300))    # 重點股以外,每次輪流補幾檔(全市場約 1950 檔,一次抓完會超過排程時限)
FRESH = timedelta(hours=12)
KEEP = timedelta(days=30)   # 超過 30 天沒更新到的資料不再使用


def main():
    warnings.filterwarnings("ignore")
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    os.makedirs(OUT, exist_ok=True)
    try:
        old = json.load(open(os.path.join(OUT, "latest.json"), encoding="utf-8"))
    except FileNotFoundError:
        old = {}
    now = datetime.now(TZ)
    prev = old.get("s", {})
    old_at = old.get("fetched_at")
    for c, v in prev.items():   # 舊格式沒有每檔時間,用整份的抓取時間
        v.setdefault("at", old_at)
    for c, a_ in (old.get("checked") or {}).items():   # 查過但沒有分析師的也要記住,不然每次都重查
        prev.setdefault(c, {"at": a_, "none": True})

    def age(c):
        a = (prev.get(c) or {}).get("at")
        return now - datetime.fromisoformat(a) if a else timedelta(days=999)

    core = universe()
    try:   # 全市場(查詢索引)
        allc = sorted(json.load(open(os.path.join(ROOT, "data/stocks/index.json"), encoding="utf-8"))["s"])
    except (OSError, ValueError, KeyError):
        allc = []
    force = "--force" in sys.argv
    todo = [c for c in core if force or age(c) > FRESH]
    rest = sorted((c for c in allc if c not in set(core) and (force or age(c) > FRESH)), key=lambda c: -age(c).total_seconds())
    todo += rest[:EXTRA_PER_RUN]
    if not todo:
        print("estimates: 全部 12 小時內已更新,略過", file=sys.stderr)
        return
    out, t0, got = dict(prev), time.time(), 0
    for c in todo:
        rec = fetch(c, (prev.get(c) or {}).get("sym"))
        if rec:
            rec["at"] = now.isoformat(timespec="minutes")
            out[c] = rec
            got += 1
        elif c in out:
            out[c]["at"] = now.isoformat(timespec="minutes")   # 查過但沒有分析師,記下時間避免一直重查
            out[c]["none"] = True
        else:
            out[c] = {"at": now.isoformat(timespec="minutes"), "none": True}
        time.sleep(0.3)
    out = {c: v for c, v in out.items() if v.get("at") and now - datetime.fromisoformat(v["at"]) < KEEP}
    has = {c: v for c, v in out.items() if not v.get("none")}
    doc = {"fetched_at": now.isoformat(timespec="minutes"), "source": "Yahoo Finance(分析師共識)", "n": len(out), "s": has,
           "checked": {c: v["at"] for c, v in out.items() if v.get("none")}}
    for name in ("latest.json", now.strftime("%Y-%m-%d") + ".json"):
        with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    print("estimates: 本次 %d 檔(重點 %d),有預估 %d;累計有預估 %d / 已查 %d,%.0f 秒" % (
        len(todo), len([c for c in todo if c in set(core)]), got, len(has), len(out), time.time() - t0), file=sys.stderr)

if __name__ == "__main__":
    main()
