"""籌碼訊號回測與每日訊號。

讀 data/history/ 的個股歷史,對每個訊號計算「出現後 5/10/20 個交易日」的表現,輸出:
  data/signals/stats.json   各訊號的歷史統計(勝率、平均超額報酬、樣本外、多空頭分開)
  data/signals/today.json   最新交易日觸發訊號的個股
  data/stocks/CODE.json     個股頁資料(近 120 日 K 線、法人買賣超、訊號標記)

回測假設(盡量貼近實際可執行):
- 訊號在 t 日收盤後才知道,t+1 日開盤價進場,t+h 日收盤出場。
- 扣除來回交易成本 0.585%(手續費 0.1425% × 2 + 證交稅 0.3%)。
- 主要指標「相對報酬」= 個股報酬 − 同一天所有流動股的平均報酬(扣掉大盤漲跌與權值股影響,
  回答「這個訊號挑出的股票,有沒有比隨便挑一檔好」)。
- 次要指標「跑贏大盤」= 個股報酬 − 同期加權指數報酬(指數用 t 到 t+h 收盤,為近似)。
- 只計流動性足夠的股票:近 20 日平均成交金額 ≥ 1 億。
- 連續型訊號只計第一天(事件),避免同一段行情重複計算。
限制:歷史資料只含目前仍掛牌的股票(已下市的不在裡面),結果會略為偏樂觀;
t+1 漲停買不到的情況沒有排除。
"""
import json
import math
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import history  # noqa: E402

ROOT = history.ROOT
OUT_DIR = os.path.join(ROOT, "data", "signals")
STOCK_DIR = os.path.join(ROOT, "data", "stocks")
THEMES = os.path.join(ROOT, "data", "sectors", "themes.json")
COST = 0.00585
HORIZONS = (5, 10, 20)
OOS_DAYS = 250
# 同時檢驗的條件有數十個(訊號 × 持有天數),單看 t ≥ 2 會把運氣誤認成優勢,門檻依多重比較拉高
T_STRONG = 3.5
T_MID = 2.5
STOCK_DAYS = 120

SIGNALS = {
    "contra1": {"name": "當日逆勢買超", "desc": "股價收跌,但三大法人當日淨買超 ≥ 0.3 億"},
    "contra1s": {"name": "當日逆勢買超(強)", "desc": "同上,且法人買超佔當日成交金額 ≥ 10%"},
    "contra5": {"name": "5 日逆勢買超", "desc": "近 5 日股價下跌,但三大法人 5 日累計淨買超 ≥ 1 億"},
    "trust3": {"name": "投信連買 3 天", "desc": "投信連續第 3 天買超,且 3 日累計 ≥ 0.5 億(只計第 3 天)"},
    "foreign5": {"name": "外資連買 5 天", "desc": "外資連續第 5 天買超,且 5 日累計 ≥ 2 億(只計第 5 天)"},
    "turn": {"name": "法人轉買", "desc": "三大法人連賣 5 天後,當日轉為淨買超 ≥ 0.5 億"},
    "high52": {"name": "創 52 週新高且量增", "desc": "收盤創近 250 日新高,成交金額 ≥ 20 日均量 2 倍(20 日內只計一次)"},
    "accum": {"name": "籌碼默默累積、股價未發動",
              "desc": "近 20 日法人有 ≥ 12 天買超、累計買超 ≥ 同期成交金額 3%,但股價 20 日漲跌在 −5%~+10%、仍在 60 日高點 85% 以上(10 日內只計一次)"},
    "overheat": {"name": "短線過熱", "desc": "股價高於 60 日均線 30% 以上,且 20 日漲幅 ≥ 25%(20 日內只計一次)"},
    # 以下是「觀察名單」用的狀態型訊號:每天符合條件就算一筆,t 值已用日期聚合與重疊修正
    "w_pick": {"name": "資金流入板塊中的法人買超股", "group": "watch", "bench": "members",
               "desc": "所屬板塊 20 日與 5 日法人皆淨流入,且個股 20 日法人買超佔成交金額在全市場前 30%"},
    "w_pick_quiet": {"name": "同上,但股價尚未發動", "group": "watch", "bench": "members",
                     "desc": "符合上一項,且股價 20 日漲幅 ≤ 10%"},
    "w_pick_moving": {"name": "同上,且股價已發動", "group": "watch", "bench": "members",
                      "desc": "符合上一項,且股價 20 日漲幅 > 10%"},
    "w_theme_out": {"name": "資金持續撤出的板塊", "group": "watch", "bench": "members",
                    "desc": "所屬板塊 20 日與 5 日法人皆淨流出(且不屬於任何流入中的板塊)"},
    "w_theme_bottom": {"name": "資金排名墊底的板塊", "group": "watch", "bench": "members",
                       "desc": "所屬板塊 20 日法人買賣超佔成交比,排在所有板塊最後 5 名"},
    "w_dump": {"name": "法人持續調節", "group": "watch",
               "desc": "個股 20 日法人買賣超佔成交金額,在全市場最後 10%"},
    "w_stretch": {"name": "大幅偏離季線", "group": "watch",
                  "desc": "股價高於 60 日均線 50% 以上"},
}


EVENTS = [k for k, v in SIGNALS.items() if not v.get("group")]
WATCH_DIR = os.path.join(ROOT, "data", "watch")
FUND = os.path.join(ROOT, "data", "fundamentals", "latest.json")


def frames(days):
    """把逐日資料轉成 日期 × 代號 的矩陣。"""
    dates = [d["date"] for d in days]
    cols = {k: {} for k in ("open", "close", "value", "chg", "fo", "tr", "de")}
    names = {}
    for d in days:
        for c, r in d["s"].items():
            names[c] = r[history.NAME]
    idx = {k: i for k, i in (("open", history.OPEN), ("close", history.CLOSE), ("value", history.VALUE),
                             ("chg", history.CHG), ("fo", history.FOREIGN), ("tr", history.TRUST),
                             ("de", history.DEALER))}
    for k, i in idx.items():
        cols[k] = pd.DataFrame({d["date"]: {c: r[i] for c, r in d["s"].items()} for d in days}).T.reindex(dates)
    taiex = pd.Series({d["date"]: (d.get("taiex") or [None])[0] for d in days}).reindex(dates).astype(float)
    hi = pd.DataFrame({d["date"]: {c: r[history.HIGH] for c, r in d["s"].items()} for d in days}).T.reindex(dates)
    lo = pd.DataFrame({d["date"]: {c: r[history.LOW] for c, r in d["s"].items()} for d in days}).T.reindex(dates)
    # 還原權值:交易所的漲跌價差是對除權息、減資、分割後的參考價算的,用它逐日串起來就是還原股價。
    # 不還原的話,國巨 2025/08 一拆四會被當成跌 74%、減資恢復交易會被當成暴漲。縮放成最後一天 = 實際股價。
    # 除權息、恢復交易當天交易所的漲跌標「X」、價差為 0,這天改用實際價差;但實際價差超過 ±10%(超過漲跌幅限制)
    # 一定是分割或減資,當天報酬視為 0。所以股利沒有還原(與原本相同),只排除股本變動造成的假漲跌。
    raw = cols["close"]
    rr = raw / raw.ffill().shift(1) - 1
    ret = cols["chg"] / 100
    xday = (cols["chg"] == 0) & (rr != 0)
    ret = ret.where(~xday, rr.where(rr.abs() <= 0.10, 0.0))
    idx_ = (1 + ret.where(raw.notna())).fillna(1).cumprod().where(raw.notna())
    k = (idx_ / raw).ffill().iloc[-1] if len(raw) else 1
    factor = idx_ / raw / k
    cols["close_raw"] = raw
    cols["close"] = raw * factor
    cols["open"] = cols["open"] * factor
    hi, lo = hi * factor, lo * factor
    return cols, hi, lo, taiex, names


def wilson(p, n, z=1.96):
    if n == 0:
        return None, None
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return round((c - h) * 100, 1), round((c + h) * 100, 1)


def nw_t(x, lag):
    """Newey-West t 值:x 是依日期排序的「每日平均相對報酬」,持有期重疊造成的自相關用 lag 修正。"""
    x = np.asarray(x, dtype=float)
    d = len(x)
    if d < 3:
        return 0.0
    e = x - x.mean()
    var = float(e @ e) / d
    for k in range(1, min(lag, d - 1) + 1):
        var += 2 * (1 - k / (lag + 1)) * float(e[k:] @ e[:-k]) / d
    return float(x.mean() / math.sqrt(var / d)) if var > 0 else 0.0


def summarize(rel, ex, ret, pos=None, h=1):
    """rel / ex / ret:相對一般個股、相對大盤、絕對報酬的一維陣列(已去除 NaN);pos = 各筆的日期序號。
    同一天多檔股票同時觸發、持有期互相重疊都會讓樣本看起來比實際多,
    所以 t 值改用「每天的平均相對報酬」這條序列,並以 Newey-West 修正重疊。"""
    n = len(rel)
    if n == 0:
        return {"n": 0}
    win = float((rel > 0).mean())
    if pos is None:
        pos = np.arange(n)
    daily = pd.Series(rel).groupby(np.asarray(pos)).mean().sort_index()
    t = nw_t(daily.values, h)
    lo, hi = wilson(win, n)
    return {
        "n": int(n), "days": int(len(daily)),
        "win": round(win * 100, 1), "win_ci": [lo, hi],
        "avg_rel": round(float(rel.mean()) * 100, 2),
        "med_rel": round(float(np.median(rel)) * 100, 2),
        "t": round(t, 2),
        "win_mkt": round(float((ex > 0).mean()) * 100, 1),
        "avg_ex": round(float(ex.mean()) * 100, 2),
        "abs_win": round(float((ret > 0).mean()) * 100, 1),
        "avg_ret": round(float(ret.mean()) * 100, 2),
    }


def grade(full, oos):
    """證據強度:看「相對一般個股」是否顯著、近一年(樣本外)是否同方向。"""
    if full.get("n", 0) < 30:
        return "樣本不足"
    same_up = oos.get("n", 0) >= 15 and oos["avg_rel"] > 0
    same_dn = oos.get("n", 0) >= 15 and oos["avg_rel"] < 0
    if full["t"] >= T_STRONG and same_up and full["avg_rel"] >= 0.3:
        return "強"
    if full["t"] >= T_MID and same_up:
        return "中"
    if full["t"] <= -T_MID and same_dn:
        return "反向"
    return "弱"


def main():
    days = history.load_days()
    if len(days) < 80:
        sys.exit("歷史資料不足(%d 天),先跑 history.py backfill" % len(days))
    F, hi, lo, taiex, names = frames(days)
    dates = list(F["close"].index)
    close, opn, value = F["close"], F["open"], F["value"]
    to_yi = close / 1e8
    net = (F["fo"] + F["tr"] + F["de"]) * to_yi
    fo, tr = F["fo"] * to_yi, F["tr"] * to_yi
    vyi = value / 1e8
    avg20 = value.rolling(20, min_periods=10).mean()
    liquid = avg20 >= 1e8

    def first(sig, gap=1):
        """事件化:只保留前 gap 天內沒出現過的訊號。"""
        prev = sig.shift(1).fillna(False).astype(bool)
        for k in range(2, gap + 1):
            prev = prev | sig.shift(k).fillna(False).astype(bool)
        return sig & ~prev

    def streak_eq(pos, k):
        s = pos.copy()
        for i in range(1, k):
            s = s & pos.shift(i).fillna(False).astype(bool)
        return s & ~pos.shift(k).fillna(False).astype(bool)

    ret5 = close / close.shift(5) - 1
    sig = {}
    sig["contra1"] = (F["chg"] < 0) & (net >= 0.3) & liquid
    sig["contra1s"] = sig["contra1"] & (net / vyi >= 0.10)
    sig["contra5"] = first((ret5 < 0) & (net.rolling(5).sum() >= 1) & liquid, 5)
    sig["trust3"] = streak_eq(F["tr"] > 0, 3) & (tr.rolling(3).sum() >= 0.5) & liquid
    sig["foreign5"] = streak_eq(F["fo"] > 0, 5) & (fo.rolling(5).sum() >= 2) & liquid
    sold5 = (net.shift(1) < 0)
    for i in range(2, 6):
        sold5 = sold5 & (net.shift(i) < 0)
    sig["turn"] = sold5 & (net >= 0.5) & liquid
    prior_max = close.shift(1).rolling(250, min_periods=200).max()
    sig["high52"] = first((close >= prior_max) & (value >= 2 * avg20) & liquid, 20)

    net20 = net.rolling(20, min_periods=20).sum()
    buy_days20 = (net > 0).astype(float).rolling(20, min_periods=20).sum()
    ret20 = close / close.shift(20) - 1
    max60 = close.rolling(60, min_periods=40).max()
    ma60 = close.rolling(60, min_periods=40).mean()
    accum_now = ((buy_days20 >= 12) & (net20 >= 0.03 * vyi.rolling(20).sum()) & (ret20 >= -0.05) & (ret20 <= 0.10)
                 & (close >= 0.85 * max60) & liquid)
    sig["accum"] = first(accum_now, 10)
    hot_now = (close / ma60 - 1 >= 0.30) & (ret20 >= 0.25) & liquid
    sig["overheat"] = first(hot_now, 20)

    # 板塊資金狀態
    theme_list = load_themes()
    is_mem = pd.DataFrame(False, index=close.index, columns=close.columns)
    th_in, th_out, th_bot = is_mem.copy(), is_mem.copy(), is_mem.copy()
    tflow, tratio = {}, {}
    for th in theme_list:
        mem = [c for c in th["codes"] if c in close.columns]
        if len(mem) < 3:
            continue
        sm = net[mem].sum(axis=1)
        tflow[th["id"]] = (sm.rolling(20).sum(), sm.rolling(5).sum(), mem)
        tratio[th["id"]] = sm.rolling(20).sum() / vyi[mem].sum(axis=1).rolling(20).sum()
    TR = pd.DataFrame(tratio)
    trank = TR.rank(axis=1, ascending=False)
    nth = TR.notna().sum(axis=1)
    for tid, (s20, s5, mem) in tflow.items():
        cols = lambda b: np.repeat(b.fillna(False).values[:, None], len(mem), axis=1)  # noqa: E731
        is_mem.loc[:, mem] = True
        th_in.loc[:, mem] = th_in[mem].values | cols((s20 > 0) & (s5 > 0))
        th_out.loc[:, mem] = th_out[mem].values | cols((s20 < 0) & (s5 < 0))
        th_bot.loc[:, mem] = th_bot[mem].values | cols(trank[tid] > nth - 5)
    value20 = vyi.rolling(20, min_periods=20).sum()
    ratio20 = net20 / value20
    rk_n = ratio20.where(liquid).rank(axis=1, pct=True)
    sig["w_pick"] = th_in & (rk_n > 0.7) & liquid
    sig["w_pick_quiet"] = sig["w_pick"] & (ret20 <= 0.10)
    sig["w_pick_moving"] = sig["w_pick"] & (ret20 > 0.10)
    sig["w_theme_out"] = th_out & ~th_in & liquid
    sig["w_theme_bottom"] = th_bot & ~th_in & liquid
    sig["w_dump"] = (rk_n <= 0.1) & liquid
    sig["w_stretch"] = (close / ma60 - 1 >= 0.5) & liquid

    # 前瞻報酬:t+1 開盤進場,t+h 收盤出場
    fwd, bench = {}, {}
    entry = opn.shift(-1)
    xs, xs_m = {}, {}
    for h in HORIZONS:
        fwd[h] = close.shift(-h) / entry - 1 - COST
        bench[h] = taiex.shift(-h) / taiex - 1
        xs[h] = fwd[h].where(liquid).mean(axis=1)   # 同一天所有流動股的平均報酬
        # 板塊類訊號改跟「所有板塊成分股」比:板塊清單是現在挑的,事後看本來就偏強勢產業,
        # 跟成分股平均比才能扣掉這個後見之明
        xs_m[h] = fwd[h].where(liquid & is_mem).mean(axis=1)
    above60 = taiex > taiex.rolling(60, min_periods=40).mean()
    oos_start = dates[-OOS_DAYS] if len(dates) > OOS_DAYS + 60 else dates[len(dates) // 2]

    dpos = {d: i for i, d in enumerate(dates)}

    def collect(mask, h, rows=None, ref=None):
        m = mask.copy()
        if rows is not None:
            m = m.loc[rows]
        r = fwd[h].loc[m.index].where(m)
        ex = r.sub(bench[h].loc[m.index], axis=0)
        rel = r.sub((ref or xs)[h].loc[m.index], axis=0)
        rv, ev, lv = r.values.ravel(), ex.values.ravel(), rel.values.ravel()
        pos = np.repeat(np.array([dpos[d] for d in m.index]), r.shape[1])
        ok = ~np.isnan(rv) & ~np.isnan(ev) & ~np.isnan(lv)
        return lv[ok], ev[ok], rv[ok], pos[ok]

    oos_rows = [d for d in dates if d >= oos_start]
    bull_rows = [d for d in dates if above60.get(d, False)]
    bear_rows = [d for d in dates if not above60.get(d, False)]

    base = {}
    for h in HORIZONS:
        base[str(h)] = summarize(*collect(liquid, h), h=h)

    stats = {}
    for sid, meta in SIGNALS.items():
        s = sig[sid].fillna(False).astype(bool)
        ref = xs_m if meta.get("bench") == "members" else xs
        hz = {}
        for h in HORIZONS:
            full = summarize(*collect(s, h, ref=ref), h=h)
            oos = summarize(*collect(s, h, oos_rows, ref=ref), h=h)
            hz[str(h)] = {
                "all": full, "oos": oos,
                "bull": summarize(*collect(s, h, bull_rows, ref=ref), h=h),
                "bear": summarize(*collect(s, h, bear_rows, ref=ref), h=h),
                "grade": grade(full, oos),
            }
        stats[sid] = dict(meta, horizons=hz)

    # 板塊翻轉:板塊 5 日法人淨買賣超由負轉正,以成分股等權平均報酬計
    flip = {h: ([], [], [], []) for h in HORIZONS}
    flip_oos = {h: ([], [], [], []) for h in HORIZONS}
    flips_today = []
    for th in theme_list:
        mem = [c for c in th["codes"] if c in close.columns]
        if len(mem) < 3:
            continue
        s5 = net[mem].sum(axis=1).rolling(5).sum()
        fl = (s5 > 0) & (s5.shift(1) <= 0)
        fl = fl & ~(fl.shift(1).fillna(False) | fl.shift(2).fillna(False) | fl.shift(3).fillna(False)
                    | fl.shift(4).fillna(False) | fl.shift(5).fillna(False))
        if bool(fl.iloc[-1]):
            flips_today.append({"id": th["id"], "name": th["name"], "net5": round(float(s5.iloc[-1]), 2)})
        for h in HORIZONS:
            r = fwd[h][mem].mean(axis=1)
            ex, rel = r - bench[h], r - xs_m[h]
            for d in fl.index[fl.fillna(False).astype(bool)]:
                if pd.isna(r[d]) or pd.isna(ex[d]) or pd.isna(rel[d]):
                    continue
                for bucket in ((flip[h],) + ((flip_oos[h],) if d >= oos_start else ())):
                    bucket[0].append(rel[d])
                    bucket[1].append(ex[d])
                    bucket[2].append(r[d])
                    bucket[3].append(dpos[d])
    hz = {}
    for h in HORIZONS:
        full = summarize(*[np.array(x) for x in flip[h]], h=h)
        oos = summarize(*[np.array(x) for x in flip_oos[h]], h=h)
        hz[str(h)] = {"all": full, "oos": oos, "grade": grade(full, oos)}
    stats["sector_flip"] = {"name": "板塊資金翻正", "desc": "板塊成分股 5 日法人淨買賣超合計由負轉正(以成分股等權組合計算報酬,跟所有板塊成分股平均比)",
                            "level": "sector", "bench": "members", "horizons": hz}

    span = [dates[0], dates[-1]]
    meta = {
        "generated_at": datetime.now(history.TZ).isoformat(timespec="minutes"),
        "span": span, "days": len(dates), "oos_start": oos_start,
        "regime_now": "多頭(加權指數在 60 日均線之上)" if bool(above60.iloc[-1]) else "空頭(加權指數在 60 日均線之下)",
        "cost_pct": COST * 100,
        "method": __doc__.split("回測假設")[1].strip() if "回測假設" in __doc__ else "",
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "stats.json"), "w", encoding="utf-8") as f:
        json.dump(dict(meta, baseline=base, signals=stats), f, ensure_ascii=False, separators=(",", ":"))

    # 今日觸發
    last = dates[-1]
    themes = history_themes()
    hits = {}
    for sid in EVENTS:
        row = sig[sid].loc[last].fillna(False).astype(bool)
        codes = list(row[row].index)
        items = []
        for c in codes:
            items.append({
                "code": c, "name": names.get(c, c), "close": float(close.at[last, c]),
                "chg": float(F["chg"].at[last, c]),
                "net": round(float(net.at[last, c]), 2), "ratio": round(float(net.at[last, c] / vyi.at[last, c] * 100), 1) if vyi.at[last, c] else None,
                "net5": round(float(net[c].iloc[-5:].sum()), 2),
                "ret5": round(float(ret5.at[last, c]) * 100, 2) if not pd.isna(ret5.at[last, c]) else None,
                "themes": themes.get(c, []),
            })
        items.sort(key=lambda x: -(x["ratio"] or 0))
        hits[sid] = items
    with open(os.path.join(OUT_DIR, "today.json"), "w", encoding="utf-8") as f:
        json.dump({"date": last, "generated_at": meta["generated_at"], "regime_now": meta["regime_now"], "hits": hits,
                   "sector_flips": flips_today},
                  f, ensure_ascii=False, separators=(",", ":"))

    watch = build_watch(locals())
    os.makedirs(WATCH_DIR, exist_ok=True)
    with open(os.path.join(WATCH_DIR, "latest.json"), "w", encoding="utf-8") as f:
        json.dump(watch, f, ensure_ascii=False, separators=(",", ":"))

    rd = radar.build(locals()) or {"rev": [], "breakout": []}

    # 個股頁:板塊成分股 + 近 20 日有訊號的股票 + 觀察名單 + 起漲雷達
    recent = dates[-20:]
    universe = set(themes) | {x["code"] for k in ("picks", "dump", "stretch") for x in watch[k]}
    universe |= {x["code"] for k in ("rev", "breakout", "theme") for x in rd.get(k, [])}
    for sid in EVENTS:
        m = sig[sid].loc[recent].fillna(False).astype(bool)
        universe |= set(m.columns[m.any()])
    os.makedirs(STOCK_DIR, exist_ok=True)
    keep = set()
    tail = dates[-STOCK_DAYS:]
    for c in sorted(universe):
        if c not in close.columns or pd.isna(close.at[last, c]):
            continue
        rows = []
        for d in tail:
            if pd.isna(close.at[d, c]):
                continue
            rows.append([d, opn.at[d, c], hi.at[d, c], lo.at[d, c], close.at[d, c],
                         round(float(vyi.at[d, c]), 2), round(float(fo.at[d, c]), 2), round(float(tr.at[d, c]), 2),
                         round(float((F["de"].at[d, c]) * to_yi.at[d, c]), 2)])
        marks = []
        for sid in EVENTS:
            m = sig[sid].loc[tail, c].fillna(False).astype(bool)
            marks += [[d, sid] for d in m.index[m]]
        marks.sort()

        def streak(series):
            n = 0
            for v in reversed(series.tolist()):
                if v > 0:
                    n += 1
                else:
                    break
            return n

        doc = {
            "code": c, "name": names.get(c, c), "date": last, "themes": themes.get(c, []),
            "fields": ["date", "open", "high", "low", "close", "value", "foreign", "trust", "dealer"],
            "rows": [[x if isinstance(x, str) else (None if pd.isna(x) else float(x)) for x in r] for r in rows],
            "signals": marks,
            "extra": radar.EXTRAS.get(c),
            "rating": radar.RATING.get(c) or {"stars": 1, "tier": None, "traps": []},
            "health": radar.SNAP.get(c),
            "summary": {
                "close": float(close.at[last, c]), "chg": float(F["chg"].at[last, c]),
                "ret5": None if pd.isna(ret5.at[last, c]) else round(float(ret5.at[last, c]) * 100, 2),
                "ret20": None if pd.isna(close.at[dates[-21], c]) else round(float(close.at[last, c] / close.at[dates[-21], c] - 1) * 100, 2),
                "net5": round(float(net[c].iloc[-5:].sum()), 2), "net20": round(float(net[c].iloc[-20:].sum()), 2),
                "foreign_streak": streak(F["fo"][c]), "trust_streak": streak(F["tr"][c]),
                "avg_value20": round(float(avg20.at[last, c]) / 1e8, 2) if not pd.isna(avg20.at[last, c]) else None,
                "high250": None if pd.isna(prior_max.at[last, c]) else float(prior_max.at[last, c]),
            },
        }
        with open(os.path.join(STOCK_DIR, c + ".json"), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
        keep.add(c + ".json")
    for n in os.listdir(STOCK_DIR):
        if n.endswith(".json") and n not in keep and n not in ("index.json", "search.json"):
            os.remove(os.path.join(STOCK_DIR, n))
    write_index(close, F, names, last, keep)
    print("OK", span, "signals", {k: len(v) for k, v in hits.items()}, "stocks", len(keep))


def write_index(close, F, names, last, keep):
    """查詢用索引:全部有收盤價的股票,含星等與幾個關鍵數字;有詳細面板的標 p=1。"""
    s = {}
    for c in close.columns:
        px = close.at[last, c]
        if pd.isna(px):
            continue
        r = radar.RATING.get(c) or {}
        n = radar.SNAP.get(c, {})
        s[c] = [names.get(c, c), r.get("stars", 1), r.get("tier"), _f(F["close_raw"].at[last, c]), _f(F["chg"].at[last, c]),
                n.get("ret60"), n.get("ind"), n.get("yoy"), n.get("yoy3"), n.get("rev_month"), 1 if c + ".json" in keep else 0,
                r.get("traps") or [], n]
    # 搜尋用的輕量索引(代號 → [名稱, 星等]),打字時才不用下載整份 index.json
    with open(os.path.join(STOCK_DIR, "search.json"), "w", encoding="utf-8") as f:
        json.dump({"date": last, "s": {c: [v[0], v[1]] for c, v in s.items()}}, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(STOCK_DIR, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"date": last, "fields": ["name", "stars", "tier", "close", "chg", "ret60", "ind", "yoy", "yoy3", "rev_month", "panel", "traps", "health"],
                   "s": s}, f, ensure_ascii=False, separators=(",", ":"))


def _streak(series, sign=1):
    n = 0
    for v in reversed(series.tolist()):
        if v is not None and not pd.isna(v) and v * sign > 0:
            n += 1
        else:
            break
    return n


def _f(x, nd=2):
    return None if x is None or pd.isna(x) else round(float(x), nd)


def build_watch(L):
    """觀察名單:板塊資金趨勢、值得觀察的個股、要留意風險的個股,附上條列原因。"""
    last, close, net, fo, tr, F = L["last"], L["close"], L["net"], L["fo"], L["tr"], L["F"]
    ratio20, rk_n, net20, bd20 = L["ratio20"], L["rk_n"], L["net20"], L["buy_days20"]
    ret20, ret5, ma60, hi250 = L["ret20"], L["ret5"], L["ma60"], L["prior_max"]
    names, themes, tflow, TR, trank, nth = L["names"], L["themes"], L["tflow"], L["TR"], L["trank"], L["nth"]
    try:
        with open(FUND, encoding="utf-8") as f:
            fund = json.load(f)
    except FileNotFoundError:
        fund = {"val": {}, "rev": {}, "rev_month": None}
    val, rev, rev_m = fund.get("val", {}), fund.get("rev", {}), fund.get("rev_month")
    theme_name = {th["id"]: th["name"] for th in L["theme_list"]}

    # 板塊
    tlist, tinfo = [], {}
    n_t = int(nth.loc[last])
    for tid, (s20, s5, mem) in tflow.items():
        r20 = ret20.loc[last, mem].dropna()
        pes = [val[c][0] for c in mem if c in val and val[c][0] and val[c][0] > 0]
        yoys = [rev[c][0] for c in mem if c in rev and rev[c][0] is not None]
        a, b = float(s20.loc[last]), float(s5.loc[last])
        state = "流入" if a > 0 and b > 0 else "流出" if a < 0 and b < 0 else "轉弱" if a > 0 else "回流"
        rank = int(trank.loc[last, tid])
        info = {
            "id": tid, "name": theme_name[tid], "state": state, "net20": round(a, 1), "net5": round(b, 1),
            "ratio20": _f(TR.at[last, tid] * 100), "rank": rank, "of": n_t, "bottom": rank > n_t - 5,
            "ret20": _f(r20.mean() * 100) if len(r20) else None,
            "pe_med": _f(np.median(pes), 1) if len(pes) >= 3 else None,
            "rev_yoy_med": _f(np.median(yoys), 1) if len(yoys) >= 3 else None,
            "trend": [_f(x * 100) for x in TR[tid].iloc[-60:].values],
        }
        tinfo[tid] = info
        tlist.append(info)
    tlist.sort(key=lambda x: x["rank"])

    def common(c):
        cl = float(close.at[last, c])
        v = val.get(c) or [None, None, None]
        rv = rev.get(c) or [None, None, None]
        pe_meds = [tinfo[t["id"]]["pe_med"] for t in themes.get(c, []) if t["id"] in tinfo and tinfo[t["id"]]["pe_med"]]
        bd = bd20.at[last, c]
        return {
            "code": c, "name": names.get(c, c), "close": cl, "chg": _f(F["chg"].at[last, c]),
            "ret5": _f(ret5.at[last, c] * 100), "ret20": _f(ret20.at[last, c] * 100),
            "net20": _f(net20.at[last, c], 1), "ratio20": _f(ratio20.at[last, c] * 100, 1),
            "pct": _f(rk_n.at[last, c] * 100, 0), "buy_days20": None if pd.isna(bd) else int(bd),
            "net5": _f(net[c].iloc[-5:].sum(), 1),
            "fo_streak": _streak(F["fo"][c]), "tr_streak": _streak(F["tr"][c]),
            "fo_sell": _streak(F["fo"][c], -1), "tr_sell": _streak(F["tr"][c], -1),
            "fo20": _f(fo[c].iloc[-20:].sum(), 1), "tr20": _f(tr[c].iloc[-20:].sum(), 1),
            "ma60": None if pd.isna(ma60.at[last, c]) else _f((cl / ma60.at[last, c] - 1) * 100, 1),
            "hi250": None if pd.isna(hi250.at[last, c]) else _f((cl / hi250.at[last, c] - 1) * 100, 1),
            "pe": v[0], "pb": v[1], "yld": v[2], "pe_med": min(pe_meds) if pe_meds else None,
            "rev_yoy": rv[0], "rev_cum": rv[2],
            "themes": themes.get(c, []),
        }

    def val_reason(x, out):
        if x["pe"] and x["pe_med"]:
            r = x["pe"] / x["pe_med"]
            if r <= 0.75:
                out.append("本益比 %.1f 倍,低於同板塊中位數 %.1f 倍" % (x["pe"], x["pe_med"]))
            elif r >= 1.6:
                out.append("本益比 %.1f 倍,高於同板塊中位數 %.1f 倍" % (x["pe"], x["pe_med"]))
        elif x["pe"] is None and x["pb"]:
            out.append("近四季虧損(無本益比)")
        if x["rev_yoy"] is not None and rev_m:
            mon = rev_m[5:].lstrip("0")
            if x["rev_yoy"] >= 20:
                out.append("%s 月營收年增 %+.0f%%" % (mon, x["rev_yoy"]))
            elif x["rev_yoy"] <= -20:
                out.append("%s 月營收年減 %.0f%%" % (mon, -x["rev_yoy"]))

    def today(sid):
        row = L["sig"][sid].loc[last].fillna(False).astype(bool)
        return list(row[row].index)

    # 值得觀察:資金流入板塊 + 個股法人買超前 30%
    picks = []
    for c in today("w_pick"):
        x = common(c)
        why = []
        ins = [t for t in themes.get(c, []) if t["id"] in tinfo and tinfo[t["id"]]["state"] == "流入"]
        if ins:
            ti = tinfo[max(ins, key=lambda t: tinfo[t["id"]]["net20"])["id"]]
            why.append("所屬「%s」板塊 20 日法人淨流入 %+.0f 億(資金排名 %d/%d),近 5 日仍在流入"
                       % (ti["name"], ti["net20"], ti["rank"], ti["of"]))
        why.append("個股 20 日法人買超 %+.1f 億,佔成交金額 %.1f%%(全市場前 %d%%)"
                   % (x["net20"], x["ratio20"], max(1, 100 - int(x["pct"]))))
        if x["buy_days20"] is not None and x["buy_days20"] >= 13:
            why.append("20 個交易日中有 %d 天法人買超,買盤持續" % x["buy_days20"])
        if x["tr_streak"] >= 3:
            why.append("投信連買 %d 天(20 日累計 %+.1f 億)" % (x["tr_streak"], x["tr20"]))
        if x["fo_streak"] >= 3:
            why.append("外資連買 %d 天(20 日累計 %+.1f 億)" % (x["fo_streak"], x["fo20"]))
        if x["hi250"] is not None and x["hi250"] >= -3:
            why.append("股價接近或創 52 週新高")
        val_reason(x, why)
        risk = []
        if x["ma60"] is not None and x["ma60"] >= 30:
            risk.append("已高於季線 %.0f%%,追高風險大" % x["ma60"])
        if x["net5"] is not None and x["net5"] < 0:
            risk.append("近 5 日法人轉為賣超 %.1f 億" % x["net5"])
        x["stage"] = "未發動" if (x["ret20"] or 0) <= 10 else "已發動"
        x["why"], x["risk"] = why, risk
        picks.append(x)
    picks.sort(key=lambda x: -(x["ratio20"] or 0))

    # 法人持續調節
    dump = []
    for c in today("w_dump"):
        x = common(c)
        if (x["net20"] or 0) > -1:
            continue
        why = ["20 日法人賣超 %.1f 億,佔成交金額 %.1f%%(全市場最後 %d%%)"
               % (x["net20"], x["ratio20"], max(1, int(x["pct"])))]
        if x["buy_days20"] is not None and x["buy_days20"] <= 7:
            why.append("20 個交易日中有 %d 天法人賣超" % (20 - x["buy_days20"]))
        if x["fo_sell"] >= 3:
            why.append("外資連賣 %d 天(20 日累計 %+.1f 億)" % (x["fo_sell"], x["fo20"]))
        if x["tr_sell"] >= 3:
            why.append("投信連賣 %d 天(20 日累計 %+.1f 億)" % (x["tr_sell"], x["tr20"]))
        if (x["ret20"] or 0) > 5:
            why.append("股價 20 日仍漲 %+.1f%%,但法人在賣,籌碼與股價背離" % x["ret20"])
        val_reason(x, why)
        x["why"] = why
        dump.append(x)
    dump.sort(key=lambda x: x["ratio20"] or 0)

    # 大幅偏離季線
    stretch = []
    for c in today("w_stretch"):
        x = common(c)
        why = ["股價高於 60 日均線 %.0f%%,20 日漲跌 %+.1f%%" % (x["ma60"], x["ret20"] or 0)]
        if (x["net5"] or 0) < 0:
            why.append("近 5 日法人賣超 %.1f 億,有獲利了結跡象" % x["net5"])
        elif (x["net5"] or 0) > 0:
            why.append("近 5 日法人仍買超 %+.1f 億" % x["net5"])
        val_reason(x, why)
        x["why"] = why
        stretch.append(x)
    stretch.sort(key=lambda x: -(x["ma60"] or 0))

    return {
        "date": last, "generated_at": L["meta"]["generated_at"], "regime_now": L["meta"]["regime_now"],
        "rev_month": rev_m, "val_date": fund.get("date"),
        "themes": tlist, "picks": picks[:60], "dump": dump[:40], "stretch": stretch[:40],
        "counts": {"picks": len(picks), "dump": len(dump), "stretch": len(stretch)},
    }


import radar  # noqa: E402  (radar 會反向 import 本模組的常數與 nw_t)


def load_themes():
    try:
        with open(THEMES, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def history_themes():
    out = {}
    for th in load_themes():
        for c in th["codes"]:
            out.setdefault(c, []).append({"id": th["id"], "name": th["name"]})
    return out


if __name__ == "__main__":
    main()
