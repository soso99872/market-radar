"""盤前雷達策略回測:逐日重建「當天看得到的」起漲雷達名單,收盤後產生、隔天開盤進場。

防偷看未來(每一項都對應下面程式):
  L1 營收:(y,m) 月營收視為次月 11 日起才知道;用的是公開資訊觀測站當月彙總表(公告當時版本)。
  L2 名單:第 i 天收盤後才算名單,第 i+1 天「開盤價」買,不用第 i 天收盤價成交。
  L3 指標:ret60、外資 20 日、波動度、同業動能只用第 i 天(含)以前的資料。
  L4 還原股價:只排除分割/減資的假漲跌,縮放因子是常數倍,不改報酬;股利沒還原(對策略偏保守)。
  L5 買不到:隔天開盤漲停(≥ 前收 +9.5%)或沒開盤的,那一格放現金。
  L6 下市:持有中下市的股票,基本版用最後收盤價出場,壓力版當成全損。
  L7 存活者偏差:每天的股票池是當天實際有交易的股票,含之後下市的。
  L8 參數:現行門檻是 2026-10 看過 2019–2026 全部資料後才定的 → 2019–2026 對現行規則來說全部是樣本內。
      所以另做「逐年前進」:每年只用之前的資料挑門檻,再拿去做下一年。
  殘留(沒辦法完全排除):產業分類用現在的 industry.json;財務地雷、處置股沒有歷史資料,選股時沒排除。
"""
import os, sys, pickle, itertools, json, math
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
D = pickle.load(open(os.path.join(HERE, "cache.pkl"), "rb"))
F, taiex, rp, IND = D["F"], D["taiex"], D["rp"], D["ind"]
COST = 0.00585                       # 來回(手續費 ×2 + 證交稅),與 signals.COST 相同
MIXED = {"19", "20", "80"}
close, opn, raw = F["close"], F["open"], F["close_raw"]
dates = list(close.index); N = len(dates); codes = list(close.columns)
dt = pd.to_datetime(close.index)
vyi = F["value"] / 1e8
C, O, V = close.values, opn.values, vyi.values

# ---------- 每日指標(L3:全部只往回看) ----------
ret60 = (close / close.shift(60) - 1).values
v20 = vyi.rolling(20, min_periods=15).mean().values
vol60 = F["chg"].rolling(60, min_periods=40).std().values
fo20 = ((F["fo"] * raw).rolling(20, min_periods=15).sum() / F["value"].rolling(20, min_periods=15).sum() * 100).values
ret120 = (close.shift(20) / close.shift(140) - 1).values      # 動能對照組:120 日報酬、跳過最近 20 日
gi = np.array([IND.get(c) if IND.get(c) not in MIXED else None for c in codes], dtype=object)
groups = {}
for j, g in enumerate(gi):
    if g: groups.setdefault(g, []).append(j)
prev_close = np.vstack([np.full(len(codes), np.nan), C[:-1]])
# 持有中下市:之後不再有任何收盤價
lastvalid = np.array([np.where(~np.isnan(C[:, j]))[0].max() if (~np.isnan(C[:, j])).any() else -1 for j in range(len(codes))])

# ---------- 月營收(L1) ----------
months = rp["months"]
avail = [pd.Timestamp(y + (m == 12), m % 12 + 1, 11) for y, m in months]
REV, GOOD, YOY3 = rp["rev"].reindex(columns=codes), rp["good"].reindex(columns=codes), rp["yoy3"].reindex(columns=codes)
ACC = (YOY3 - YOY3.shift(3))
# 換股日 = 每月營收公告後的第一個交易日(與 radar.newpub 相同)
reb = []
for mk, ((y, m), a) in enumerate(zip(months, avail)):
    i = dt.searchsorted(a)
    if 0 < i < N - 1: reb.append((i, mk))
reb_idx = {i: k for k, (i, k) in enumerate(reb)}
mi_of = {i: k for i, k in reb}           # 換股日 → 最新可用月份序號(就是剛公告那個月)


def peer60(i):
    r, t = ret60[i], V[i] >= 0.3
    out = np.full(len(codes), np.nan)
    for g, js in groups.items():
        js = np.array(js); ok = js[t[js] & ~np.isnan(r[js])]
        if len(ok) >= 5: out[js] = r[ok].mean() * 100
    return out


SIG = {}   # 換股日 i → 營收名單特徵(與參數無關的部分先算好)
for i, k in reb:
    m1, m0 = months[k], months[k - 1] if k > 0 else None
    r1 = REV.loc[[m1]].values[0]
    use1 = ~np.isnan(r1)
    g = np.where(use1, GOOD.loc[[m1]].values[0], GOOD.loc[[m0]].values[0] if m0 else False).astype(bool)
    has = use1 | (~np.isnan(REV.loc[[m0]].values[0]) if m0 else use1)
    yoy3 = np.where(use1, YOY3.loc[[m1]].values[0], YOY3.loc[[m0]].values[0] if m0 else np.nan)
    acc = np.where(use1, ACC.loc[[m1]].values[0], ACC.loc[[m0]].values[0] if m0 else np.nan)
    liq = (v20[i] >= 0.1) & ~np.isnan(C[i])
    t = V[i] >= 0.3
    vc = np.nanquantile(vol60[i][t], 0.3) if t.sum() > 20 else np.nan
    SIG[i] = dict(rev=g & has & liq, new=use1, yoy3=yoy3, decel=acc <= -20, dump=fo20[i] <= -10,
                  r60=ret60[i] * 100, peer=peer60(i), lowvol=vol60[i] < vc, v20=v20[i])


def stars(i, mom=20, peer=15):
    s = SIG[i]
    mo = s["r60"] >= mom; pe = s["peer"] >= peer
    st = np.where(mo & pe, 5, np.where(mo | pe, 4, 3)) - (s["decel"] | s["dump"]).astype(int)
    return np.where(s["rev"], st, 0)


def pick_top(i, st, n=10, cap=3):
    s = SIG[i]
    cand = [j for j in np.where(st >= 4)[0] if not s["lowvol"][j] and s["v20"][j] >= 0.3]
    cand.sort(key=lambda j: (-st[j], not s["new"][j], not s["v20"][j] >= 1.0, -(s["yoy3"][j] if not np.isnan(s["yoy3"][j]) else -1e9)))
    out, per = [], {}
    for j in cand:
        g = gi[j] or codes[j]
        if len(out) < n and per.get(g, 0) < cap:
            out.append(j); per[g] = per.get(g, 0) + 1
    return out


# ---------- 選股規則 ----------
def rule(name, **kw):
    def f(i):
        if name == "star4": return list(np.where(stars(i, **kw) >= 4)[0])
        if name == "star5": return list(np.where(stars(i, **kw) >= 5)[0])
        if name == "top10": return pick_top(i, stars(i, **kw))
        if name == "rev":   return list(np.where(SIG[i]["rev"])[0])
        if name == "allEW": return list(np.where((V[i] >= 0.3) & ~np.isnan(C[i]))[0])
        if name == "mom10":   # 純動能:成交 ≥ 1 億裡 120 日報酬(跳過近 20 日)最強 10 檔
            r = np.where((v20[i] >= 1.0), ret120[i], np.nan)
            ok = np.where(~np.isnan(r))[0]
            return list(ok[np.argsort(-r[ok])][:10])
    return f


# ---------- 回測引擎 ----------
def path(j, e, e2, delist_loss):
    """j 從第 e 天開盤到第 e2 天開盤的價格路徑(長度 e2-e+1):[開盤 e, 收盤 e..e2-1, 開盤 e2]。"""
    p0 = O[e, j] if not np.isnan(O[e, j]) else (C[:e, j][~np.isnan(C[:e, j])][-1] if (~np.isnan(C[:e, j])).any() else np.nan)
    seq = [p0] + list(C[e:e2, j]) + [O[e2, j]]
    out, last = [], p0
    for t, p in enumerate(seq):
        d = e + max(t - 1, 0) if t < len(seq) - 1 else e2
        if np.isnan(p):
            p = 0.0 if (delist_loss and d > lastvalid[j]) else last
        out.append(p); last = p if p else last
    return np.array(out) / p0


def run(select, start="2000-01-01", end="2100-01-01", delist_loss=False, stock_w=1.0):
    """第 i 個換股日收盤後選股,第 i+1 天開盤等權買進(L2),持有到下一個換股日隔天開盤。
    stock_w < 1:其餘資金放加權指數,每次換股時配回比例。"""
    rs = [i for i, _ in reb if start <= dates[i] < end and i + 1 < N]
    endi = min(N - 1, int(dt.searchsorted(pd.Timestamp(end))))
    vals, idx = [], []
    val, hold, trades, expo, nd = 1.0, {}, [], 0, 0
    tx = taiex.ffill().values
    for k, i in enumerate(rs):
        e = i + 1
        e2 = rs[k + 1] + 1 if k + 1 < len(rs) else endi
        if e2 <= e: break
        want = select(i)
        keep = [j for j in want if j in hold]
        new = [j for j in want if j not in hold and not np.isnan(O[e, j]) and not np.isnan(prev_close[e, j])
               and O[e, j] < prev_close[e, j] * 1.095]          # L5
        sells = [j for j in hold if j not in keep]
        nprev = max(len(hold), 1)
        for j in sells:
            trades.append((hold[j][0], e - hold[j][1])); del hold[j]
        H = keep + new; n = len(H)
        sw = stock_w if n else 0.0
        val *= 1 - (len(sells) / nprev * stock_w * COST / 2 + (len(new) / n * sw * COST / 2 if n else 0))
        for j in new: hold[j] = [1.0, e]
        P = np.vstack([path(j, e, e2, delist_loss) for j in H]) if n else None
        sv = P.mean(axis=0) if n else np.ones(e2 - e + 2)
        tseq = np.array([tx[e - 1]] + list(tx[e:e2]) + [tx[e2 - 1]]) / tx[e - 1]
        port = val * (sw * sv + (1 - sw) * tseq)
        # 記每日收盤淨值:收盤 e..e2-1 對應 port[1:-1]
        for t, d in enumerate(range(e, e2)):
            idx.append(dates[d]); vals.append(port[t + 1]); nd += 1; expo += n > 0
        for r, j in enumerate(H): hold[j][0] *= P[r, -1]
        val = port[-1]
    for j in hold: trades.append((hold[j][0], endi - hold[j][1]))
    eq = pd.Series(vals, index=pd.to_datetime(idx))
    return eq, trades, expo / max(nd, 1)


def metrics(eq, trades=None, expo=None, bench=None):
    if len(eq) < 30: return None
    r = eq.pct_change().dropna()
    yrs = len(r) / 245
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1
    mdd = (eq / eq.cummax() - 1).min()
    sh = r.mean() / r.std() * math.sqrt(245) if r.std() > 0 else 0
    out = {"年化%": cagr * 100, "最大回撤%": mdd * 100, "夏普": sh}
    if bench is not None:
        m = eq.resample("ME").last().pct_change().dropna() if isinstance(eq.index, pd.DatetimeIndex) else None
    if trades is not None:
        tr = np.array([t[0] - 1 - COST for t in trades]); dd = np.array([t[1] for t in trades])
        w, l = tr[tr > 0], tr[tr <= 0]
        out.update({"勝率%": (tr > 0).mean() * 100 if len(tr) else np.nan,
                    "盈虧比": (w.mean() / -l.mean()) if len(w) and len(l) and l.mean() < 0 else np.nan,
                    "交易數": len(tr), "平均持有天": dd.mean() if len(dd) else np.nan, "暴露%": expo * 100})
    return out


def index_eq(start, end):
    s = taiex[(taiex.index >= start) & (taiex.index < end)].dropna()
    s.index = pd.to_datetime(s.index)
    return s / s.iloc[0]
