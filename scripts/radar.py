"""起漲雷達:營收動能(爆發前)與爆量突破(剛爆發),附回測、即時判斷門檻與名單實績追蹤。

由 signals.py 呼叫 build(L),L 是 signals.main() 的區域變數。輸出:
  data/radar/latest.json   今日名單 + 回測統計
  data/radar/live.json     上市股的突破門檻,讓網頁在排程更新前就能用證交所當日資料即時判斷
  data/track/lists/D.json  每天的名單快照(只增不改,用來事後驗證)
  data/track/summary.json  名單實績:每天的名單之後實際表現

回測規則與 signals.py 相同:收盤後才知道、隔天開盤進場、扣交易成本;
月營收視為次月 11 日起才知道(法定公告期限是 10 日)。
"""
import csv
from datetime import datetime
import json
import os

import numpy as np
import pandas as pd

import history
import revenue
import signals as S

OUT = os.path.join(history.ROOT, "data", "radar")
TRACK = os.path.join(history.ROOT, "data", "track")
MIN_VALUE = 0.3          # 億,當天成交金額門檻(比觀察名單寬,才看得到小型股)
SURGE = 5                # 成交金額 ≥ 前 20 日均量幾倍
REV_YOY = 30             # 營收年增門檻(%)
MOM60 = 20               # 「動能」:近 60 日漲幅 ≥ 20%(scripts/explosion_study.py 的組合規則)
PEER60 = 15              # 「題材」:同產業(證交所產業別)可交易股票近 60 日平均漲幅 ≥ 15%
DECEL = -20              # 「營收減速」:近 3 月平均年增比 3 個月前少 20 個百分點以上
REV_YOY2 = 20            # 或連續 2 個月年增都 ≥ 這個數(接住像騰輝 1 月年增 29% 這種差一點的)

RULES = {
    "rev_high": {"name": "營收創 12 個月新高且高成長",
                 "desc": "月營收公告後的第一個交易日(視為次月 11 日),當月營收高於前 12 個月,且年增 ≥ 30% 或連續 2 個月年增 ≥ 20%"},
    "breakout": {"name": "爆量突破、創 52 週新高",
                 "desc": "成交金額 ≥ 前 20 日均量 5 倍、漲 ≥ 5%,收盤突破前 60 日整理區間(區間 ≤ 35%)且創 250 日新高(20 日內只計一次)"},
    "breakout_rev": {"name": "爆量突破 + 營收成長",
                     "desc": "符合爆量突破,且近 3 個月營收平均年增 ≥ 20%"},
    "breakout_norev": {"name": "爆量突破但營收衰退(對照組)",
                       "desc": "符合爆量突破,但近 3 個月營收平均年減"},
}


def _f(x, nd=2):
    return None if x is None or pd.isna(x) else round(float(x), nd)


def revenue_panels(codes):
    R = revenue.load_all()
    months = sorted(R)
    if not months:
        return None
    rev = pd.DataFrame({m: {c: v[0] for c, v in R[m].items()} for m in months}).T.reindex(columns=codes).astype(float)
    yoy = pd.DataFrame({m: {c: v[1] for c, v in R[m].items()} for m in months}).T.reindex(columns=codes).astype(float)
    mom = pd.DataFrame({m: {c: v[2] for c, v in R[m].items()} for m in months}).T.reindex(columns=codes).astype(float)
    rmax12 = rev.shift(1).rolling(12, min_periods=10).max()
    rec = (rev >= rmax12) & rev.notna()
    yoy3 = yoy.rolling(3, min_periods=3).mean()
    good = rec & ((yoy >= REV_YOY) | ((yoy >= REV_YOY2) & (yoy.shift(1) >= REV_YOY2)))
    # 連續創新高月數
    streak = rec.astype(int).copy()
    for i in range(1, len(streak)):
        streak.iloc[i] = (streak.iloc[i - 1] + 1) * rec.iloc[i].astype(int)
    return {"months": months, "rev": rev, "yoy": yoy, "mom": mom, "rec": rec, "yoy3": yoy3, "streak": streak, "good": good}


def to_daily(panel, months, index):
    """月資料 → 交易日:(y, m) 的營收視為 (y, m+1) 月 11 日起可用。"""
    avail = [pd.Timestamp(y + (m == 12), m % 12 + 1, 11) for y, m in months]
    df = panel.copy()
    df.index = avail
    return df.reindex(pd.to_datetime(index), method="ffill").set_axis(index)


def first(m, gap=20):
    m = m.fillna(False).astype(bool)
    p = m.shift(1).fillna(False).astype(bool)
    for k in range(2, gap + 1):
        p = p | m.shift(k).fillna(False).astype(bool)
    return m & ~p


def evaluate(mask, fwd, rel, fmax, pos, oos_i, h):
    m = mask.values
    if m.sum() == 0:
        return {"n": 0}
    r, x, mx, p = fwd.values[m], rel.values[m], fmax.values[m], pos[m]
    ok = ~np.isnan(r) & ~np.isnan(x)
    r, x, mx, p = r[ok], x[ok], mx[ok], p[ok]
    if len(r) == 0:
        return {"n": 0}
    daily = pd.Series(x).groupby(p).mean().sort_index()
    o = p >= oos_i
    return {
        "n": int(len(r)), "days": int(len(daily)),
        "avg": _f(r.mean() * 100), "med": _f(np.median(r) * 100),
        "avg_rel": _f(x.mean() * 100), "win": _f((x > 0).mean() * 100, 1),
        "t": _f(S.nw_t(daily.values, h)),
        "double": _f(np.nanmean(mx >= 1.0) * 100, 1), "up50": _f(np.nanmean(mx >= 0.5) * 100, 1),
        "loss15": _f((r < -0.15).mean() * 100, 1),
        "top10_share": _f(top_share(x), 1),
        "oos_n": int(o.sum()), "oos_avg_rel": _f(x[o].mean() * 100) if o.sum() else None,
    }


def top_share(x):
    """報酬最高的 10% 樣本,貢獻了多少總超額報酬(衡量是否靠少數大漲股撐起來)。"""
    pos = np.sort(x)[::-1]
    total = pos.sum()
    if total <= 0:
        return None
    k = max(1, len(pos) // 10)
    return pos[:k].sum() / total * 100


def grade(st):
    if st.get("n", 0) < 30:
        return "樣本不足"
    t, oos = st["t"], st.get("oos_avg_rel")
    up, dn = oos is not None and oos > 0, oos is not None and oos < 0
    if t >= S.T_STRONG and up and st["avg_rel"] >= 0.3:
        return "強"
    if t >= S.T_MID and up:
        return "中"
    if t <= -S.T_MID and dn:
        return "反向"
    return "弱"


def build(L):
    close, opn, F, names, dates = L["close"], L["opn"], L["F"], L["names"], L["dates"]
    vyi, net = L["vyi"], L["net"]
    last = dates[-1]
    codes = close.columns
    rp = revenue_panels(codes)
    if rp is None:
        print("radar: 沒有月營收資料,略過")
        return None

    chg = F["chg"]
    avg20p = vyi.shift(1).rolling(20, min_periods=15).mean()
    mx60 = close.shift(1).rolling(60, min_periods=50).max()
    mn60 = close.shift(1).rolling(60, min_periods=50).min()
    mx250 = close.shift(1).rolling(250, min_periods=200).max()
    vol60 = chg.rolling(60, min_periods=40).std()
    ret20 = close / close.shift(20) - 1
    ret60 = close / close.shift(60) - 1

    D = {k: to_daily(rp[k], rp["months"], close.index) for k in ("yoy", "yoy3", "rec", "good")}
    newpub = pd.Series(False, index=close.index)
    for y, m in rp["months"]:
        i = pd.to_datetime(close.index).searchsorted(pd.Timestamp(y + (m == 12), m % 12 + 1, 11))
        if 0 < i < len(close.index):
            newpub.iloc[i] = True
    tradable = vyi >= MIN_VALUE

    surge = (vyi >= SURGE * avg20p) & (chg >= 5) & tradable
    bo = surge & (close >= mx60) & (mx60 / mn60 - 1 <= 0.35) & (close >= mx250)
    sig = {
        "rev_high": pd.DataFrame(np.outer(newpub.values, np.ones(len(codes), bool)), index=close.index, columns=codes)
        & (D["good"] == 1) & tradable,
        "breakout": first(bo),
    }
    sig["breakout_rev"] = sig["breakout"] & (D["yoy3"] >= 20)
    sig["breakout_norev"] = sig["breakout"] & (D["yoy3"] < 0)

    # 回測
    entry = opn.shift(-1)
    fmax = close[::-1].rolling(120, min_periods=1).max()[::-1].shift(-1) / entry - 1
    pos = np.repeat(np.arange(len(dates))[:, None], len(codes), axis=1)
    rev_start = pd.Timestamp(rp["months"][0][0], rp["months"][0][1], 1) + pd.DateOffset(months=13)
    usable = pd.Series(pd.to_datetime(close.index) >= rev_start, index=close.index)
    oos_i = len(dates) - S.OOS_DAYS
    stats, base = {}, {}
    for h in (20, 60):
        fwd = close.shift(-h) / entry - 1 - S.COST
        univ = tradable & fwd.notna()
        xs = fwd.where(univ).mean(axis=1)
        rel = fwd.sub(xs, axis=0)
        base[str(h)] = evaluate(univ & usable.values[:, None], fwd, rel, fmax, pos, oos_i, h)
        for sid in RULES:
            st = evaluate(sig[sid] & univ & usable.values[:, None], fwd, rel, fmax, pos, oos_i, h)
            st["grade"] = grade(st)
            stats.setdefault(sid, dict(RULES[sid], horizons={}))["horizons"][str(h)] = st

    # 今日名單
    themes = L["themes"]
    latest_m = rp["months"][-1]
    hi250_now = L["prior_max"]

    def stock_row(c):
        cl = close.at[last, c]
        v60 = vol60.at[last, c]
        return {
            "code": c, "name": names.get(c, c), "close": _f(cl), "chg": _f(chg.at[last, c]),
            "ret20": _f(ret20.at[last, c] * 100, 1), "value": _f(vyi.at[last, c]),
            "hi250": None if pd.isna(hi250_now.at[last, c]) else _f((cl / hi250_now.at[last, c] - 1) * 100, 1),
            "net20": _f(net[c].iloc[-20:].sum(), 1),
            "vol60": _f(v60), "themes": themes.get(c, []),
            "above_ma60": None if pd.isna(ma60.at[last, c]) else bool(cl > ma60.at[last, c]),
            "dumped": bool(rk_last.get(c, 1) <= 0.1),
        }

    ma60 = L["ma60"]
    rk_last = L["rk_n"].loc[last].fillna(1).to_dict()
    peer, ind = peer_momentum(ret60.loc[last], tradable.loc[last])
    accel = rp["yoy3"] - rp["yoy3"].shift(3)
    vol_cut = float(vol60.loc[last][tradable.loc[last]].quantile(0.3))
    rev_list = []
    for c in codes:
        # 用每檔「已公布的最新一個月」
        col = rp["rev"][c]
        if col.isna().all():
            continue
        mi = col.last_valid_index()
        if len(rp["months"]) > 1 and mi < rp["months"][-2]:
            continue   # 最新兩個月都沒公布,資料太舊
        if not rp["good"].at[mi, c]:
            continue
        if pd.isna(close.at[last, c]) or not (vyi[c].iloc[-20:].mean() >= MIN_VALUE / 3):
            continue
        x = stock_row(c)
        x.update({
            "rev_month": "%d-%02d" % mi, "rev_new": mi == latest_m,
            "yoy": _f(rp["yoy"].at[mi, c], 1), "yoy3": _f(rp["yoy3"].at[mi, c], 1), "mom": _f(rp["mom"].at[mi, c], 1),
            "rev_streak": int(rp["streak"].at[mi, c]),
            "low_vol": bool(not pd.isna(x["vol60"]) and x["vol60"] < vol_cut),
            "rev_hist": [_f(v / 1e5, 1) for v in col.loc[:mi].iloc[-13:].values],
        })
        r60 = ret60.at[last, c]
        x.update({
            "ret60": _f(r60 * 100, 1), "ind": IND_NAME.get(ind.get(c), ind.get(c)), "peer60": _f(peer.get(c), 1),
            "accel": _f(accel.at[mi, c], 1),
        })
        x["mom_ok"] = bool(not pd.isna(r60) and r60 * 100 >= MOM60)
        x["peer_ok"] = bool(x["peer60"] is not None and x["peer60"] >= PEER60)
        x["tri"] = x["mom_ok"] and x["peer_ok"]
        x["tier"] = "A" if x["tri"] else "B" if (x["mom_ok"] or x["peer_ok"]) else "C"
        x["decel"] = bool(x["accel"] is not None and x["accel"] <= DECEL)
        x["why"] = rev_reasons(x)
        rev_list.append(x)
    rev_list.sort(key=lambda x: (not x["rev_new"], -(x["yoy3"] or 0)))

    # D 層:營收還沒確認、但股價動能 + 同產業一起漲(題材股行情)。歷史上優勢不穩定,只供觀察
    in_rev = {x["code"] for x in rev_list}
    theme_list = []
    r60_last = ret60.loc[last]
    for c in codes:
        if c in in_rev or not tradable.at[last, c] or pd.isna(r60_last[c]):
            continue
        if r60_last[c] * 100 < MOM60 or (peer.get(c) is None) or peer[c] < PEER60:
            continue
        x = stock_row(c)
        mi = rp["rev"][c].last_valid_index()
        x.update({"ret60": _f(r60_last[c] * 100, 1), "ind": IND_NAME.get(ind.get(c), ind.get(c)), "peer60": _f(peer.get(c), 1),
                  "yoy": None if mi is None else _f(rp["yoy"].at[mi, c], 1), "yoy3": None if mi is None else _f(rp["yoy3"].at[mi, c], 1),
                  "tier": "D", "low_vol": bool(not pd.isna(x["vol60"]) and x["vol60"] < vol_cut)})
        theme_list.append(x)
    theme_list.sort(key=lambda x: (-(x["peer60"] or 0), -(x["ret60"] or 0)))

    # 星等評級
    fo20 = ((F["fo"] * F["close_raw"]).iloc[-20:].sum() / F["value"].iloc[-20:].sum() * 100) if "close_raw" in F else pd.Series(dtype=float)
    RATING.clear()
    for x in rev_list:
        traps = []
        if x.get("decel"):
            traps.append("營收減速")
        if not pd.isna(fo20.get(x["code"], np.nan)) and fo20[x["code"]] <= FO_DUMP:
            traps.append("外資 20 日大賣")
        x["traps"], x["stars"] = traps, STARS_BASE[x["tier"]] - (1 if traps else 0)
        RATING[x["code"]] = {"stars": x["stars"], "tier": x["tier"], "traps": traps}
    for x in theme_list:
        x["traps"], x["stars"] = [], STARS_BASE["D"]
        RATING[x["code"]] = {"stars": x["stars"], "tier": "D", "traps": []}
    SNAP.clear()
    r60_all = ret60.loc[last]
    for c in codes:
        col = rp["rev"][c]
        mi = col.last_valid_index()
        SNAP[c] = {"ret60": _f(r60_all[c] * 100, 1), "ind": IND_NAME.get(ind.get(c), ind.get(c)),
                   "yoy": None if mi is None else _f(rp["yoy"].at[mi, c], 1),
                   "yoy3": None if mi is None else _f(rp["yoy3"].at[mi, c], 1),
                   "rev_month": None if mi is None else "%d-%02d" % mi,
                   # 個股健檢用
                   "rev_ok": bool(mi is not None and rp["good"].at[mi, c] and len(rp["months"]) > 1 and mi >= rp["months"][-2]),
                   "accel": None if mi is None else _f(accel.at[mi, c], 1),
                   "streak": None if mi is None else int(rp["streak"].at[mi, c]),
                   "peer60": _f(peer.get(c), 1),
                   "fo20": _f(fo20.get(c, np.nan), 1),
                   "value20": _f(vyi[c].iloc[-20:].mean(), 2),
                   "vol60": _f(vol60.at[last, c], 2), "low_vol": bool(not pd.isna(vol60.at[last, c]) and vol60.at[last, c] < vol_cut),
                   "hi250": None if pd.isna(hi250_now.at[last, c]) else _f((close.at[last, c] / hi250_now.at[last, c] - 1) * 100, 1),
                   "above_ma60": None if pd.isna(ma60.at[last, c]) else bool(close.at[last, c] > ma60.at[last, c])}

    # 近 10 個交易日的爆量突破
    recent = dates[-10:]
    bo_list = []
    for d in recent:
        row = sig["breakout"].loc[d]
        for c in row[row.fillna(False).astype(bool)].index:
            x = stock_row(c)
            k = dates.index(d)
            x.update({
                "date": d, "days_ago": len(dates) - 1 - k,
                "since": _f((close.at[last, c] / close.at[d, c] - 1) * 100, 1),
                "surge": _f(vyi.at[d, c] / avg20p.at[d, c], 1) if avg20p.at[d, c] else None,
                "day_chg": _f(chg.at[d, c]), "yoy3": _f(D["yoy3"].at[d, c], 1), "yoy": _f(D["yoy"].at[d, c], 1),
                "rev_ok": bool((D["yoy3"].at[d, c] or -1) >= 20),
                "low_vol": bool(not pd.isna(x["vol60"]) and x["vol60"] < vol_cut),
            })
            x["why"] = bo_reasons(x)
            bo_list.append(x)
    bo_list.sort(key=lambda x: (x["days_ago"], not x["rev_ok"], -(x["surge"] or 0)))

    meta = {"date": last, "generated_at": L["meta"]["generated_at"], "rev_latest": "%d-%02d" % latest_m,
            "vol_cut": _f(vol_cut), "min_value": MIN_VALUE, "cost_pct": S.COST * 100,
            "span": [str(rev_start.date()), last], "oos_start": dates[oos_i]}
    os.makedirs(OUT, exist_ok=True)
    state = (D["good"] == 1) & tradable & usable.values[:, None]
    pubs = [i for i in np.where(newpub.values)[0] if usable.iat[i]]
    port = portfolio(state, pubs, close, opn, tradable)
    basket_log(state, pubs, close, opn, tradable, dates)
    cyc = cycle(L, rp, close, dates, usable)
    fv = fair_all(rp, close, last)
    mg = margin_now()
    for x in rev_list + bo_list:
        x["fv"] = fv.get(x["code"])
        m = mg.get(x["code"])
        x["gm"] = {"p": m["p"], "gm": m["gm"], "d": m["d"]} if m else None
    for c, m in mg.items():
        if c in EXTRAS:
            EXTRAS[c]["gm"] = m["hist"]
        if c in SNAP:
            SNAP[c]["gm"], SNAP[c]["dgm"], SNAP[c]["gm_p"] = m["gm"], m["d"], m["p"]
    for c, e in fv.items():   # 估值只供參考(前瞻估值尚未回測、歷史估值回測沒有預測力)
        if c in SNAP:
            w, tg = e.get("fwd") or {}, e.get("tgt") or {}
            SNAP[c].update(fpe=w.get("pe"), fpe_med=(w.get("band") or [None, None])[1], fwd_status=w.get("status"), tgt_up=tg.get("up"))
    mom = momentum(L, rp, close, opn, tradable, usable, newpub, rev_list)
    rank = ranking(rev_list, bo_list, mom)
    try:   # 毛利率回測結果(scripts/margin_test.py 產生,研究用、不在排程跑)
        with open(os.path.join(OUT, "margin_test.json"), encoding="utf-8") as f:
            meta["margin_bt"] = json.load(f)
    except (OSError, ValueError):
        pass
    try:   # 飆股特徵研究(scripts/explosion_study.py,研究用):只帶網頁要顯示的部分
        with open(os.path.join(OUT, "explosion.json"), encoding="utf-8") as f:
            ex = json.load(f)
        meta["explosion"] = {k: ex[k] for k in ("span", "base", "traps", "recall", "cases") if k in ex}
        meta["explosion"]["rules"] = {k: v for k, v in ex.get("rules", {}).items()
                                      if k in ("只看營收(目前的起漲雷達)", "營收 + 起漲初期", "營收 + 動能", "營收 + 同產業股價強", "營收 + 動能 + 同產業股價強")}
        meta["explosion"]["streak"] = ex.get("streak")
        meta["explosion"]["tiers"] = ex.get("tiers")
        meta["explosion"]["stars"] = ex.get("stars")
    except (OSError, ValueError):
        pass
    doc = dict(meta, stats=stats, base=base, rev=rev_list, theme=theme_list, breakout=bo_list, portfolio=port, cycle=cyc, rank=rank,
               momentum={k: v for k, v in mom.items() if k != "today"})
    with open(os.path.join(OUT, "latest.json"), "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))

    write_live(L, close, vyi, chg, D, last, names, vol60, vol_cut)
    track(L, rev_list, bo_list, close, opn, vyi, dates, mom)
    print("radar: rev %d, breakout %d" % (len(rev_list), len(bo_list)))
    return doc


def portfolio(state, pubs, close, opn, tradable, h=60, draws=100):
    """照名單操作的組合模擬:每月營收公告日從名單隨機買 k 檔等權,持有 h 日。比較分散與停損的效果。"""
    rng = np.random.default_rng(20261007)
    C, E, T, M = close.values, opn.shift(-1).values, tradable.values, state.values

    def run(k, stop=False, pool=None):
        res = []
        for i in pubs:
            if i + h >= len(C):
                continue
            js = np.where((pool[i] if pool is not None else M[i]) & ~np.isnan(E[i]) & ~np.isnan(C[i + h]))[0]
            if len(js) < k:
                continue
            for _ in range(draws if k < len(js) else 1):
                pick = rng.choice(js, k, replace=False)
                r = C[i + h, pick] / E[i, pick] - 1 - S.COST
                if stop:
                    for q, j in enumerate(pick):
                        path = C[i + 1:i + h + 1, j] / E[i, j] - 1
                        hit = np.where(path <= -0.15)[0]
                        if len(hit):
                            r[q] = path[hit[0]] - S.COST
                res.append(r.mean())
        a = np.array(res)
        return {"k": k, "stop": stop, "random": pool is not None, "n": int(len(a)),
                "avg": _f(a.mean() * 100, 1), "med": _f(np.median(a) * 100, 1),
                "loss15": _f((a < -0.15).mean() * 100, 1), "loss10": _f((a < -0.10).mean() * 100, 1),
                "p5": _f(np.percentile(a, 5) * 100, 1), "win": _f((a > 0).mean() * 100, 1)}
    rows = [run(k) for k in (1, 5, 10, 20)]
    rows.append(run(10, stop=True))
    rows.append(run(10, pool=T))
    return {"hold": h, "rows": rows}


def basket_log(state, pubs, close, opn, tradable, dates, h=20):
    """每月一籃(名單全部等權、持有 20 日)扣掉一般股的報酬,寫成 anti-gambling-trader 可讀的交易紀錄。
    每籃之間不重疊,符合它「交易彼此獨立」的前提;扣掉一般股是因為只看絕對損益時,多頭裡亂選也會被判有優勢。"""
    C, E, T, M = close.values, opn.shift(-1).values, tradable.values, state.values
    rows = []
    for i in pubs:
        if i + h >= len(C) or not M[i].any():
            continue
        f = C[i + h] / E[i] - 1 - S.COST
        pick, univ = M[i] & ~np.isnan(f), T[i] & ~np.isnan(f)
        if pick.any():
            rows.append(["籃%s" % dates[i][:7], dates[i + 1], dates[i + h],
                         int(round(1e6 * (f[pick].mean() - f[univ].mean()))), "TWD"])
    os.makedirs(TRACK, exist_ok=True)
    with open(os.path.join(TRACK, "basket_backtest.csv"), "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["代號", "進場時間", "出場時間", "已實現淨損益", "損益幣別"])
        w.writerows(rows)


def cycle(L, rp, close, dates, usable):
    """產業景氣循環:板塊營收(同口徑)年增轉強 + 成分股齊漲。抓記憶體、被動元件這類整個產業的漲價行情。"""
    ret = close.pct_change()
    mx250 = close.rolling(250, min_periods=200).max()
    themes = [t for t in L["theme_list"] if len([c for c in t["codes"] if c in close.columns]) >= 3]
    IDX, BR, RV, RACC, RB, info = {}, {}, {}, {}, {}, {}
    for t in themes:
        mem = [c for c in t["codes"] if c in close.columns]
        IDX[t["id"]] = (1 + ret[mem].mean(axis=1).fillna(0)).cumprod()
        BR[t["id"]] = (close[mem] >= 0.95 * mx250[mem]).sum(axis=1) / close[mem].notna().sum(axis=1)
        cur, prv = rp["rev"][mem], rp["rev"][mem].shift(12)
        both = cur.notna() & prv.notna()          # 只用兩年都有資料的公司,算同口徑年增
        yoy = (cur.where(both).sum(axis=1) / prv.where(both).sum(axis=1) - 1) * 100
        yoy[both.sum(axis=1) < max(2, len(mem) // 2)] = np.nan
        y3 = yoy.rolling(3).mean()
        brv = (rp["yoy"][mem] >= 20).sum(axis=1) / rp["yoy"][mem].notna().sum(axis=1)
        RV[t["id"]] = to_daily(y3.to_frame("x"), rp["months"], close.index)["x"]
        RACC[t["id"]] = to_daily((y3 - y3.shift(3)).to_frame("x"), rp["months"], close.index)["x"]
        RB[t["id"]] = to_daily(brv.to_frame("x"), rp["months"], close.index)["x"]
        info[t["id"]] = {"name": t["name"], "n": len(mem), "y3m": [_f(v, 0) for v in y3.iloc[-13:].values]}
    IDX, BR, RV, RACC, RB = map(pd.DataFrame, (IDX, BR, RV, RACC, RB))
    rev_up = (RV >= 15) & (RACC >= 10) & (RB >= 0.5)
    rally = (BR >= 0.5) & (IDX >= IDX.rolling(250, min_periods=200).max())
    both = rev_up.rolling(60, min_periods=1).max().astype(bool) & rally
    sigs = {"rev_up": first(rev_up, 60), "rally": first(rally, 60), "both": first(both, 60)}
    labels = {"rev_up": "產業營收轉強", "rally": "產業齊漲", "both": "營收轉強 + 齊漲"}
    stats = {}
    for k, m in sigs.items():
        stats[k] = {"name": labels[k]}
        for h in (60, 120):
            fwd = IDX.shift(-h) / IDX.shift(-1) - 1
            rel = fwd.sub(fwd.mean(axis=1), axis=0)
            mm = m & usable.values[:, None]
            v, a = rel[mm].stack().dropna().values, fwd[mm].stack().dropna().values
            stats[k][str(h)] = {"n": int(len(v)), "avg_rel": _f(v.mean() * 100, 1) if len(v) else None,
                                "med_rel": _f(np.median(v) * 100, 1) if len(v) else None,
                                "win": _f((v > 0).mean() * 100, 0) if len(v) else None,
                                "avg": _f(a.mean() * 100, 1) if len(a) else None}
    # 歷史大行情個案:板塊等權指數 120 日內從低點漲 ≥ 50%,訊號在哪裡出現
    cases, start = [], int(np.argmax(usable.values))
    for tid in IDX.columns:
        s_ = IDX[tid].values
        i = start
        while i < len(s_) - 1:
            w = s_[i:i + 121]
            j = int(np.argmax(w))
            if w[j] >= 1.5 * s_[i] and s_[i] == s_[max(0, i - 20):i + 1].min():
                pk = i + j
                tr = i + int(np.argmin(s_[i:pk + 1]))
                row = {"id": tid, "name": info[tid]["name"], "trough": dates[tr], "peak": dates[pk],
                       "gain": _f((s_[pk] / s_[tr] - 1) * 100, 0)}
                for k in ("rev_up", "both"):
                    col = sigs[k][tid].values
                    ks = [q for q in range(max(0, tr - 40), pk + 1) if col[q]]
                    row[k] = None if not ks else {"date": dates[ks[0]], "at": _f((s_[ks[0]] / s_[tr] - 1) * 100, 0),
                                                  "left": _f((s_[pk] / s_[ks[0]] - 1) * 100, 0)}
                cases.append(row)
                i = pk + 1
            else:
                i += 1
    cases.sort(key=lambda x: -x["gain"])
    last = dates[-1]
    now = []
    for tid in IDX.columns:
        r_up, r_ral = bool(rev_up[tid].iloc[-60:].any()), bool(rally[tid].iloc[-20:].any())
        state = ("景氣上行確認" if r_up and r_ral else "營收轉強、股價未齊漲" if r_up
                 else "股價齊漲、營收未跟上" if r_ral else "—")
        now.append(dict(info[tid], id=tid, state=state, rev_y3=_f(RV.at[last, tid], 0), rev_acc=_f(RACC.at[last, tid], 0),
                        rev_breadth=_f(RB.at[last, tid] * 100, 0), price_breadth=_f(BR.at[last, tid] * 100, 0),
                        ret60=_f((IDX.at[last, tid] / IDX[tid].iloc[-61] - 1) * 100, 1)))
    order = {"景氣上行確認": 0, "營收轉強、股價未齊漲": 1, "股價齊漲、營收未跟上": 2, "—": 3}
    now.sort(key=lambda x: (order[x["state"]], -(x["rev_y3"] if x["rev_y3"] is not None else -999)))
    return {"stats": stats, "cases": cases, "now": now}


# 證交所產業別代碼(上市與上櫃共用)
IND_NAME = {"01": "水泥", "02": "食品", "03": "塑膠", "04": "紡織", "05": "電機機械", "06": "電器電纜", "08": "玻璃陶瓷",
            "09": "造紙", "10": "鋼鐵", "11": "橡膠", "12": "汽車", "14": "建材營造", "15": "航運", "16": "觀光餐旅",
            "17": "金融保險", "18": "貿易百貨", "19": "綜合", "20": "其他", "21": "化學", "22": "生技醫療", "23": "油電燃氣",
            "24": "半導體", "25": "電腦及週邊", "26": "光電", "27": "通信網路", "28": "電子零組件", "29": "電子通路",
            "30": "資訊服務", "31": "其他電子", "32": "文化創意", "33": "農業科技", "35": "綠能環保", "36": "數位雲端",
            "37": "運動休閒", "38": "居家生活", "80": "管理股票"}


MIXED_IND = {"19", "20", "80"}   # 綜合、其他、管理股票:不是同一種生意,不算「同產業」


def peer_momentum(r60_last, trad_last):
    """同產業可交易股票近 60 日平均漲幅(%);產業內少於 5 檔不算。"""
    try:
        with open(os.path.join(history.ROOT, "data", "profile", "industry.json"), encoding="utf-8") as f:
            ind = json.load(f)
    except (OSError, ValueError):
        return {}, {}
    df = pd.DataFrame({"r": r60_last, "t": trad_last})
    df["g"] = [None if ind.get(c) in MIXED_IND else ind.get(c) for c in df.index]
    ok = df[df.t.fillna(False).astype(bool) & df.r.notna() & df.g.notna()]
    agg = ok.groupby("g").r.agg(["mean", "size"])
    agg = agg[agg["size"] >= 5]["mean"] * 100
    return {c: agg.get(g) for c, g in df.g.items() if g in agg.index}, ind


def rev_reasons(x):
    out = ["%s 月營收年增 %+.0f%%,創近 12 個月新高" % (x["rev_month"][5:].lstrip("0"), x["yoy"])]
    if x["yoy"] < REV_YOY:
        out.append("年增未達 30%,但已連續 2 個月年增 ≥ 20%")
    if x.get("above_ma60") is False:
        out.append("股價仍在季線下")
    if x.get("dumped"):
        out.append("但近 20 日法人賣超居全市場後 10%")
    if x["rev_streak"] >= 2:
        out.append("已連續 %d 個月創新高" % x["rev_streak"])
    if x["yoy3"] is not None:
        out.append("近 3 個月平均年增 %+.0f%%" % x["yoy3"])
    if x["hi250"] is not None:
        if x["hi250"] >= -3:
            out.append("股價已在 52 週高點附近")
        elif x["hi250"] <= -20:
            out.append("股價距 52 週高點還有 %.0f%%,尚未反映" % -x["hi250"])
    if x["ret20"] is not None and x["ret20"] >= 30:
        out.append("股價 20 日已漲 %+.0f%%" % x["ret20"])
    if x.get("tri"):
        out.append("營收、動能(60 日漲 %+.0f%%)、題材(%s類股 60 日平均 %+.0f%%)三項都有" % (x["ret60"], x["ind"] or "同產業", x["peer60"]))
    elif x.get("peer60") is not None and x["peer60"] >= PEER60:
        out.append("%s類股 60 日平均漲 %+.0f%%,但這檔股價動能還不足" % (x["ind"] or "同產業", x["peer60"]))
    if x.get("decel"):
        out.append("營收年增在減速(近 3 月比 3 個月前少 %.0f 個百分點),歷史上之後表現較差" % -x["accel"])
    return out


def bo_reasons(x):
    out = ["%s 爆量 %.0f 倍、漲 %+.1f%%,突破整理並創 52 週新高" % (x["date"][5:].replace("-", "/"), x["surge"] or 0, x["day_chg"] or 0)]
    if x["yoy3"] is not None:
        out.append("近 3 個月營收平均年增 %+.0f%%%s" % (x["yoy3"], "" if x["rev_ok"] else "(未達 20%,歷史上效果較差)"))
    else:
        out.append("無月營收資料")
    if x["days_ago"] > 0 and x["since"] is not None:
        out.append("突破後至今 %+.1f%%" % x["since"])
    return out


RATING = {}   # 代號 → 星等評級(signals.py 寫進個股檔與查詢索引);不在任何名單的是 1★
SNAP = {}     # 代號 → 查詢索引用的最新營收、產業、60 日漲幅(全部股票)
STARS_BASE = {"A": 5, "B": 4, "C": 3, "D": 3}   # 陷阱(營收減速、外資 20 日大賣)A/B/C 各扣 1 顆;回測見 explosion_study.py
FO_DUMP = -10            # 外資 20 日買賣超佔成交金額 ≤ −10% 視為大賣
EXTRAS = {}   # 代號 → 個股面板用的估值、營收、本益比歷史(signals.py 寫個股檔時帶入)


def margin_now():
    """每檔最新一季毛利率、與去年同季相比的變化(百分點)、近 8 季歷史。只供顯示:回測顯示它對營收動能名單沒有預測力。"""
    import margin
    out = {}
    for c, cum in margin.load().items():
        q = margin.quarterly(cum)
        gm = {p: g / r * 100 for p, (r, g) in q.items() if r and r > 0 and abs(g / r) <= 1}
        if not gm:
            continue
        ps = sorted(gm)
        p = ps[-1]
        py = "%d%s" % (int(p[:4]) - 1, p[4:])
        out[c] = {"p": p, "gm": _f(gm[p], 1), "d": _f(gm[p] - gm[py], 1) if py in gm else None,
                  "hist": [[k, _f(gm[k], 1)] for k in ps[-8:]]}
    return out


def fair_all(rp, close, last):
    """每檔股票的模型合理價(公式見 fairvalue.py)。同時把個股面板要用的歷史資料放進 EXTRAS。"""
    import fairvalue as FV
    import valuation
    VAL = valuation.load_all()
    try:
        with open(os.path.join(history.ROOT, "data", "fundamentals", "latest.json"), encoding="utf-8") as f:
            now = json.load(f).get("val", {})
    except FileNotFoundError:
        now = {}
    try:
        cons = json.load(open(os.path.join(history.ROOT, "data", "estimates", "latest.json"), encoding="utf-8")).get("s", {})
    except FileNotFoundError:
        cons = {}
    cur_m = (int(last[:4]), int(last[5:7]))
    w1 = (cur_m[1] - 1) / 12   # 未來 12 個月 EPS = 今年預估 × 剩餘比例 + 明年預估 × 已過比例
    vm = [m for m in sorted(VAL) if m < cur_m][-FV.MAX_HIST:]
    pe_h = {m: VAL[m]["s"] for m in vm}
    rev, yoy = rp["rev"], rp["yoy"]
    out = {}
    EXTRAS.clear()
    for c in close.columns:
        price = close.at[last, c]
        if pd.isna(price):
            continue
        pe, pb = (now.get(c) or [None, None])[:2]
        col = rev[c].dropna()
        ttm = r3 = None
        if len(col) >= 12 and col.index[-1] >= rp["months"][-3]:
            ttm, r3 = col.iloc[-12:].sum(), col.iloc[-3:].sum()
        ph = [pe_h[m].get(c, [None])[0] for m in vm]
        bh = [(pe_h[m].get(c) or [None, None])[1] for m in vm]
        est = FV.estimate(float(price), pe, pb, ttm, r3, ph, bh)
        ex = {"rev": [["%d-%02d" % m, _f(rev.at[m, c] / 1e5, 2), _f(yoy.at[m, c], 1)] for m in rev.index[-24:] if not pd.isna(rev.at[m, c])],
              "pe_hist": [["%d-%02d" % m, v] for m, v in zip(vm, ph) if v]}
        if est:
            e = {"fair": _f(est["fair"]), "low": _f(est["low"]), "high": _f(est["high"]),
                 "up": _f((est["fair"] / price - 1) * 100, 1), "status": FV.status(float(price), est),
                 "method": est["method"], "band": [_f(b, 1) for b in est["band"]], "n": est["n"],
                 "pe": pe, "pb": pb}
            # 合理價偏離股價太多,通常是景氣轉折、一次性損益或評價重估,固定公式不適用
            e["extreme"] = bool(e["up"] is not None and (e["up"] > 100 or e["up"] < -60))
            # 前瞻估值:分析師共識的未來 12 個月 EPS × 自身歷史本益比中位數(只有 PE 法、且有預估時)
            k = cons.get(c) or {}
            pe_band = FV.band(ph)
            if est_ok(k) and pe_band:
                e0, e1 = k.get("eps0") or k["eps1"], k["eps1"]
                feps12 = e0 * (1 - w1) + e1 * w1
                # 預估本益比低於 2 倍(EPS 超過股價一半)幾乎一定是資料錯誤(例:廣穎 1 位分析師 EPS 149、股價 149),不採用
                if feps12 > 0 and price / feps12 >= 2:
                    lo_, mid_, hi_ = pe_band[:3]
                    e["fwd"] = {"eps": _f(feps12), "pe": _f(price / feps12, 1), "fair": _f(feps12 * mid_),
                                "low": _f(feps12 * lo_), "high": _f(feps12 * hi_), "up": _f((feps12 * mid_ / price - 1) * 100, 1),
                                "n": k.get("n1"), "eps0": k.get("eps0"), "eps1": k["eps1"], "band": [_f(b, 1) for b in pe_band[:3]]}
                    e["fwd"]["status"] = "低估" if price < feps12 * lo_ else "高估" if price > feps12 * hi_ else "合理"
            if k.get("tgt"):
                e["tgt"] = {"mean": k["tgt"], "lo": k.get("tgt_lo"), "hi": k.get("tgt_hi"),
                            "up": _f((k["tgt"] / price - 1) * 100, 1)}
            if est["method"] == "pe":
                e.update(eps=_f(est["eps"]), growth=_f(est["growth"]), feps=_f(est["feps"]))
            else:
                e.update(bvps=_f(est["bvps"]))
            out[c] = e
            ex["fv"] = e
        EXTRAS[c] = ex
    return out


MOM_FEATS = ("離季線幅度", "60 日漲幅", "連續創新高月數", "距 52 週高點")


def momentum(L, rp, close, opn, tradable, usable, newpub, rev_list, h=60):
    """營收動能名單內的綜合動能分數,以及「同分組歷史 60 日後實際落點」當作統計預期區間。

    分數 = 4 個特徵在當天名單內的百分位排名平均(離季線幅度、60 日漲幅、營收連續創新高月數、距 52 週高點)。
    這 4 個特徵在 2019–2023 與 2023–2026 兩段期間方向一致(動能延續),但組合是看過兩段資料後才定的,
    真正的檢驗是實績追蹤。"""
    ma60 = L["ma60"]
    feats = {
        "離季線幅度": (close / ma60 - 1).values,
        "60 日漲幅": (close / close.shift(60) - 1).values,
        "連續創新高月數": to_daily(rp["streak"].astype(float), rp["months"], close.index).values,
        "距 52 週高點": (close / close.rolling(250, min_periods=200).max() - 1).values,
    }
    good = (to_daily(rp["good"].astype(float), rp["months"], close.index) == 1).values & tradable.values
    C, E, T = close.values, opn.shift(-1).values, tradable.values
    N = len(close.index)

    def scores(i, js):
        X = np.column_stack([feats[k][i, js] for k in MOM_FEATS])
        ok = ~np.isnan(X).any(axis=1)
        sc = np.full(len(js), np.nan)
        if ok.sum() >= 5:
            sc[ok] = pd.DataFrame(X[ok]).rank(pct=True).mean(axis=1).values
        return sc

    hist = {q: [] for q in range(5)}
    for i in np.where(newpub.values & usable.values)[0]:
        if i + h >= N:
            continue
        js = np.where(good[i])[0]
        if len(js) < 10:
            continue
        sc = scores(i, js)
        f = C[i + h] / E[i] - 1 - S.COST
        bench = np.nanmean(f[T[i] & ~np.isnan(f)])
        qs = pd.Series(sc).rank(pct=True).values
        for j, s_, q_ in zip(js, sc, qs):
            if not np.isnan(s_) and not np.isnan(f[j]):
                hist[min(4, int(q_ * 5 - 1e-9))].append((f[j], f[j] - bench))
    qstat = []
    for q in range(5):
        a = np.array(hist[q])
        if len(a) == 0:
            qstat.append(None)
            continue
        qstat.append({"q": q, "n": int(len(a)), "rel": _f(a[:, 1].mean() * 100), "avg": _f(a[:, 0].mean() * 100),
                      "p25": _f(np.percentile(a[:, 0], 25) * 100), "p50": _f(np.median(a[:, 0]) * 100),
                      "p75": _f(np.percentile(a[:, 0], 75) * 100), "win": _f((a[:, 1] > 0).mean() * 100, 0)})
    # 今天的名單
    last_i = N - 1
    code_ix = {c: k for k, c in enumerate(close.columns)}
    js = np.array([code_ix[x["code"]] for x in rev_list], dtype=int)
    today = {}
    if len(js) >= 5:
        sc = scores(last_i, js)
        qs = pd.Series(sc).rank(pct=True).values
        for x, s_, q_ in zip(rev_list, sc, qs):
            if np.isnan(s_):
                continue
            q = min(4, int(q_ * 5 - 1e-9))
            st, px = qstat[q], x["close"]
            today[x["code"]] = {"score": _f(q_ * 100, 0), "q": q,
                                "proj": None if not st else {"p25": _f(px * (1 + st["p25"] / 100)), "p50": _f(px * (1 + st["p50"] / 100)),
                                                             "p75": _f(px * (1 + st["p75"] / 100)), "rel": st["rel"], "win": st["win"]}}
    return {"hold": h, "quintiles": qstat, "today": today, "feats": list(MOM_FEATS)}


def est_ok(k):
    return bool(k and k.get("eps1") and (k.get("n1") or 0) >= 1)


def ranking(rev_list, bo_list, mom):
    """潛在排行:起漲雷達名單(營收動能 + 近 5 日爆量突破),附綜合動能分數、統計預期區間與模型合理價。"""
    seen, out = {}, []
    for x in rev_list:
        seen[x["code"]] = dict(x, src=["營收動能"])
    for x in bo_list:
        if x["days_ago"] > 5:
            continue
        if x["code"] in seen:
            seen[x["code"]]["src"].append("爆量突破")
        else:
            seen[x["code"]] = dict(x, src=["爆量突破"])
    keys = ("code", "name", "close", "chg", "fv", "src", "yoy", "yoy3", "rev_streak", "above_ma60", "dumped",
            "low_vol", "themes", "ret20", "hi250")
    for x in seen.values():
        r = {k: x.get(k) for k in keys}
        r["mom"] = mom["today"].get(x["code"])   # 只有營收動能名單內的才有分數
        out.append(r)
    out.sort(key=lambda x: -(x["mom"]["score"] if x["mom"] else -1))
    return out


def write_live(L, close, vyi, chg, D, last, names, vol60, vol_cut):
    """給網頁即時判斷用:明天若出現「成交 ≥ 5 倍均量、漲 ≥ 5%、收盤 ≥ 這些價位」即為突破。"""
    out = {}
    tail = vyi.iloc[-20:]
    c60, c250 = close.iloc[-60:], close.iloc[-250:]
    for c in close.columns:
        if pd.isna(close.at[last, c]) or len(c250[c].dropna()) < 200:
            continue
        mx60, mn60, mx250 = c60[c].max(), c60[c].min(), c250[c].max()
        out[c] = [_f(tail[c].mean()), _f(mx60), _f(mn60), _f(mx250), _f(close.at[last, c]),
                  _f(D["yoy3"].at[last, c], 1), names.get(c, c)]
    with open(os.path.join(OUT, "live.json"), "w", encoding="utf-8") as f:
        json.dump({"date": last, "surge": SURGE, "min_value": MIN_VALUE,
                   "fields": ["avg20", "max60", "min60", "max250", "close", "yoy3", "name"], "s": out},
                  f, ensure_ascii=False, separators=(",", ":"))


def track(L, rev_list, bo_list, close, opn, vyi, dates, mom=None):
    """名單實績:每天存快照(不覆蓋舊的),再用之後的實際股價結算。"""
    last = dates[-1]
    d = os.path.join(TRACK, "lists")
    os.makedirs(d, exist_ok=True)
    w = L.get("watch") or {}
    snap = {
        "date": last,
        "rev": [x["code"] for x in rev_list if not x["low_vol"]],
        "breakout": [x["code"] for x in bo_list if x["days_ago"] == 0],
        "picks": [x["code"] for x in w.get("picks", [])],
        "dump": [x["code"] for x in w.get("dump", [])],
        "mom_top": [c for c, v in ((mom or {}).get("today") or {}).items() if v["q"] == 4],
        "star45": [x["code"] for x in rev_list if x.get("stars", 0) >= 4],   # 2026-10-09 起記錄
        "star5": [x["code"] for x in rev_list if x.get("stars", 0) >= 5],
    }
    p = os.path.join(d, last + ".json")
    if not os.path.exists(p):
        with open(p, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, separators=(",", ":"))
    else:
        # 已存在的快照不改既有名單;只補上後來新增的名單種類,而且只能在隔天開盤(進場)前補,過了就等於事後補記
        old = json.load(open(p, encoding="utf-8"))
        now = datetime.now(history.TZ)
        before_open = now.strftime("%Y-%m-%d") == last or now.hour < 9
        add = {k: v for k, v in snap.items() if k not in old} if before_open else {}
        if add:
            old.update(add)
            with open(p, "w", encoding="utf-8") as f:
                json.dump(old, f, ensure_ascii=False, separators=(",", ":"))

    names = {"rev": "營收動能", "star45": "評級 4★ 以上", "star5": "評級 5★", "mom_top": "營收動能 · 動能分數前 1/5", "breakout": "爆量突破", "picks": "法人資金流向", "dump": "法人持續調節"}
    idx = {x: i for i, x in enumerate(dates)}
    univ = vyi >= MIN_VALUE
    res = {k: {"name": v, "rows": []} for k, v in names.items()}
    for fn in sorted(os.listdir(d)):
        s = json.load(open(os.path.join(d, fn), encoding="utf-8"))
        i = idx.get(s["date"])
        if i is None or i + 1 >= len(dates):
            continue
        entry = opn.iloc[i + 1]
        for k in names:
            cs = [c for c in s.get(k, []) if c in close.columns]
            row = {"date": s["date"], "n": len(cs)}
            for h in (5, 20, 60):
                if i + h < len(dates) and cs:
                    fwd = close.iloc[i + h] / entry - 1 - S.COST
                    avg = fwd[univ.iloc[i]].mean()
                    row["r%d" % h] = _f(fwd[cs].mean() * 100)
                    row["x%d" % h] = _f((fwd[cs].mean() - avg) * 100)
            res[k]["rows"].append(row)
    for k, v in res.items():
        for h in (5, 20, 60):
            xs = [r["x%d" % h] for r in v["rows"] if r.get("x%d" % h) is not None]
            v["avg_x%d" % h] = _f(np.mean(xs)) if xs else None
            v["n%d" % h] = len(xs)
    # 實盤的每月一籃:從快照中每隔 20 個交易日取一天,把名單等權持有 20 日(扣掉一般股),給第三方稽核用
    os.makedirs(TRACK, exist_ok=True)
    for key, fname in (("rev", "basket_live.csv"), ("star45", "basket_live_star.csv")):
        live_rows, next_i = [], -1
        for fn in sorted(os.listdir(d)):
            s = json.load(open(os.path.join(d, fn), encoding="utf-8"))
            i = idx.get(s["date"])
            if i is None or i < next_i or i + 20 >= len(dates) or key not in s:
                continue
            f = close.iloc[i + 20] / opn.iloc[i + 1] - 1 - S.COST
            cs = [c for c in s.get(key, []) if c in close.columns and not pd.isna(f[c])]
            if cs:
                live_rows.append(["籃%s" % s["date"], dates[i + 1], dates[i + 20],
                                  int(round(1e6 * (f[cs].mean() - f[univ.iloc[i]].mean()))), "TWD"])
                next_i = i + 20
        with open(os.path.join(TRACK, fname), "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["代號", "進場時間", "出場時間", "已實現淨損益", "損益幣別"])
            w.writerows(live_rows)
    with open(os.path.join(TRACK, "summary.json"), "w", encoding="utf-8") as f:
        json.dump({"since": sorted(os.listdir(d))[0][:10] if os.listdir(d) else last, "date": last, "lists": res},
                  f, ensure_ascii=False, separators=(",", ":"))
