"""盤前雷達多策略比較（2026-11-02，樣本內，見 research/compare/PROTOCOL.md）。
選股訊號、資料、成本都用凍結的 oos-2010/frozen（bt.py、buy.py），只換「怎麼買、怎麼賣、要不要看大盤、同時幾檔」。
進場：brk（收盤創 20 日新高，隔天開盤買）、imm（換股日隔天開盤直接買前 10 名）
出場：stars（換股日星等 < 4 賣，現行）、buffer（換股日掉出候選前 20 名才賣）、hold60（抱滿 60 個交易日賣）、trail（stars 加上從最高收盤回落 15% 賣）
大盤：none、exit（加權指數跌破 200 日線全出且停買）、entry（跌破只停買）
檔數：10、5（每檔 = 總淨值 / 檔數）
用法：python compare.py [--check]   --check 只重現 A 原規則（brk、stars、none、10）對照凍結結果"""
import os, sys, json, types, itertools, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
F = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "oos-2010", "frozen"); sys.path.insert(0, F)
import buy as U                                   # 凍結的訊號與資料
from bt import metrics, index_eq
tx = np.asarray(U.taiex.ffill().values, dtype=float)
ma = pd.Series(tx).rolling(200, min_periods=200).mean().values
MKT = ~(tx < ma)
O, C, N, COST, dates = U.O, U.C, U.N, U.COST, U.dates
LIM = 1.095


def sim(entry="brk", exit="stars", filt="none", slots=10, start="2000-01-01", end="2100-01-01", top=10):
    d0 = dates.index([x for x in dates if x >= start][0])
    d1 = min(N - 1, int(U.dt.searchsorted(pd.Timestamp(end))))
    cash, pos, to_sell, eq, trades, expo = 1.0, {}, set(), [], [], 0
    watch, buy_next = [], []
    for d in range(d0, d1 + 1):
        for j in list(to_sell):                   # 開盤：賣
            p = O[d, j]
            if np.isnan(p):
                if d > U.lastvalid[j]: p = pos[j]["last"]
                else: continue
            cash += pos[j]["units"] * p * (1 - COST / 2)
            trades.append((p / pos[j]["entry"] * (1 - COST / 2) / (1 + COST / 2), d - pos[j]["e"]))
            del pos[j]; to_sell.discard(j)
        if buy_next and d < d1:                   # 開盤：買
            total = cash + sum(v["units"] * (O[d, j] if not np.isnan(O[d, j]) else v["last"]) for j, v in pos.items())
            for j in buy_next:
                if len(pos) >= slots or cash <= 1e-9: break
                if j in pos: continue
                o, pc = O[d, j], U.prev_close[d, j]
                if np.isnan(o) or np.isnan(pc) or o >= pc * LIM: continue
                amt = min(total / slots, cash)
                pos[j] = dict(units=amt / (o * (1 + COST / 2)), e=d, entry=o, last=o, peak=o)
                cash -= amt
                if j in watch: watch.remove(j)
            buy_next = []
        for j, v in pos.items():                  # 收盤：估值
            if not np.isnan(C[d, j]): v["last"] = C[d, j]; v["peak"] = max(v["peak"], C[d, j])
        val = cash + sum(v["units"] * v["last"] for v in pos.values())
        if d < d1: eq.append((dates[d], val)); expo += bool(pos)
        if d in U.REB:                            # 收盤：換股日的賣出判斷
            if exit in ("stars", "trail"):
                st = U.stars_at(d)
                for j in pos:
                    if st[j] < 4: to_sell.add(j)
            elif exit == "buffer":
                keep = set(U.candidates(d, "cur")[:20])
                for j in pos:
                    if j not in keep: to_sell.add(j)
        for j, v in pos.items():                  # 每天的賣出判斷
            if exit == "hold60" and d - v["e"] >= 60: to_sell.add(j)
            if exit == "trail" and v["last"] < v["peak"] * 0.85: to_sell.add(j)
        for j in pos:
            if j not in to_sell and d >= U.lastvalid[j] and U.lastvalid[j] < N - 1: to_sell.add(j)
        if filt == "exit" and not MKT[d]:
            for j in pos: to_sell.add(j)
        if d >= d1: continue
        if filt != "none" and not MKT[d]:
            buy_next = []; continue
        free = slots - (len(pos) - len(to_sell))
        if d in U.REB:
            watch = [j for j in U.candidates(d, "cur")[:top] if j not in pos or j in to_sell]
        if free <= 0 or not watch: continue
        if entry == "imm":
            if d in U.REB: buy_next = list(watch)
        else:
            buy_next = [j for j in watch if j not in pos and not np.isnan(U.HI20[d, j]) and C[d, j] > U.HI20[d, j]]
    for j, v in pos.items(): trades.append((v["last"] / v["entry"], d1 - v["e"]))
    s = pd.Series([x[1] for x in eq], index=pd.to_datetime([x[0] for x in eq]))
    return s, trades, expo / max(len(eq), 1)


PERIODS = {"2005–2009": ("2005-04-01", "2010-01-01"), "2011–2018": ("2011-04-01", "2019-01-01"), "2019–2026": ("2019-05-01", "2100-01-01")}
R = lambda m: {k: round(float(v), 2) for k, v in m.items()}

if __name__ == "__main__":
    if "--check" in sys.argv:              # 同一份資料上，這支的 A 要跟凍結程式 U.sim 完全一樣
        out = {}
        for name, (a, b) in PERIODS.items():
            if not any(a <= x < b for x in dates): continue
            e, t, x = sim(start=a, end=b); e2, t2, x2 = U.sim(timing="brk", exit_k=4, start=a, end=b)
            out[name] = {"這支": R(metrics(e, t, x))["年化%"], "凍結": R(metrics(e2, t2, x2))["年化%"], "最大差": float(abs(e - e2).max())}
        print(json.dumps(out, ensure_ascii=False)); sys.exit()
    idx = {n: R(metrics(index_eq(a, b))) for n, (a, b) in PERIODS.items() if any(a <= x < b for x in dates)}
    rows = []
    for entry, exit, filt, slots in itertools.product(("brk", "imm"), ("stars", "buffer", "hold60", "trail"), ("none", "exit", "entry"), (10, 5)):
        r = {"進場": entry, "出場": exit, "大盤": filt, "檔數": slots, "期間": {}}
        for name, (a, b) in PERIODS.items():
            if name not in idx: continue
            e, t, x = sim(entry, exit, filt, slots, a, b)
            m = R(metrics(e, t, x))
            r["期間"][name] = {k: m[k] for k in ("年化%", "最大回撤%", "夏普", "交易數", "暴露%")} | {"超額%": round(m["年化%"] - idx[name]["年化%"], 2)}
        ex = [p["超額%"] for p in r["期間"].values()]
        r["最差超額%"] = min(ex); r["最深回撤%"] = min(p["最大回撤%"] for p in r["期間"].values())
        rows.append(r); print(entry, exit, filt, slots, r["最差超額%"], file=sys.stderr, flush=True)
    rows.sort(key=lambda r: (-r["最差超額%"], -r["最深回撤%"]))
    print(json.dumps({"加權指數": idx, "策略": rows}, ensure_ascii=False, indent=1))
