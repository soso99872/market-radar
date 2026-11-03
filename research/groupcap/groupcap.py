"""族群上限測試（2026-11-03，見 research/groupcap/PROTOCOL.md）。
跟 compare.sim 完全一樣，只在買進前多一道檢查：
  corr：這檔過去 60 個交易日的日報酬，跟手上已經有的股票相關係數 > 0.7 的已經有 2 檔，就不買（只用前一天收盤以前的資料）
  theme：照 data/sectors/topics.json（2026-11-03 的分類）的族群，同一族群已經有 2 檔就不買（用今天的分類回推歷史，有偷看）
用法：python groupcap.py [--check]"""
import os, sys, json, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "compare"))
import compare as K
from compare import U, MKT, O, C, N, COST, dates, LIM, PERIODS, R
from bt import metrics, index_eq
RET = np.vstack([np.full(C.shape[1], np.nan), C[1:] / C[:-1] - 1])
TOP = json.load(open(os.path.join(HERE, "topics-2026-11-03.json"), encoding="utf-8"))
SECTOR = {}
for t in TOP:
    for c in t["codes"]: SECTOR.setdefault(c, t.get("sector") or t["id"])
SEC = [SECTOR.get(c) for c in U.codes]

def corr(a, b, d):
    x, y = RET[max(0, d - 60):d, a], RET[max(0, d - 60):d, b]
    m = ~np.isnan(x) & ~np.isnan(y)
    if m.sum() < 40: return 0.0
    return float(np.corrcoef(x[m], y[m])[0, 1])

def blocked(cap, j, held, d):
    if cap == "corr": return sum(corr(j, h, d) > 0.7 for h in held) >= 2
    if cap == "theme": return SEC[j] is not None and sum(SEC[h] == SEC[j] for h in held) >= 2
    return False

def sim(entry="brk", exit="stars", filt="none", slots=10, start="2000-01-01", end="2100-01-01", top=10, cap=None):
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
                if cap and blocked(cap, j, list(pos), d): continue
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
    global LAST; LAST = ({j: dict(v) for j, v in pos.items()}, set(to_sell), d1)   # 期末持股（前進觀察用，不影響結果）
    s = pd.Series([x[1] for x in eq], index=pd.to_datetime([x[0] for x in eq]))
    return s, trades, expo / max(len(eq), 1)



def crash(e, a, b):
    tx = pd.Series(K.tx, index=pd.to_datetime(dates)).pct_change()
    r = e.pct_change(); m = tx.reindex(r.index); bad = m[m <= -0.03].index
    return {"大跌日數": int(len(bad)), "大盤平均%": round(float(m[bad].mean()) * 100, 2) if len(bad) else None,
            "策略平均%": round(float(r[bad].mean()) * 100, 2) if len(bad) else None, "策略最差單日%": round(float(r.min()) * 100, 2)}

if __name__ == "__main__":
    if "--check" in sys.argv:          # cap=None 時要跟 compare.sim 逐日一樣
        out = {}
        for p, (a, b) in PERIODS.items():
            if not any(a <= x < b for x in dates): continue
            e, *_ = sim(start=a, end=b); e2, *_ = K.sim(start=a, end=b); out[p] = float(abs(e - e2).max())
        print(json.dumps(out, ensure_ascii=False)); sys.exit()
    idx = {p: R(metrics(index_eq(a, b))) for p, (a, b) in PERIODS.items() if any(a <= x < b for x in dates)}
    out = {"加權指數": idx, "族群對照": {"有族群的股票數": sum(s is not None for s in SEC)}, "版本": {}}
    for base, filt in (("A", "none"), ("C1", "exit")):
        for cap in (None, "corr", "theme"):
            name = base + ("" if cap is None else {"corr": "＋相關係數上限", "theme": "＋族群上限"}[cap])
            r = {}
            for p, (a, b) in PERIODS.items():
                if p not in idx: continue
                e, t, x = sim("brk", "stars", filt, 10, a, b, cap=cap)
                m = R(metrics(e, t, x))
                r[p] = {k: m[k] for k in ("年化%", "最大回撤%", "夏普", "交易數")} | {"超額%": round(m["年化%"] - idx[p]["年化%"], 2)} | crash(e, a, b)
            out["版本"][name] = r; print(name, file=sys.stderr, flush=True)
    print(json.dumps(out, ensure_ascii=False, indent=1))
