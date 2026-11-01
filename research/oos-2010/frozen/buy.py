"""買入方式回測。賣出固定:換股日星等 < 4 才賣(上一輪最佳)。

可調:
  slots   同時最多幾檔(每檔 = 總淨值 / slots)
  order   候選排序:cur(首頁前 10 檔規則)、strong(60 日漲最多)、early(60 日漲最少)、rev(近 3 月營收年增最高)
  timing  imm(換股日隔天開盤)、pull(x)(收盤回到月線 x% 以內,隔天開盤)、brk(收盤創 20 日新高,隔天開盤)、
          daily(每天重算星等,哪天變 4★ 以上、有空位就隔天開盤買)
防偷看:條件都用第 d 天收盤判斷、第 d+1 天開盤成交;每日星等只用當天以前公告的營收。
"""
import sys, os, warnings; warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd
from bt import *
import bt as B

MA20 = close.rolling(20).mean().values
HI20 = close.shift(1).rolling(20).max().values
REB = {i for i, _ in reb}
mk_day = np.searchsorted(np.array(avail, dtype="datetime64[ns]"), dt.values, side="right") - 1   # 第 d 天可用的最新月份序號


def sig_at(d):
    """任一天的星等與排序欄位(換股日直接用 SIG)。"""
    if d in SIG: return SIG[d]
    k = mk_day[d]
    m1, m0 = months[k], months[k - 1]
    r1 = REV.loc[[m1]].values[0]; use1 = ~np.isnan(r1)
    g = np.where(use1, GOOD.loc[[m1]].values[0], GOOD.loc[[m0]].values[0]).astype(bool)
    has = use1 | ~np.isnan(REV.loc[[m0]].values[0])
    yoy3 = np.where(use1, YOY3.loc[[m1]].values[0], YOY3.loc[[m0]].values[0])
    acc = np.where(use1, ACC.loc[[m1]].values[0], ACC.loc[[m0]].values[0])
    liq = (v20[d] >= 0.1) & ~np.isnan(C[d]); t = V[d] >= 0.3
    vc = np.nanquantile(vol60[d][t], 0.3) if t.sum() > 20 else np.nan
    SIG[d] = dict(rev=g & has & liq, new=use1, yoy3=yoy3, decel=acc <= -20, dump=fo20[d] <= -10,
                  r60=ret60[d] * 100, peer=peer60(d), lowvol=vol60[d] < vc, v20=v20[d])
    return SIG[d]


MOM, PEER = 20, 15
def stars_at(d):
    s = sig_at(d)
    mo, pe = s["r60"] >= MOM, s["peer"] >= PEER
    st = np.where(mo & pe, 5, np.where(mo | pe, 4, 3)) - (s["decel"] | s["dump"]).astype(int)
    return np.where(s["rev"], st, 0)


def candidates(d, order):
    s, st = sig_at(d), stars_at(d)
    js = [j for j in np.where(st >= 4)[0] if not s["lowvol"][j] and s["v20"][j] >= 0.3]
    y = lambda j: s["yoy3"][j] if not np.isnan(s["yoy3"][j]) else -1e9
    r = lambda j: s["r60"][j] if not np.isnan(s["r60"][j]) else 0
    if order == "cur":
        js.sort(key=lambda j: (-st[j], not s["new"][j], not s["v20"][j] >= 1.0, -y(j)))
        out, per = [], {}
        for j in js:                                   # 同產業最多 3 檔(與首頁相同)
            g_ = gi[j] or codes[j]
            if per.get(g_, 0) < 3: out.append(j); per[g_] = per.get(g_, 0) + 1
        return out
    if order == "strong": return sorted(js, key=lambda j: -r(j))
    if order == "early":  return sorted(js, key=lambda j: r(j))
    if order == "rev":    return sorted(js, key=lambda j: -y(j))


def sim(slots=10, order="cur", timing="imm", px=0.0, top=10, start="2000-01-01", end="2100-01-01", exit_k=4):
    d0 = dates.index([x for x in dates if x >= start][0])
    d1 = min(N - 1, int(dt.searchsorted(pd.Timestamp(end))))
    cash, pos, to_sell, eq, trades, expo = 1.0, {}, set(), [], [], 0
    watch, buy_next = [], []            # 觀察中的候選(換股日產生,到下次換股日失效)、明天開盤要買的
    for d in range(d0, d1 + 1):
        for j in list(to_sell):         # 開盤:賣
            p = O[d, j]
            if np.isnan(p):
                if d > lastvalid[j]: p = pos[j]["last"]
                else: continue
            cash += pos[j]["units"] * p * (1 - COST / 2)
            trades.append((p / pos[j]["entry"] * (1 - COST / 2) / (1 + COST / 2), d - pos[j]["e"]))
            del pos[j]; to_sell.discard(j)
        if buy_next and d < d1:         # 開盤:買
            total = cash + sum(v["units"] * (O[d, j] if not np.isnan(O[d, j]) else v["last"]) for j, v in pos.items())
            for j in buy_next:
                if len(pos) >= slots or cash <= 1e-9: break
                if j in pos: continue
                o, pc = O[d, j], prev_close[d, j]
                if np.isnan(o) or np.isnan(pc) or o >= pc * 1.095: continue
                amt = min(total / slots, cash)
                pos[j] = dict(units=amt / (o * (1 + COST / 2)), e=d, entry=o, last=o)
                cash -= amt
                if j in watch: watch.remove(j)
            buy_next = []
        for j, v in pos.items():        # 收盤:估值
            if not np.isnan(C[d, j]): v["last"] = C[d, j]
        val = cash + sum(v["units"] * v["last"] for v in pos.values())
        if d < d1: eq.append((dates[d], val)); expo += bool(pos)
        if d in REB:                    # 收盤:賣出判斷(星等 < exit_k)
            st = stars_at(d)
            for j in pos:
                if st[j] < exit_k: to_sell.add(j)
        for j in pos:
            if j not in to_sell and d >= lastvalid[j] and lastvalid[j] < N - 1: to_sell.add(j)
        if d >= d1: continue
        free = slots - (len(pos) - len(to_sell))
        if timing == "daily":           # 每天:現在是 4★ 以上、還沒持有的,依排序補
            if free > 0:
                buy_next = [j for j in candidates(d, order) if j not in pos][:max(free * 3, 10)]
            continue
        if d in REB:
            watch = [j for j in candidates(d, order)[:top] if j not in pos or j in to_sell]
        if free <= 0 or not watch: continue
        if timing == "imm":
            if d in REB: buy_next = list(watch)
        elif timing == "pull":
            buy_next = [j for j in watch if j not in pos and not np.isnan(MA20[d, j]) and C[d, j] <= MA20[d, j] * (1 + px)]
        elif timing == "brk":
            buy_next = [j for j in watch if j not in pos and not np.isnan(HI20[d, j]) and C[d, j] > HI20[d, j]]
    for j, v in pos.items(): trades.append((v["last"] / v["entry"], d1 - v["e"]))
    s = pd.Series([x[1] for x in eq], index=pd.to_datetime([x[0] for x in eq]))
    return s, trades, expo / max(len(eq), 1)
