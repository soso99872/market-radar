"""前進觀察第三批（2026-11-04 起，見 research/others/PROTOCOL.md 第一筆）：台股常用策略裡照事先登記的標準入選的 2 個。
E1：52 週新高接近度（收盤 ÷ 52 週最高價最高 30 檔，月換）
E2：三因子（營收動能池內，營收年增、60 日動能、60 日低波動百分位相加，40 檔，月換）
規則用 research/others/strategies.py 的 STRATS 和 sim，判定標準跟第一批一樣。
用法：python forward3.py [0050含息報酬 json]"""
import os, sys, json, warnings; warnings.filterwarnings("ignore")
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "others"))
import strategies as S
from bt import index_eq
START = "2026-11-04"
VERSIONS = {"E1 52 週新高接近度": "52 週新高接近度", "E2 三因子（營收、動能、低波）": "三因子（營收、動能、低波）"}
names = S.U.D.get("names", {})
def stats(e):
    r = e.pct_change().dropna()
    o = {"交易日": int(len(e)), "累積%": round((e.iloc[-1] / e.iloc[0] - 1) * 100, 2), "最大回撤%": round(float((e / e.cummax() - 1).min() * 100), 2)}
    if len(r) >= 245:
        o["年化%"] = round(((e.iloc[-1] / e.iloc[0]) ** (245 / len(r)) - 1) * 100, 2)
        o["夏普"] = round(float(r.mean() / r.std() * np.sqrt(245)), 2) if r.std() > 0 else 0.0
    return o
if sum(x >= START for x in S.dates) < 2:
    print(json.dumps({"起": START, "狀態": "2026-11-04 以後的資料還不到兩天"}, ensure_ascii=False)); sys.exit()
ie = index_eq(START, "2100-01-01")
out = {"起": START, "資料到": S.dates[-1], "加權指數(不含息)": stats(ie), "注意": "月換的策略要等第一個換股日（11 號以後）才會買進"}
if len(sys.argv) > 1 and os.path.exists(sys.argv[1]): out["0050 含息(從 11/02 起算)"] = json.load(open(sys.argv[1], encoding="utf-8"))
for lab, key in VERSIONS.items():
    fn, n, every, src = S.STRATS[key]
    e, t, x, cnt = S.sim(fn, n, every, START, "2100-01-01")
    pos, ts, d1 = S.LAST
    st = stats(e); st["換股次數"] = cnt; st["已平倉筆數"] = len(t) - len(pos); st["持股比例%"] = round(x * 100, 1)
    st["期末持股"] = [{"代號": S.codes[j], "名稱": names.get(S.codes[j], ""), "買進日": S.dates[v["e"]], "買價": round(float(v["entry"]), 2),
                     "收盤": round(float(v["last"]), 2), "報酬%": round((v["last"] / v["entry"] - 1) * 100, 1), "明天開盤賣": j in ts}
                    for j, v in sorted(pos.items(), key=lambda kv: kv[1]["e"])]
    out[lab] = st
print(json.dumps(out, ensure_ascii=False, indent=1))
