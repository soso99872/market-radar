"""落後補漲選股規則(純函式):同題材 ≥ 2 檔發動時,找出同題材裡「營收不輸、股價還沒漲」的個股。

規則函式(launches / triggers / select)的輸入都由呼叫端傳入(不讀寫 data/),方便用固定資料測試。
  launches()  每日哪些股票「發動」(爆量突破 或 收盤創 52 週新高)的布林面板
  triggers()  第 t 日被觸發的題材(≥ 2 檔發動)與其發動者
  select()    第 t 日入選名單
回測與輸出:
  backtest()  對全部歷史逐日 select,算 20、60 日扣成本後的超額報酬統計
  build(L)    組出 data/radar/laggard.json 的內容並寫檔;L 是 signals.main() 的 locals() 或 load() 的結果
  python scripts/laggard.py  單獨執行:自己讀歷史、回測、寫檔、印摘要

爆量突破的條件與 scripts/radar.py build() 的 surge / bo 一致,但不做 20 日內只計一次的去重。
只用第 t 日(含)以前的價格,以及第 t 日已公告的月營收(M 月營收視為 M+1 月 11 日起可用,與 radar.to_daily 相同)。
"""
import json
import os
import sys
import time
from datetime import datetime

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MIN_VALUE = 0.3      # 億,當天成交金額門檻(同 radar.MIN_VALUE)
SURGE = 5            # 成交金額 ≥ 前 20 日均量幾倍(同 radar.SURGE)
MIN_LAUNCH = 2       # 同題材至少幾檔發動才算觸發
RET_DAYS = 20        # 近 N 日漲幅
COST = 0.005425      # 來回交易成本 0.5425%,出自 PRD(不是 signals.COST 的 0.585%)
HORIZONS = (20, 60)  # 持有交易日數


def launches(close, value, chg, min_value=MIN_VALUE, surge=SURGE):
    """每日發動面板。close 收盤、value 成交金額(億)、chg 漲跌幅(%),皆為 日期 × 代號 的 DataFrame。
    回傳同形狀的布林 DataFrame:爆量突破 或 收盤創 52 週新高。"""
    avg20p = value.shift(1).rolling(20, min_periods=15).mean()
    mx60 = close.shift(1).rolling(60, min_periods=50).max()
    mn60 = close.shift(1).rolling(60, min_periods=50).min()
    mx250 = close.shift(1).rolling(250, min_periods=200).max()
    boom = (value >= surge * avg20p) & (chg >= 5) & (value >= min_value)
    breakout = boom & (close >= mx60) & (mx60 / mn60 - 1 <= 0.35) & (close >= mx250)
    high52 = close > mx250     # 前面不足 200 日資料時 mx250 是 NaN,比較結果為 False
    return (breakout | high52).fillna(False).astype(bool)


def _month_key(k):
    """營收表的列索引:(年, 月) tuple 或 'YYYY-MM' 字串。"""
    if isinstance(k, str):
        y, m = k.split("-")
        return int(y), int(m)
    return int(k[0]), int(k[1])


def known_yoy(yoy, day):
    """第 day 日已公告的最新一個月的年增率(Series,index 為代號)。
    yoy:列為月份((年, 月) 或 'YYYY-MM')、欄為代號的 DataFrame。M 月營收在 M+1 月 11 日(含)起可用。
    沒有任何已公告月份就回傳空 Series。"""
    day = pd.Timestamp(day)
    best, best_key = None, None
    for i, k in enumerate(yoy.index):
        y, m = _month_key(k)
        avail = pd.Timestamp(y + (m == 12), m % 12 + 1, 11)
        if avail <= day and (best_key is None or (y, m) > best_key):
            best, best_key = i, (y, m)
    if best is None:
        return pd.Series(dtype=float)
    return yoy.iloc[best].astype(float)


def triggers(day, launched, topics, min_launch=MIN_LAUNCH):
    """第 day 日被觸發的題材。topics:{題材id: [代號...]}。
    回傳 {題材id: [當日發動者代號(排序)]},只含發動者 ≥ min_launch 的題材。"""
    row = launched.loc[day]
    fired = set(row.index[row.values])
    out = {}
    for tid, codes in topics.items():
        hit = sorted(c for c in set(codes) if c in fired)
        if len(hit) >= min_launch:
            out[tid] = hit
    return out


def select(day, close, launched, yoy, topics, restricted=(), min_launch=MIN_LAUNCH):
    """第 day 日入選名單。restricted:當日處置/注意股代號集合。
    入選:觸發題材的成員中,當日不是發動者、最新營收年增 ≥ 題材中位數、近 20 日漲幅 < 題材中位數、不在 restricted。
    中位數的母體:題材內第 day 日有收盤價的所有成員(含發動者);年增與 20 日漲幅再各自略過缺值。
    第 day 日沒有收盤價的成員(停牌、未上市)既不進母體也不會入選。一檔屬於多個觸發題材會各出現一筆。
    index 要求:close、launched 的 index 都是 DatetimeIndex 且是同一份日期(與面板一致),day 必須是其中的交易日;
    day 不在 close 或 launched 的 index 會丟 KeyError(不會悄悄退回前一個交易日)。
    回傳 list of dict:code, topic, launched(同題材發動者), yoy, ret20, yoy_median, ret20_median;依題材、代號排序。"""
    day = pd.Timestamp(day)
    for name, df in (("close", close), ("launched", launched)):
        if day not in df.index:
            raise KeyError(f"select: day {day.date()} 不在 {name} 的 index(需為面板內的交易日,index 為 DatetimeIndex)")
    px = close.loc[:day]                     # 只看 day(含)以前的價格
    pos = len(px) - 1
    if pos < RET_DAYS:
        return []
    ret20 = px.iloc[pos] / px.iloc[pos - RET_DAYS] - 1
    yy = known_yoy(yoy, day)
    restricted = set(restricted)
    out = []
    for tid, fired in sorted(triggers(day, launched.loc[:day], topics, min_launch).items()):
        members = [c for c in sorted(set(topics[tid])) if c in ret20.index and pd.notna(px.iloc[pos][c])]
        ys = pd.Series({c: yy.get(c, np.nan) for c in members}, dtype=float)
        rs = ret20.reindex(members)
        y_med, r_med = ys.median(), rs.median()   # median 會略過 NaN
        if pd.isna(y_med) or pd.isna(r_med):
            continue
        for c in members:
            if c in fired or c in restricted or pd.isna(ys[c]) or pd.isna(rs[c]):
                continue
            if ys[c] >= y_med and rs[c] < r_med:
                out.append({"code": c, "topic": tid, "launched": list(fired), "yoy": float(ys[c]),
                            "ret20": float(rs[c]), "yoy_median": float(y_med), "ret20_median": float(r_med)})
    return out


# ---------- 回測與輸出 ----------

def _r(x, nd=2):
    return None if x is None or pd.isna(x) else round(float(x), nd)


def backtest(close, opn, taiex, launched, yoy, topics, restricted=(), oos_days=None, min_launch=MIN_LAUNCH):
    """對 close 的每個交易日跑 select(launched 由呼叫端先算好,只算一次)。
    close、opn、launched:DatetimeIndex × 代號;taiex:加權指數收盤 Series(同 index)。
    進場:第 t+1 日開盤;出場:第 t+h 日收盤;報酬扣 COST;超額 = 個股報酬 - 指數 t 日收盤到 t+h 日收盤的報酬
    (指數只有收盤價,用 t 日收盤近似進場價)。沒有 t+1 或 t+h 資料的樣本排除。
    回傳 dict:triggers(觸發的 題材×日 次數)、signals(入選 題材×日 筆數)、samples(DataFrame,同一天同一檔只留一筆)、
    stats({"20": {...}, "60": {...}},欄位同 radar.evaluate 的命名,另有 med_rel、loss、stocks)。
    oos_days:最後幾個交易日算樣本外(預設 signals.OOS_DAYS,與 radar.build 的 oos_i 一致)。"""
    import signals as S
    import radar
    if oos_days is None:
        oos_days = S.OOS_DAYS
    dates = close.index
    oos_i = len(dates) - oos_days
    n_trig, rows = 0, []
    fired_n = launched.sum(axis=1)
    for pos, day in enumerate(dates):
        if fired_n.iloc[pos] < min_launch:
            continue
        trig = triggers(day, launched, topics, min_launch)
        if not trig:
            continue
        n_trig += len(trig)
        for x in select(day, close, launched, yoy, topics, restricted, min_launch):
            rows.append(dict(x, day=day, pos=pos))
    allrows = pd.DataFrame(rows)
    uniq = allrows.drop_duplicates(["day", "code"]).reset_index(drop=True) if len(allrows) else allrows
    entry = opn.shift(-1)
    stats = {}
    for h in HORIZONS:
        st = {"n": 0}
        if len(uniq):
            fwd = close.shift(-h) / entry - 1 - COST
            tx = taiex.shift(-h) / taiex - 1
            ret = np.array([fwd.at[d, c] for d, c in zip(uniq["day"], uniq["code"])], dtype=float)
            ex = ret - tx.reindex(uniq["day"]).values
            ok = ~np.isnan(ret) & ~np.isnan(ex)
            ret, ex, p = ret[ok], ex[ok], uniq["pos"].values[ok]
            if len(ret):
                daily = pd.Series(ex).groupby(p).mean().sort_index()   # 每個訊號日的平均超額
                o = p >= oos_i
                st = {"n": int(len(ret)), "stocks": int(uniq.loc[ok, "code"].nunique()), "days": int(len(daily)),
                      "avg": _r(ret.mean() * 100), "win": _r((ex > 0).mean() * 100, 1),
                      "avg_rel": _r(ex.mean() * 100), "med_rel": _r(np.median(ex) * 100),
                      "loss": _r((ret < 0).mean() * 100, 1), "t": _r(S.nw_t(daily.values, h)),
                      "oos_n": int(o.sum()), "oos_avg_rel": _r(ex[o].mean() * 100) if o.sum() else None}
        st["grade"] = radar.grade(st)
        stats[str(h)] = st
    return {"triggers": n_trig, "signals": len(allrows), "samples": uniq, "stats": stats}


def load(days=None):
    """單獨執行用:讀全部歷史,回傳和 signals.main() 的 locals() 同名的資料(只含 build 需要的)。"""
    import history
    import signals as S
    days = days or history.load_days()
    F, hi, lo, taiex, names = S.frames(days)
    return {"close": F["close"], "opn": F["open"], "F": F, "taiex": taiex, "names": names,
            "dates": list(F["close"].index), "vyi": F["value"] / 1e8}


def _restricted():
    """今日處置/注意股(data/quality/alerts.json);沒有檔就當空集合。"""
    import history
    try:
        with open(os.path.join(history.ROOT, "data", "quality", "alerts.json"), encoding="utf-8") as f:
            a = json.load(f)
    except (FileNotFoundError, ValueError):
        return set()
    return set(a.get("punish", {})) | set(a.get("notice", {}))


NOTES = [
    "處置股限制:歷史上沒有逐日處置/注意股資料,回測不排除處置股;只有今日名單用 data/quality/alerts.json 排除。",
    "題材分類偏差:回測把現在的 data/sectors/topics.json 套用到全部歷史,有事後分類的偏差(當時不一定被歸在同一題材)。",
    "報酬:第 t+1 日開盤進場、收盤出場,扣來回成本 0.5425%;超額 = 個股報酬 - 加權指數同期報酬(指數用 t 日收盤近似進場價)。",
    "同一天同一檔屬於多個觸發題材只算一個樣本;勝率以超額報酬 > 0 計,虧損機率以扣成本後個股報酬 < 0 計。",
    "連續幾天都入選的同一檔會重複出現(持有期重疊);NW t 值以每個訊號日的平均超額報酬計算,落後期用持有日數修正。",
]


def build(L, write=True):
    """L 需有 close、opn、F、taiex、names、vyi(index 為 'YYYY-MM-DD' 字串)。
    回傳輸出的 dict;write=True 時寫 data/radar/laggard.json。"""
    import history
    import radar
    import signals as S
    import topics as T
    close, opn, F, names = L["close"], L["opn"], L["F"], L["names"]
    idx = pd.to_datetime(close.index)
    cl, op, ch, va = close.copy(), opn.copy(), F["chg"].copy(), L["vyi"].copy()
    tx = L["taiex"].astype(float).copy()
    for df in (cl, op, ch, va, tx):
        df.index = idx
    rp = radar.revenue_panels(close.columns)
    if rp is None:
        print("laggard: 沒有月營收資料,略過")
        return None
    tps = {t["id"]: t["codes"] for t in T.load()}
    launched = launches(cl, va, ch)
    restricted = _restricted()
    bt = backtest(cl, op, tx, launched, rp["yoy"], tps)
    last = cl.index[-1]
    today = select(last, cl, launched, rp["yoy"], tps, restricted)
    prev = select(cl.index[-2], cl, launched, rp["yoy"], tps, restricted) if len(cl) > 1 else []
    for x in today:
        x["name"] = names.get(x["code"], x["code"])
        x["yoy"], x["ret20"] = _r(x["yoy"], 1), _r(x["ret20"] * 100, 1)
        x["yoy_median"], x["ret20_median"] = _r(x["yoy_median"], 1), _r(x["ret20_median"] * 100, 1)
    new = sorted({x["code"] for x in today} - {x["code"] for x in prev})
    stats = bt["stats"]
    out = {
        "date": str(last.date()),
        "generated_at": datetime.now(history.TZ).isoformat(timespec="minutes"),
        "list": today, "new": new,
        "backtest": {
            "period": [str(cl.index[0].date()), str(last.date())],
            "oos_start": str(cl.index[max(0, len(cl) - S.OOS_DAYS)].date()),
            "triggers": bt["triggers"], "signals": bt["signals"], "cost_pct": COST * 100,
            "horizons": stats, "grade": stats["60"]["grade"],
        },
        "advantage": stats["60"]["grade"] in ("強", "中"),
        "notes": NOTES,
    }
    if write:
        d = os.path.join(history.ROOT, "data", "radar")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "laggard.json"), "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    return out


def summary(o):
    b = o["backtest"]
    print("落後補漲 %s:今日入選 %d 檔(新進 %d)" % (o["date"], len(o["list"]), len(o["new"])))
    print("回測期間 %s ~ %s(樣本外自 %s);觸發 %d 次(題材×日)、入選 %d 筆" % (b["period"][0], b["period"][1], b["oos_start"], b["triggers"], b["signals"]))
    for h, s in b["horizons"].items():
        print("  %s 日:樣本 %s(不重複個股 %s)勝率 %s%% 平均超額 %s%% 中位數超額 %s%% 虧損機率 %s%% NW t %s 樣本外 %s%%(n=%s) grade %s"
              % (h, s["n"], s.get("stocks"), s.get("win"), s.get("avg_rel"), s.get("med_rel"), s.get("loss"), s.get("t"),
                 s.get("oos_avg_rel"), s.get("oos_n"), s["grade"]))
    print("統計優勢 advantage = %s" % o["advantage"])
    for n in o["notes"]:
        print("  注意:" + n)


def main():
    t0 = time.time()
    o = build(load())
    if o:
        summary(o)
    print("耗時 %.1f 秒" % (time.time() - t0))


if __name__ == "__main__":
    main()
