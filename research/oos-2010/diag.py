"""診斷(非凍結):凍結規則 A 在『已看過』的 2010–2026 資料上的逐筆交易與每日狀態。
跟 frozen/buy.py 的 sim(timing=brk, exit_k=4) 同一套邏輯,只多記錄。最後會比對淨值和 sim 一致。
輸出 diag/trades.csv、diag/daily.csv、diag/check.json。"""
import os, sys, json, warnings; warnings.filterwarnings("ignore")
F_ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frozen"); sys.path.insert(0, F_)
import numpy as np, pandas as pd
import buy as U
from buy import *
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "diag"); os.makedirs(OUT, exist_ok=True)
TX = np.asarray(U.taiex.ffill().values, dtype=float)
assert len(TX) == U.N, (len(TX), U.N)
MA60 = U.close.rolling(60).mean().values

def run(start, end, slots=10, top=10, order="cur", exit_k=4):
    d0 = U.dates.index([x for x in U.dates if x >= start][0]); d1 = min(U.N - 1, int(U.dt.searchsorted(pd.Timestamp(end))))
    cash, pos, to_sell, eq, T, daily = 1.0, {}, {}, [], [], []
    watch, buy_next = [], []
    for d in range(d0, d1 + 1):
        for j in list(to_sell):
            p = U.O[d, j]
            if np.isnan(p):
                if d > U.lastvalid[j]: p = pos[j]["last"]
                else: continue
            cash += pos[j]["units"] * p * (1 - U.COST / 2)
            v = pos[j]; T.append(dict(code=U.codes[j], ind=U.gi[j], sig=U.dates[v["sd"]], entry=U.dates[v["e"]], exit=U.dates[d],
                     ret=p / v["entry"] * (1 - U.COST / 2) / (1 + U.COST / 2) - 1, hold=d - v["e"], why=to_sell[j],
                     st=v["st"], r60=v["r60"], peer=v["peer"], yoy3=v["yoy3"], peak=v["peak"] / v["entry"] - 1))
            del pos[j]; del to_sell[j]
        nb = 0
        if buy_next and d < d1:
            total = cash + sum(v["units"] * (U.O[d, j] if not np.isnan(U.O[d, j]) else v["last"]) for j, v in pos.items())
            for j, sd in buy_next:
                if len(pos) >= slots or cash <= 1e-9: break
                if j in pos: continue
                o, pc = U.O[d, j], U.prev_close[d, j]
                if np.isnan(o) or np.isnan(pc) or o >= pc * 1.095: continue
                amt = min(total / slots, cash); s = U.sig_at(sd); st = U.stars_at(sd)
                pos[j] = dict(units=amt / (o * (1 + U.COST / 2)), e=d, entry=o, last=o, sd=sd, st=int(st[j]), r60=float(s["r60"][j]),
                              peer=float(s["peer"][j]) if not np.isnan(s["peer"][j]) else None, yoy3=float(s["yoy3"][j]) if not np.isnan(s["yoy3"][j]) else None, peak=o)
                cash -= amt; nb += 1
                if j in watch: watch.remove(j)
            buy_next = []
        for j, v in pos.items():
            if not np.isnan(U.C[d, j]): v["last"] = U.C[d, j]; v["peak"] = max(v["peak"], U.C[d, j])
        val = cash + sum(v["units"] * v["last"] for v in pos.values())
        n4 = None
        if d in U.REB:
            st = U.stars_at(d); n4 = int(len(U.candidates(d, order)))
            for j in pos:
                if st[j] < exit_k and j not in to_sell: to_sell[j] = "stars"
        for j in pos:
            if j not in to_sell and d >= U.lastvalid[j] and U.lastvalid[j] < U.N - 1: to_sell[j] = "delist"
        t = U.V[d] >= 0.3
        br = float(np.nanmean((U.C[d] > MA60[d])[t & ~np.isnan(MA60[d])])) if t.sum() else np.nan
        if d < d1: eq.append(val); daily.append(dict(date=U.dates[d], eq=val, npos=len(pos), cash=cash / val, bought=nb, n4=n4,
                                                   taiex=float(TX[d]), breadth60=br, reb=int(d in U.REB)))
        if d >= d1: continue
        free = slots - (len(pos) - len(to_sell))
        if d in U.REB:
            watch = [j for j in U.candidates(d, order)[:top] if j not in pos or j in to_sell]
        if free <= 0 or not watch: continue
        buy_next = [(j, d) for j in watch if j not in pos and not np.isnan(U.HI20[d, j]) and U.C[d, j] > U.HI20[d, j]]
    for j, v in pos.items():
        T.append(dict(code=U.codes[j], ind=U.gi[j], sig=U.dates[v["sd"]], entry=U.dates[v["e"]], exit=None, ret=v["last"] / v["entry"] - 1,
                      hold=d1 - v["e"], why="open", st=v["st"], r60=v["r60"], peer=v["peer"], yoy3=v["yoy3"], peak=v["peak"] / v["entry"] - 1))
    return pd.DataFrame(T), pd.DataFrame(daily)

U.MOM = 20
chk = {}
for lab, a, b in (("oos", "2011-04-01", "2019-01-01"), ("is", "2019-05-01", "2100-01-01")):
    T, Dd = run(a, b)
    e, t, x = U.sim(timing="brk", exit_k=4, start=a, end=b)
    chk[lab] = {"diag_final": float(Dd["eq"].iloc[-1]), "sim_final": float(e.iloc[-1]), "trades": [len(T), len(t)]}
    T.to_csv(os.path.join(OUT, "trades_%s.csv" % lab), index=False); Dd.to_csv(os.path.join(OUT, "daily_%s.csv" % lab), index=False)
json.dump(chk, open(os.path.join(OUT, "check.json"), "w"), indent=1)
print(json.dumps(chk))
