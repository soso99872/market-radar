"""飆股起漲前的共同特徵(研究用,不在每日排程裡跑)。

問題:營收大爆發的股票,有的股價跟著飆(騰輝),有的不動或已經漲完(群聯 2026 年營收年增 300% 但股價持平)。
起漲前、或起漲初期還有大空間的股票,事前看得出什麼共同點?哪些看起來很好、其實是陷阱?

做法(全部只用當時已知的資料):
  樣本   每個月營收公告日(次月 11 日後第一個交易日),所有當天成交 ≥ 0.3 億的股票
  結果   隔天開盤進場後 120 個交易日內最高漲幅 ≥ 100%(飆股)、≥ 50%(大漲);60 日報酬比一般股
  特徵   營收(年增、加速、轉正、創新高)、毛利率變化、股價位置(已漲多少、離底部多遠、整理多緊)、
         量能、法人、本益比相對自身歷史、市值、同產業是否一起轉強
  1. 單一特徵:五等分後各組的飆股比例(以全體樣本比例為 1 倍)
  2. 陷阱:營收動能名單裡,哪些特徵讓結果變差
  3. 組合規則:用 2019–2022 決定規則,2023 年後當樣本外檢驗;
     與「只看營收」比較抓到的飆股比例、每檔的平均表現、中途虧損
  4. 案例:騰輝、國巨、群聯等,以及每一段翻倍行情,規則在什麼價位、哪一天會列入
股價已還原分割與減資(signals.frames),報酬扣交易成本。

用法:python scripts/explosion_study.py > 報告.txt   (另寫 data/radar/explosion.json 給網頁)
"""
import json
import math
import os
import sys

import numpy as np
import pandas as pd

import history
import margin
import radar
import signals as S
import valuation

H_MAX, H_RET = 120, 60
OUT = os.path.join(history.ROOT, "data", "radar", "explosion.json")
SPLIT = "2023-01-01"     # 之前定規則,之後當樣本外
CASES = ["6672", "2327", "8299"]


def industries():
    out, cap = {}, {}
    for url, kc, ki, kp in (("https://openapi.twse.com.tw/v1/opendata/t187ap03_L", "公司代號", "產業別", "已發行普通股數或TDR原股發行股數"),
                            ("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O", "SecuritiesCompanyCode",
                             "SecuritiesIndustryCode", "IssueShares")):
        try:
            rows = history.get(url)   # 失敗會重試
        except Exception as e:  # noqa: BLE001
            print("industry fetch failed", url, e, file=sys.stderr)
            continue
        for r in rows:
            c = str(r.get(kc, "")).strip()
            out[c] = str(r.get(ki, "")).strip()
            v = history.num(r.get(kp, ""))
            if v:
                cap[c] = v
    try:   # 產業別以每日排程存下的檔案為準(與雷達一致)
        with open(os.path.join(history.ROOT, "data", "profile", "industry.json"), encoding="utf-8") as f:
            out.update(json.load(f))
    except (OSError, ValueError):
        pass
    return out, cap


print("載入歷史資料…", file=sys.stderr)
days = history.load_days()
F, HI, LO, taiex, names = S.frames(days)
close, opn, raw = F["close"], F["open"], F["close_raw"]
vyi = F["value"] / 1e8
dates = list(close.index)
codes = list(close.columns)
N, M = len(dates), len(codes)
rp = radar.revenue_panels(close.columns)
months = rp["months"]
pdates = pd.to_datetime(close.index)
C, O, V, RAW = close.values, opn.values, vyi.values, raw.values

pub_i = []
for y, m in months:
    i = int(pdates.searchsorted(pd.Timestamp(y + (m == 12), m % 12 + 1, 11)))
    if 260 <= i < N:   # 要有一年股價歷史
        pub_i.append(i)
pub_i = sorted(set(pub_i))


def daily(panel):
    return radar.to_daily(panel, months, close.index).values


# ---- 營收特徵(月資料 → 公告後可用) ----
yoy, rev = rp["yoy"], rp["rev"]
yoy3 = rp["yoy3"]
f_rev = {
    "營收年增": daily(yoy),
    "近3月年增": daily(yoy3),
    "年增加速": daily(yoy3 - yoy3.shift(3)),                        # 近 3 月平均年增,比 3 個月前多幾個百分點
    "連續創新高月數": daily(rp["streak"].astype(float)),
    "營收距3年高": daily(rev / rev.shift(1).rolling(36, min_periods=24).max() * 100 - 100),
    "半年前年增": daily(yoy3.shift(6)),                              # 低基期:半年前還在衰退
}
GOOD = daily(rp["good"].astype(float)) == 1

# ---- 股價、量能、法人 ----
ma60 = close.rolling(60, min_periods=40).mean()
ma250 = close.rolling(250, min_periods=200).mean()
r1 = close.pct_change()
f_px = {
    "60日漲幅": (close / close.shift(60) - 1) * 100,
    "120日漲幅": (close / close.shift(120) - 1) * 100,
    "距52週高": (close / close.rolling(250, min_periods=200).max() - 1) * 100,
    "距1年低點": (close / close.rolling(250, min_periods=200).min() - 1) * 100,
    "離季線": (close / ma60 - 1) * 100,
    "離年線": (close / ma250 - 1) * 100,
    "60日區間寬度": (close.rolling(60, min_periods=40).max() / close.rolling(60, min_periods=40).min() - 1) * 100,
    "波動收縮": r1.rolling(20, min_periods=15).std() / r1.rolling(120, min_periods=80).std(),
    "量能放大": vyi.rolling(20, min_periods=15).mean() / vyi.rolling(120, min_periods=80).mean(),
    "成交金額": vyi.rolling(20, min_periods=15).mean(),
}
money = lambda k: (F[k] * raw).rolling(20, min_periods=15).sum() / F["value"].rolling(20, min_periods=15).sum() * 100   # noqa: E731
f_px["投信20日買超佔成交"] = money("tr")
f_px["外資20日買超佔成交"] = money("fo")
f_px = {k: v.values for k, v in f_px.items()}

IND, CAP = industries()
ind = np.array([IND.get(c, "") for c in codes])
shares = np.array([CAP.get(c, np.nan) for c in codes])   # 目前的發行股數,套用到過去(股本變動會有誤差)
f_px["市值(億)"] = RAW * shares[None, :] / 1e8

# 同產業一起轉強:同產業(證交所產業別)可交易股票中,近 3 月營收年增 ≥ 20% 的比例、同產業 60 日平均漲幅
yy3, r60 = f_rev["近3月年增"], f_px["60日漲幅"]
peer_rev = np.full((N, M), np.nan)
peer_px = np.full((N, M), np.nan)
groups = {g: np.where(ind == g)[0] for g in set(ind) if g and g not in radar.MIXED_IND}   # 綜合、其他不算同產業
for i in pub_i:
    ok = V[i] >= radar.MIN_VALUE
    for g, js in groups.items():
        jj = js[ok[js] & ~np.isnan(yy3[i, js])]
        if len(jj) < 5:
            continue
        peer_rev[i, js] = (yy3[i, jj] >= 20).mean() * 100
        peer_px[i, js] = np.nanmean(r60[i, jj])

# ---- 毛利率(申報期限日才算已知) ----
cum = margin.load()
periods = sorted({p for v in cum.values() for p in v})
gm = {c: {p: g / r * 100 for p, (r, g) in margin.quarterly(v).items() if r and r > 0 and abs(g / r) <= 1} for c, v in cum.items()}
dgm = np.full((N, M), np.nan)
for i in pub_i:
    known = [p for p in periods if margin.available(p) <= dates[i]]
    if not known:
        continue
    p = known[-1]
    py = "%d%s" % (int(p[:4]) - 1, p[4:])
    for j, c in enumerate(codes):
        g = gm.get(c)
        if g and p in g and py in g:
            dgm[i, j] = g[p] - g[py]

# ---- 本益比相對自身過去 36 個月中位數 ----
VAL = valuation.load_all()
vm = sorted(VAL)
pe_rel = np.full((N, M), np.nan)
pe_now = np.full((N, M), np.nan)
for i in pub_i:
    d = dates[i]
    cur = [m for m in vm if (m[0], m[1]) < (int(d[:4]), int(d[5:7]))]
    if len(cur) < 24:
        continue
    last, hist = VAL[cur[-1]]["s"], cur[-36:]
    for j, c in enumerate(codes):
        v = (last.get(c) or [None])[0]
        if not v or v <= 0:
            continue
        h = [VAL[m]["s"].get(c, [None])[0] for m in hist]
        h = [x for x in h if x and x > 0]
        if len(h) >= 18:
            pe_now[i, j] = v
            pe_rel[i, j] = v / np.median(h)

FEATS = dict(f_rev)
FEATS.update(f_px)
FEATS["同產業營收轉強比例"] = peer_rev
FEATS["同產業60日漲幅"] = peer_px
FEATS["毛利率年變化"] = dgm
FEATS["本益比相對歷史"] = pe_rel
FEATS["本益比"] = pe_now

# ---- 樣本 ----
rows = []
for i in pub_i:
    e = i + 1
    if e + H_RET - 1 >= N:
        continue
    ok = (V[i] >= radar.MIN_VALUE) & ~np.isnan(O[e]) & ~np.isnan(C[i])
    end = min(N, e + H_MAX)
    mx = np.nanmax(C[e:end], axis=0) / O[e] - 1
    f60 = C[e + H_RET - 1] / O[e] - 1 - S.COST
    mn60 = np.nanmin(C[e:e + H_RET], axis=0) / O[e] - 1
    okf = ok & ~np.isnan(f60)
    if okf.sum() < 100:
        continue
    bench = np.nanmean(f60[okf])
    full = end - e == H_MAX
    for j in np.where(ok)[0]:
        r = [i, dates[i], codes[j], bool(GOOD[i, j]), mx[j], f60[j], f60[j] - bench if okf[j] else np.nan, mn60[j], full]
        r += [FEATS[k][i, j] for k in FEATS]
        rows.append(r)
R = pd.DataFrame(rows, columns=["i", "date", "code", "rev", "max120", "ret60", "x60", "min60", "full"] + list(FEATS))
R["飆股"] = R.max120 >= 1.0
R["大漲"] = R.max120 >= 0.5
R["重挫"] = R.min60 <= -0.25
ALL = R                  # 案例用(含最近還沒走完 120 日的)
R = R[R.full].copy()     # 統計只用走完 120 日的樣本,不然最近幾個月只有已翻倍的會被算進來
print("樣本 %d 筆,%s ~ %s,飆股 %.2f%%" % (len(R), R.date.min(), R.date.max(), R["飆股"].mean() * 100), file=sys.stderr)

out = {"span": [R.date.min(), R.date.max()], "n": int(len(R)), "base": {}, "feats": {}, "traps": {}, "rules": {}, "cases": {}}
base_all = R["飆股"].mean()
base_rev = R[R.rev]["飆股"].mean()
out["base"] = {"all": round(base_all * 100, 2), "rev": round(base_rev * 100, 2), "n_rev": int(R.rev.sum()),
               "big_all": round(R["大漲"].mean() * 100, 1), "big_rev": round(R[R.rev]["大漲"].mean() * 100, 1)}

print("=" * 110)
print("飆股起漲前特徵研究  %s ~ %s  樣本 %d(營收動能名單 %d)" % (R.date.min(), R.date.max(), len(R), R.rev.sum()))
print("飆股 = 進場後 120 個交易日內最高漲 ≥ 100%%。全體 %.2f%%,營收動能名單 %.2f%%(%.1f 倍)" % (
    base_all * 100, base_rev * 100, base_rev / base_all))
print("=" * 110)


def q_table(df, k, base, label):
    d = df[df[k].notna()]
    if len(d) < 500:
        return None
    try:
        q = pd.qcut(d[k].rank(method="first"), 5, labels=False)
    except ValueError:
        return None
    res = []
    for b in range(5):
        s = d[q == b]
        res.append({"lo": round(float(s[k].min()), 2), "hi": round(float(s[k].max()), 2), "n": int(len(s)),
                    "hit": round(s["飆股"].mean() * 100, 2), "lift": round(s["飆股"].mean() / base, 2),
                    "big": round(s["大漲"].mean() * 100, 1), "x60": round(s.x60.mean() * 100, 2),
                    "crash": round(s["重挫"].mean() * 100, 1)})
    return res


def show(tab, k):
    spread = tab[-1]["lift"] - tab[0]["lift"]
    print("\n  %s(倍數 = 該組飆股比例 ÷ 整體;最高組 − 最低組 %+.2f)" % (k, spread))
    for b, t in enumerate(tab):
        print("    Q%d %10.1f ~ %-10.1f 飆股 %5.2f%% (%4.2f 倍)  大漲 %4.1f%%  60日比一般股 %+6.2f%%  60日內曾跌25%% %4.1f%%" % (
            b + 1, t["lo"], t["hi"], t["hit"], t["lift"], t["big"], t["x60"], t["crash"]))


for scope, df, base in (("全部股票", R, base_all), ("營收動能名單內", R[R.rev], base_rev)):
    print("\n[%s · 單一特徵五等分]" % scope)
    out["feats"][scope] = {}
    for k in FEATS:
        tab = q_table(df, k, base, scope)
        if tab:
            out["feats"][scope][k] = tab
            show(tab, k)

# ---- 陷阱:營收動能名單內,哪些狀況之後明顯比較差 ----
L = R[R.rev]
TRAPS = {
    "股價已漲 1 倍以上(120 日)": L["120日漲幅"] >= 100,
    "股價已漲 50% 以上(60 日)": L["60日漲幅"] >= 50,
    "離季線 +40% 以上": L["離季線"] >= 40,
    "本益比高於自身歷史 2 倍": L["本益比相對歷史"] >= 2,
    "低基期反彈(半年前年增 < −20%)": L["半年前年增"] < -20,
    "年增減速(近 3 月比 3 月前少 20pp 以上)": L["年增加速"] <= -20,
    "毛利率下降 3pp 以上": L["毛利率年變化"] <= -3,
    "市值 1000 億以上": L["市值(億)"] >= 1000,
    "法人(外資)20 日大賣": L["外資20日買超佔成交"] <= -10,
    "同產業沒有一起轉強(< 20% 同業成長)": L["同產業營收轉強比例"] < 20,
}
print("\n[營收動能名單 · 可能的陷阱]  基準:名單整體 飆股 %.2f%%  60日比一般股 %+.2f%%  曾跌25%% %.1f%%" % (
    base_rev * 100, L.x60.mean() * 100, L["重挫"].mean() * 100))
for k, m in TRAPS.items():
    a, b = L[m], L[~m & m.notna()]
    if len(a) < 50:
        continue
    out["traps"][k] = {"n": int(len(a)), "hit": round(a["飆股"].mean() * 100, 2), "hit_other": round(b["飆股"].mean() * 100, 2),
                       "x60": round(a.x60.mean() * 100, 2), "x60_other": round(b.x60.mean() * 100, 2),
                       "crash": round(a["重挫"].mean() * 100, 1), "crash_other": round(b["重挫"].mean() * 100, 1)}
    t = out["traps"][k]
    print("  %-34s n=%5d  飆股 %5.2f%% (其他 %5.2f%%)  60日比一般股 %+6.2f%% (其他 %+6.2f%%)  曾跌25%% %4.1f%% (其他 %4.1f%%)" % (
        k, t["n"], t["hit"], t["hit_other"], t["x60"], t["x60_other"], t["crash"], t["crash_other"]))


# ---- 組合規則:在 2019–2022 選規則,2023 起樣本外 ----
def nw(series):
    s = series.dropna().values
    return round(float(S.nw_t(s, 3)), 2) if len(s) > 12 else None


def evaluate(mask, df):
    d = df[mask & mask.notna()]
    if len(d) < 30:
        return {"n": int(len(d))}
    caught = d[d["飆股"]].code.nunique()
    coh = d.groupby("i").x60.mean()
    return {"n": int(len(d)), "per_month": round(len(d) / df.i.nunique(), 1), "hit": round(d["飆股"].mean() * 100, 2),
            "big": round(d["大漲"].mean() * 100, 1), "x60": round(d.x60.mean() * 100, 2),
            "med60": round(d.ret60.median() * 100, 2), "crash": round(d["重挫"].mean() * 100, 1),
            "t": nw(coh), "stocks_caught": int(caught)}


def rule(df, early=True, theme=True, room=True, pe=True):
    m = df.rev.copy()
    if early:    # 起漲初期:還沒漲太多
        m &= (df["120日漲幅"] < 100) & (df["離季線"] < 40)
    if room:     # 營收正在加速,而不是減速
        m &= df["年增加速"].fillna(0) > 0
    if theme:    # 同產業也在轉強(題材)
        m &= df["同產業營收轉強比例"].fillna(0) >= 20
    if pe:       # 評價還沒被炒到天上
        m &= df["本益比相對歷史"].fillna(1) < 2
    return m


IS, OOS = R[R.date < SPLIT], R[R.date >= SPLIT]
variants = {
    "全部股票": lambda d: pd.Series(True, index=d.index),
    "只看營收(目前的起漲雷達)": lambda d: d.rev,
    "營收 + 起漲初期": lambda d: rule(d, True, False, False, False),
    "營收 + 加速": lambda d: rule(d, False, False, True, False),
    "營收 + 同產業轉強": lambda d: rule(d, False, True, False, False),
    "營收 + 起漲初期 + 加速": lambda d: rule(d, True, False, True, False),
    "營收 + 起漲初期 + 加速 + 同產業": lambda d: rule(d, True, True, True, False),
    "營收 + 起漲初期 + 加速 + 同產業 + 評價": lambda d: rule(d, True, True, True, True),
}
print("\n[組合規則]  規則依 2019–2022 的結果決定,2023 年後是樣本外")
for k, fn in variants.items():
    a, b = evaluate(fn(IS), IS), evaluate(fn(OOS), OOS)
    out["rules"][k] = {"is": a, "oos": b}
    for tag, s in (("2019–22", a), ("2023– ", b)):
        if "hit" not in s:
            print("  %-30s %s 樣本不足 n=%d" % (k, tag, s["n"]))
            continue
        print("  %-30s %s 每月 %5.1f 檔  飆股 %5.2f%%  大漲 %4.1f%%  60日比一般股 %+6.2f%%  中位 %+6.2f%%  曾跌25%% %4.1f%%  t=%s" % (
            k, tag, s["per_month"], s["hit"], s["big"], s["x60"], s["med60"], s["crash"], s["t"]))

# ---- 第一次列入 vs 已經列入很久(群聯 2026 年那種:營收還在爆發,但股價早已反映) ----
# 本輪連續列入的第一個月股價 → 現在已漲多少
R = R.sort_values(["code", "i"])
ALL = ALL.sort_values(["code", "i"])
for df in (R, ALL):
    first_px, months_on, since = [], [], []
    last_code, start_px, n_on, prev_i = None, None, 0, None
    pos = {d: k for k, d in enumerate(pub_i)}
    for r in df.itertuples():
        if not r.rev:
            first_px.append(np.nan); months_on.append(0); since.append(np.nan)
            if r.code == last_code:
                n_on = 0
            continue
        k = pos[r.i]
        cont = r.code == last_code and n_on > 0 and prev_i is not None and pos[prev_i] == k - 1
        if not cont:
            start_px, n_on = C[r.i, codes.index(r.code)], 0
        n_on += 1
        months_on.append(n_on)
        since.append((C[r.i, codes.index(r.code)] / start_px - 1) * 100)
        first_px.append(start_px)
        last_code, prev_i = r.code, r.i
    df["連續列入月數"] = months_on
    df["列入後已漲"] = since
IS, OOS = R[R.date < SPLIT], R[R.date >= SPLIT]
L = R[R.rev]
print("\n[營收動能名單 · 第一次列入 vs 已經列入很久]")
out["streak"] = {}
for k, m in (("第 1 個月(新列入)", L["連續列入月數"] == 1), ("第 2–3 個月", L["連續列入月數"].between(2, 3)),
             ("第 4 個月以上", L["連續列入月數"] >= 4),
             ("列入後已漲 < 30%", L["列入後已漲"] < 30), ("列入後已漲 30–100%", L["列入後已漲"].between(30, 100)),
             ("列入後已漲 > 100%", L["列入後已漲"] > 100)):
    for tag, d in (("2019–22", L[m & (L.date < SPLIT)]), ("2023– ", L[m & (L.date >= SPLIT)])):
        s = evaluate(pd.Series(True, index=d.index), d)
        out["streak"].setdefault(k, {})[tag.strip()] = s
        if "hit" in s:
            print("  %-20s %s n=%5d  飆股 %5.2f%%  大漲 %4.1f%%  60日比一般股 %+6.2f%%  中位 %+6.2f%%  曾跌25%% %4.1f%%" % (
                k, tag, s["n"], s["hit"], s["big"], s["x60"], s["med60"], s["crash"]))

# ---- 營收 + 題材 + 動能:三者都有才列入 ----
mom = lambda d: d["60日漲幅"] >= 20                    # noqa: E731  股價已經開始動
peer = lambda d: d["同產業60日漲幅"] >= 15               # noqa: E731  同產業股價也在漲(題材發酵)
fresh = lambda d: d["列入後已漲"].fillna(0) < 100         # noqa: E731  這一輪列入後還沒漲超過一倍
nofo = lambda d: d["外資20日買超佔成交"].fillna(0) > -10  # noqa: E731  外資沒有大賣
combos = {
    "營收 + 動能": lambda d: d.rev & mom(d),
    "營收 + 同產業股價強": lambda d: d.rev & peer(d),
    "營收 + 動能 + 同產業股價強": lambda d: d.rev & mom(d) & peer(d),
    "營收 + 動能 + 同產業 + 列入後未漲 1 倍": lambda d: d.rev & mom(d) & peer(d) & fresh(d),
    "營收 + 動能 + 同產業 + 未漲 1 倍 + 外資沒大賣": lambda d: d.rev & mom(d) & peer(d) & fresh(d) & nofo(d),
}
print("\n[營收 + 題材 + 動能]")
for k, fn in combos.items():
    a, b = evaluate(fn(IS), IS), evaluate(fn(OOS), OOS)
    out["rules"][k] = {"is": a, "oos": b}
    for tag, s in (("2019–22", a), ("2023– ", b)):
        if "hit" in s:
            print("  %-34s %s 每月 %5.1f 檔  飆股 %5.2f%%  大漲 %4.1f%%  60日比一般股 %+6.2f%%  中位 %+6.2f%%  曾跌25%% %4.1f%%  t=%s" % (
                k, tag, s["per_month"], s["hit"], s["big"], s["x60"], s["med60"], s["crash"], s["t"]))
variants.update(combos)

# ---- 案例與召回:每段翻倍行情,規則第一次列入是在漲了多少的時候 ----
best = variants["營收 + 動能 + 同產業 + 未漲 1 倍 + 外資沒大賣"]
for df in (R, ALL):
    df["pick"] = best(df)
    df["rev_only"] = df.rev


def first_flag(code, col, start, stop):
    d = R[(R.code == code) & R[col] & (R.date >= start) & (R.date <= stop)]
    return d.iloc[0] if len(d) else None


print("\n[案例]")
for code in CASES:
    j = codes.index(code)
    s = pd.Series(C[:, j], index=dates)
    out["cases"][code] = {"name": names.get(code, code), "flags": []}
    print("  %s %s" % (code, names.get(code, code)))
    for col, label in (("rev_only", "只看營收"), ("pick", "組合規則")):
        d = ALL[(ALL.code == code) & ALL[col]]
        hist = [(r.date, round(float(s[r.date]), 1), round(r.max120 * 100), round(r.x60 * 100, 1) if not np.isnan(r.x60) else None)
                for r in d.itertuples()]
        out["cases"][code]["flags"].append({"rule": label, "hits": hist[-12:]})
        print("    %s:%s" % (label, "、".join("%s @%s(之後120日最高 %+d%%)" % (h[0][2:], h[1], h[2]) for h in hist[-10:]) or "從未列入"))

# 所有「低點起 120 日內翻倍」的波段(同 recall.py 定義),在波段前 1/3 漲幅內被列入的比例
eps = []
for j, c in enumerate(codes):
    a = C[:, j]
    i = 260
    while i < N - 1:
        if np.isnan(a[i]):
            i += 1
            continue
        w = a[i:i + 121]
        k = int(np.nanargmax(w))
        if w[k] >= 2 * a[i] and a[i] == np.nanmin(a[max(0, i - 20):i + 1]) and np.nanmean(V[max(0, i - 20):i + 1, j]) >= 0.05:
            eps.append((c, i, i + k, a[i], w[k]))
            i = i + k + 1
        else:
            i += 1
print("\n[召回] 低點起 120 日內翻倍的波段 %d 段" % len(eps))
out["recall"] = {"episodes": len(eps)}


def recall_of(col):
    flagged = R[R[col]]
    by = {c: g for c, g in flagged.groupby("code")}
    early = caught = 0
    gains_at, left = [], []
    for c, tr, pk, lo_, hi_ in eps:
        g = by.get(c)
        if g is None:
            continue
        w = g[(g.i >= tr - 40) & (g.i <= pk)]   # 起漲前兩個月內到高點之間
        if not len(w):
            continue
        caught += 1
        q = int(w.i.iloc[0])
        p = C[q, codes.index(c)]
        at = p / lo_ - 1
        gains_at.append(at)
        left.append(hi_ / p - 1)
        if at <= (hi_ / lo_ - 1) / 3:
            early += 1
    return {"caught": round(caught / len(eps) * 100, 1), "early": round(early / len(eps) * 100, 1),
            "at_med": round(float(np.median(gains_at)) * 100) if gains_at else None,
            "left_med": round(float(np.median(left)) * 100) if left else None,
            "per_month": round(flagged.groupby("i").size().mean(), 1) if len(flagged) else 0}


for col, label in (("rev_only", "只看營收"), ("pick", "組合規則")):
    out["recall"][label] = v = recall_of(col)
    print("  %-8s 抓到 %4.1f%% 的波段,其中在前 1/3 漲幅內就列入 %4.1f%%;列入時已漲中位數 %s%%、之後還剩中位數 %s%%;平均每月名單 %s 檔" % (
        label, v["caught"], v["early"], v["at_med"], v["left_med"], v["per_month"]))

# ---- 分層:不同邏輯各自列入,畫面上分開標示 ----
# A 三項都有  B 營收 + 動能或題材其一  C 只有營收(最早期)  D 沒有營收、但動能 + 題材(題材股行情,營收還沒跟上)
TIERS = [("A", "營收＋動能＋題材"), ("B", "營收＋動能或題材其一"), ("C", "只有營收(最早期)"), ("D", "沒有營收,動能＋題材")]
for df in (R, ALL):
    m, p_ = mom(df).fillna(False), peer(df).fillna(False)
    df["tier"] = np.select([df.rev & m & p_, df.rev & (m | p_), df.rev, ~df.rev & m & p_], ["A", "B", "C", "D"], "")
print("\n[分層]  同一檔只會落在一層;累計 = 由上往下合起來抓到的翻倍波段比例")
out["tiers"] = []
acc = set()
for k, label in TIERS:
    IS_t, OOS_t = R[R.date < SPLIT], R[R.date >= SPLIT]
    a, b = evaluate(IS_t.tier == k, IS_t), evaluate(OOS_t.tier == k, OOS_t)
    acc.add(k)
    R["_acc"] = R.tier.isin(acc)
    R["_one"] = R.tier == k
    one, cum_ = recall_of("_one"), recall_of("_acc")
    out["tiers"].append({"tier": k, "label": label, "is": a, "oos": b, "recall": one, "recall_cum": cum_})
    for tag, s in (("2019–22", a), ("2023– ", b)):
        if "hit" in s:
            print("  %s %-18s %s 每月 %5.1f 檔  飆股 %5.2f%%  大漲 %4.1f%%  60日比一般股 %+6.2f%%  中位 %+6.2f%%  曾跌25%% %4.1f%%  t=%s" % (
                k, label, tag, s["per_month"], s["hit"], s["big"], s["x60"], s["med60"], s["crash"], s["t"]))
    print("    單層抓到 %4.1f%% 波段(列入時已漲 %s%%、之後剩 %s%%);累計 %4.1f%%" % (one["caught"], one["at_med"], one["left_med"], cum_["caught"]))
R = R.drop(columns=["_acc", "_one"])

def clean(o):
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if math.isnan(o) else float(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


with open(OUT, "w", encoding="utf-8") as fh:
    json.dump(clean(out), fh, ensure_ascii=False, separators=(",", ":"))


# ---- 星等評級:分層 + 陷阱扣分。驗證星等越高、歷史表現越好(單調),才用在網頁 ----
# 5★ A 層沒有陷阱;4★ B 層沒有陷阱,或 A 層有陷阱;3★ C 層(最早期)或 D 層(題材動能、營收未跟上),或 B 層有陷阱;
# 2★ C 層有陷阱;1★ 不在任何名單。C 與 D 都列 3★:D 飆股率較高但 2019–22 平均較差,兩者排序不穩定
def stars(df):
    trap = (df["年增加速"].fillna(0) <= -20) | (df["外資20日買超佔成交"].fillna(0) <= -10)
    base = df.tier.map({"A": 5, "B": 4, "C": 3, "D": 3}).fillna(1)
    s = base - (trap & df.tier.isin(["A", "B", "C"])).astype(int)
    return s.astype(int)


for df in (R, ALL):
    df["stars"] = stars(df)
print("\n[星等]  5★ = A 層無陷阱 … 1★ = 不在任何名單(陷阱:營收減速、外資 20 日大賣)")
out["stars"] = []
for k in (5, 4, 3, 2, 1):
    IS_t, OOS_t = R[R.date < SPLIT], R[R.date >= SPLIT]
    a, b = evaluate(IS_t.stars == k, IS_t), evaluate(OOS_t.stars == k, OOS_t)
    out["stars"].append({"stars": k, "is": a, "oos": b})
    for tag, s in (("2019–22", a), ("2023– ", b)):
        if "hit" in s:
            print("  %d★ %s 每月 %6.1f 檔  飆股 %5.2f%%  大漲 %4.1f%%  60日比一般股 %+6.2f%%  中位 %+6.2f%%  曾跌25%% %4.1f%%  t=%s" % (
                k, tag, s["per_month"], s["hit"], s["big"], s["x60"], s["med60"], s["crash"], s["t"]))
with open(OUT, "w", encoding="utf-8") as fh:
    json.dump(clean(out), fh, ensure_ascii=False, separators=(",", ":"))

# ---- 第三方稽核用:4★ 以上每月一籃(營收公告隔天開盤進場、持有 20 日、扣掉同日一般股),格式同 radar.basket_log ----
import csv  # noqa: E402
rows_b = []
for i in sorted(R.i.unique()):
    e = i + 1
    if e + 19 >= N:
        continue
    f20 = C[e + 19] / O[e] - 1 - S.COST
    ok = (V[i] >= radar.MIN_VALUE) & ~np.isnan(f20)
    picks = [codes.index(c) for c in R[(R.i == i) & (R.stars >= 4)].code]
    picks = [j for j in picks if ok[j]]
    if not picks or ok.sum() < 100:
        continue
    rows_b.append(["籃%s" % dates[i], dates[e], dates[e + 19], int(round(1e6 * (np.mean(f20[picks]) - np.mean(f20[ok])))), "TWD"])
with open(os.path.join(history.ROOT, "data", "track", "basket_backtest_star.csv"), "w", encoding="utf-8", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["代號", "進場時間", "出場時間", "已實現淨損益", "損益幣別"])
    w.writerows(rows_b)
print("\n[稽核用] 4★ 以上每月一籃 %d 筆,平均每籃比一般股 %+.2f%%,月勝率 %.0f%%" % (
    len(rows_b), np.mean([r[3] for r in rows_b]) / 1e4, np.mean([r[3] > 0 for r in rows_b]) * 100))

# 給 accuracy_study.py 用的樣本(不提交)
R.to_pickle(os.path.join(os.environ.get("TEMP", "/tmp"), "mr_samples.pkl"))
