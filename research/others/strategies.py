"""台股常用策略回測（2026-11-03，見 research/others/PROTOCOL.md）。
資料、成本、交易時點跟凍結的起漲雷達回測一樣（oos-2010/frozen）：換股日（月營收公布後）收盤選股、隔天開盤買賣，
漲停開盤不買，來回成本 0.585%，下市照收盤價結算。每檔等權，賣掉不在新名單的、空出的錢平分買新的。
參數照出處，不調。本益比、淨值比、殖利率來自證交所／櫃買中心每月快照（data/valhist，換股日當天或之前最新一份）。
用法：python strategies.py [--only 名稱]"""
import os, sys, json, glob, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "oos-2010", "frozen")); sys.path.insert(0, os.path.join(HERE, "..", "compare"))
import buy as U
import compare as K                       # 起漲雷達 A、C1 當對照
from bt import metrics, index_eq
O, C, N, COST, dates, codes = U.O, U.C, U.N, U.COST, U.dates, U.codes
NC = len(codes); REB = sorted(U.REB); LIM = 1.095
REVV = U.REV.values                       # [月份序號, 股票]
ret = lambda d, a, b=0: C[d - b] / C[d - a] - 1 if d - a >= 0 else np.full(NC, np.nan)
liquid = lambda d: (U.v20[d] >= 0.3) & ~np.isnan(C[d])          # 跟起漲雷達同一個流動性門檻（日均成交 3,000 萬）
def top_half(d):                                                 # 成交額前 50%
    v = np.where(np.isnan(C[d]), np.nan, U.v20[d]); med = np.nanmedian(v); return v >= med
def yoy(k, lag=0):
    if k - lag - 12 < 0: return np.full(NC, np.nan)
    return REVV[k - lag] / REVV[k - lag - 12] - 1
def std(d, n):
    r = U.F["chg"].values[max(0, d - n + 1):d + 1]; return np.nanstd(r, axis=0) if len(r) >= n * 0.8 else np.full(NC, np.nan)

# 本益比、淨值比、殖利率快照
VAL = {}
for f in sorted(glob.glob(os.path.join(HERE, "..", "..", "data", "valhist", "*.json"))):
    VAL[os.path.basename(f)[:10]] = json.load(open(f, encoding="utf-8"))
VKEYS = sorted(VAL)
def val(d, field):                       # field: 0 本益比、1 淨值比、2 殖利率
    ks = [k for k in VKEYS if k <= dates[d]]
    if not ks or (pd.Timestamp(dates[d]) - pd.Timestamp(ks[-1])).days > 45: return None
    v = VAL[ks[-1]]; return np.array([(v.get(c) or [np.nan] * 3)[field] if c in v else np.nan for c in codes], dtype=float)

def pick(score, ok, n, asc=False):       # 依分數排序取前 n
    s = np.where(ok & ~np.isnan(score), score, np.nan)
    idx = np.where(~np.isnan(s))[0]
    return list(idx[np.argsort(s[idx] if asc else -s[idx], kind="stable")][:n])

def rev_pool(d):                          # FinLab 營收動能選股池：連續 3 個月年增 > 0，最新年增 10%～150%
    k = U.mk_day[d]; y0, y1, y2 = yoy(k), yoy(k, 1), yoy(k, 2)
    return (y0 > 0) & (y1 > 0) & (y2 > 0) & (y0 >= 0.10) & (y0 <= 1.50), y0

def pct(x, ok):                           # 池內百分位排名（0～1）
    s = pd.Series(np.where(ok, x, np.nan)); return s.rank(pct=True).values

STRATS = {
    # 名稱: (選股函數, 檔數, 每幾個換股日換一次, 出處)
    "價格動能 60 日": (lambda d: pick(ret(d, 60), liquid(d), 30), 30, 1, "FinLab 選股方法實測：近 60 日漲幅、30 檔、月換"),
    "動能 12-1 個月": (lambda d: pick(ret(d, 252, 21), liquid(d), 30), 30, 1, "Jegadeesh & Titman (1993)；學術慣例：過去 12 個月跳過最近 1 個月"),
    "52 週新高接近度": (lambda d: pick(C[d] / np.nanmax(C[max(0, d - 251):d + 1], axis=0), liquid(d), 30), 30, 1, "George & Hwang (2004)"),
    "低波動 60 日": (lambda d: pick(std(d, 60), top_half(d), 30, asc=True), 30, 1, "FinLab 低波動實測：60 日波動最低 30 檔、成交額前 50%、月換"),
    "營收動能": (lambda d: (lambda p, y: pick(y, p & liquid(d), 40))(*rev_pool(d)), 40, 1, "FinLab 多因子文章單因子：連續 3 月年增為正、年增 10～150%、40 檔"),
    "營收創 4 年新高": (lambda d: (lambda k: pick(yoy(k), liquid(d) & (k >= 48) & (REVV[k] >= np.nanmax(REVV[max(0, k - 47):k], axis=0)), 30))(U.mk_day[d]), 30, 1, "鉅亨易策略：最新月營收創 4 年新高（不含法人條件），依年增排序取 30 檔"),
    "外資買超 20 日": (lambda d: None if not np.nanmax(np.abs(np.nan_to_num(U.fo20[d]))) > 0 else pick(U.fo20[d], liquid(d), 30), 30, 1, "籌碼選股常見做法：外資近 20 日買超佔成交額，30 檔、月換（2012-05 起才有資料）"),
    "低股價淨值比": (lambda d: (lambda v: None if v is None else pick(v, top_half(d) & (v > 0), 30, asc=True))(val(d, 1)), 30, 1, "FinLab 選股方法實測：低 PB、30 檔、月換"),
    "低本益比": (lambda d: (lambda v: None if v is None else pick(v, top_half(d) & (v > 0), 30, asc=True))(val(d, 0)), 30, 1, "FinLab 選股方法實測：低 PE、30 檔、月換"),
    "高殖利率": (lambda d: (lambda v: None if v is None else pick(v, top_half(d) & (v > 0), 30))(val(d, 2)), 30, 1, "高股息常見做法：殖利率最高 30 檔、成交額前 50%、月換"),
    "風險調整動能": (lambda d: pick(ret(d, 126) / std(d, 120), liquid(d) & (yoy(U.mk_day[d]) > 0) & (ret(d, 63) > 0) & (ret(d, 126) > 0), 15), 15, 3,
                 "FinLab 低波動優化版（不含 ROE，資料沒有）：營收年增 > 0、3 與 6 個月報酬 > 0，6 個月報酬 ÷ 120 日波動，15 檔、季換"),
    "三因子（營收、動能、低波）": (lambda d: (lambda p, y: pick(pct(y, p) + pct(ret(d, 60), p) + pct(-std(d, 60), p), p & liquid(d), 40))(*rev_pool(d)), 40, 1,
                    "FinLab 四因子（不含 ROE，資料沒有）：營收動能池內，營收年增、60 日動能、60 日低波動百分位相加，40 檔、等權"),
}

def sim(select, n, every, start, end):
    d0 = dates.index([x for x in dates if x >= start][0]); d1 = min(N - 1, int(U.dt.searchsorted(pd.Timestamp(end))))
    rebs = [d for d in REB if d0 <= d < d1][::every]
    cash, pos, eq, trades, expo, sell, buy, cnt = 1.0, {}, [], [], 0, set(), [], 0
    for d in range(d0, d1 + 1):
        for j in list(sell):
            p = O[d, j]
            if np.isnan(p):
                if d > U.lastvalid[j]: p = pos[j]["last"]
                else: continue
            cash += pos[j]["u"] * p * (1 - COST / 2); trades.append((p / pos[j]["entry"] * (1 - COST / 2) / (1 + COST / 2), d - pos[j]["e"]))
            del pos[j]; sell.discard(j)
        if buy and d < d1:
            total = cash + sum(v["u"] * (O[d, j] if not np.isnan(O[d, j]) else v["last"]) for j, v in pos.items())
            for j in buy:
                if len(pos) >= n or cash <= 1e-9: break
                o, pc = O[d, j], U.prev_close[d, j]
                if j in pos or np.isnan(o) or np.isnan(pc) or o >= pc * LIM: continue
                amt = min(total / n, cash); pos[j] = dict(u=amt / (o * (1 + COST / 2)), e=d, entry=o, last=o); cash -= amt
            buy = []
        for j, v in pos.items():
            if not np.isnan(C[d, j]): v["last"] = C[d, j]
        if d < d1: eq.append((dates[d], cash + sum(v["u"] * v["last"] for v in pos.values()))); expo += bool(pos)
        for j in pos:
            if d >= U.lastvalid[j] and U.lastvalid[j] < N - 1: sell.add(j)
        if d in rebs and d < d1:
            lst = select(d)
            if lst is None: continue                     # 這天沒有估值資料：維持原持股
            keep = set(lst); cnt += 1
            for j in pos:
                if j not in keep: sell.add(j)
            buy = [j for j in lst if j not in pos or j in sell]
    for j, v in pos.items(): trades.append((v["last"] / v["entry"], d1 - v["e"]))
    global LAST; LAST = ({j: dict(v) for j, v in pos.items()}, set(sell), d1)   # 期末持股（前進觀察用，不影響結果）
    s = pd.Series([x[1] for x in eq], index=pd.to_datetime([x[0] for x in eq]))
    return s, trades, expo / max(len(eq), 1), cnt

PERIODS = K.PERIODS
R = lambda m: {k: round(float(v), 2) for k, v in m.items()}
if __name__ == "__main__":
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
    idx = {p: R(metrics(index_eq(a, b))) for p, (a, b) in PERIODS.items() if any(a <= x < b for x in dates)}
    out = {"加權指數": idx, "估值快照": [VKEYS[0], VKEYS[-1], len(VKEYS)] if VKEYS else None, "策略": {}}
    VSTART = VKEYS[0] if VKEYS else "2100-01-01"
    def add(name, src, runner, needs_val=False):
        r = {"出處": src, "期間": {}}
        for p, (a, b) in PERIODS.items():
            if p not in idx: continue
            ix = idx[p]
            if needs_val and VSTART > a:                     # 估值資料晚於期間起點：期間從第一份估值快照開始，大盤也同一段比
                if VSTART >= b: r["期間"][p] = None; continue
                a = VSTART; ix = R(metrics(index_eq(a, b)))
            e, t, x, *c = runner(a, b)
            if len(e) < 30 or e.iloc[-1] == e.iloc[0] and len(t) == 0: r["期間"][p] = None; continue
            m = R(metrics(e, t, x))
            r["期間"][p] = {k: m[k] for k in ("年化%", "最大回撤%", "夏普", "交易數", "暴露%")} | {"超額%": round(m["年化%"] - ix["年化%"], 2), "起": a}
            if c: r["期間"][p]["換股次數"] = c[0]
        got = [v for v in r["期間"].values() if v]
        r["最差超額%"] = min(v["超額%"] for v in got) if len(got) == len(idx) else None
        r["三段都贏"] = bool(got) and len(got) == len(idx) and all(v["超額%"] > 0 for v in got)
        out["策略"][name] = r; print(name, r["最差超額%"], file=sys.stderr, flush=True)
    for name, (fn, n, every, src) in STRATS.items():
        if only and only != name: continue
        add(name, src, lambda a, b, fn=fn, n=n, every=every: sim(fn, n, every, a, b), needs_val=name in ("低股價淨值比", "低本益比", "高殖利率"))
    if not only:
        add("起漲雷達 A（對照）", "現行規則", lambda a, b: K.sim("brk", "stars", "none", 10, a, b))
        add("起漲雷達 C1（對照）", "現行規則加大盤濾網", lambda a, b: K.sim("brk", "stars", "exit", 10, a, b))
    print(json.dumps(out, ensure_ascii=False, indent=1))
