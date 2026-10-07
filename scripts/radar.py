"""起漲雷達:營收動能(爆發前)與爆量突破(剛爆發),附回測、即時判斷門檻與名單實績追蹤。

由 signals.py 呼叫 build(L),L 是 signals.main() 的區域變數。輸出:
  data/radar/latest.json   今日名單 + 回測統計
  data/radar/live.json     上市股的突破門檻,讓網頁在排程更新前就能用證交所當日資料即時判斷
  data/track/lists/D.json  每天的名單快照(只增不改,用來事後驗證)
  data/track/summary.json  名單實績:每天的名單之後實際表現

回測規則與 signals.py 相同:收盤後才知道、隔天開盤進場、扣交易成本;
月營收視為次月 11 日起才知道(法定公告期限是 10 日)。
"""
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

RULES = {
    "rev_high": {"name": "營收創 12 個月新高且年增 ≥ 30%",
                 "desc": "月營收公告後的第一個交易日(視為次月 11 日),當月營收高於前 12 個月且年增 ≥ 30%"},
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
    # 連續創新高月數
    streak = rec.astype(int).copy()
    for i in range(1, len(streak)):
        streak.iloc[i] = (streak.iloc[i - 1] + 1) * rec.iloc[i].astype(int)
    return {"months": months, "rev": rev, "yoy": yoy, "mom": mom, "rec": rec, "yoy3": yoy3, "streak": streak}


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

    D = {k: to_daily(rp[k], rp["months"], close.index) for k in ("yoy", "yoy3", "rec")}
    newpub = pd.Series(False, index=close.index)
    for y, m in rp["months"]:
        i = pd.to_datetime(close.index).searchsorted(pd.Timestamp(y + (m == 12), m % 12 + 1, 11))
        if i < len(close.index):
            newpub.iloc[i] = True
    tradable = vyi >= MIN_VALUE

    surge = (vyi >= SURGE * avg20p) & (chg >= 5) & tradable
    bo = surge & (close >= mx60) & (mx60 / mn60 - 1 <= 0.35) & (close >= mx250)
    sig = {
        "rev_high": pd.DataFrame(np.outer(newpub.values, np.ones(len(codes), bool)), index=close.index, columns=codes)
        & (D["rec"] == 1) & (D["yoy"] >= REV_YOY) & tradable,
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
        }

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
        if not (rp["rec"].at[mi, c] and (rp["yoy"].at[mi, c] or 0) >= REV_YOY):
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
        x["why"] = rev_reasons(x)
        rev_list.append(x)
    rev_list.sort(key=lambda x: (not x["rev_new"], -(x["yoy3"] or 0)))

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
    doc = dict(meta, stats=stats, base=base, rev=rev_list, breakout=bo_list)
    with open(os.path.join(OUT, "latest.json"), "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))

    write_live(L, close, vyi, chg, D, last, names, vol60, vol_cut)
    track(L, rev_list, bo_list, close, opn, vyi, dates)
    print("radar: rev %d, breakout %d" % (len(rev_list), len(bo_list)))
    return doc


def rev_reasons(x):
    out = ["%s 月營收年增 %+.0f%%,創近 12 個月新高" % (x["rev_month"][5:].lstrip("0"), x["yoy"])]
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


def track(L, rev_list, bo_list, close, opn, vyi, dates):
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
    }
    p = os.path.join(d, last + ".json")
    if not os.path.exists(p):
        with open(p, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, separators=(",", ":"))

    names = {"rev": "營收動能", "breakout": "爆量突破", "picks": "法人資金流向", "dump": "法人持續調節"}
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
    os.makedirs(TRACK, exist_ok=True)
    with open(os.path.join(TRACK, "summary.json"), "w", encoding="utf-8") as f:
        json.dump({"since": sorted(os.listdir(d))[0][:10] if os.listdir(d) else last, "date": last, "lists": res},
                  f, ensure_ascii=False, separators=(",", ":"))
