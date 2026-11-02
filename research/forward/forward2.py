"""前進觀察第二批（2026-11-03 起，見 research/compare/PROTOCOL.md 第二筆）：多策略比較照事先登記的標準選出的前 2 名。
D1：brk 進場、抱 60 天出場、大盤跌破 200 日線全出、5 檔
D2：brk 進場、星等 < 4 或從高點回落 15% 出場、大盤跌破 200 日線停買、5 檔
規則用 research/compare/compare.py 的 sim（跟凍結程式 A 逐日一致已驗證），判定標準跟第一批一樣。
用法：python forward2.py [0050含息報酬 json]"""
import os, sys, json, warnings; warnings.filterwarnings("ignore")
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "compare"))
import compare as K
from bt import index_eq
START = "2026-11-03"
VERSIONS = {"D1 突破／抱60天／大盤全出／5檔": ("brk", "hold60", "exit", 5), "D2 突破／星等或回落15%／大盤停買／5檔": ("brk", "trail", "entry", 5)}
names = K.U.D.get("names", {})
def stats(e):
    r = e.pct_change().dropna()
    o = {"交易日": int(len(e)), "累積%": round((e.iloc[-1] / e.iloc[0] - 1) * 100, 2), "最大回撤%": round(float((e / e.cummax() - 1).min() * 100), 2)}
    if len(r) >= 245:
        o["年化%"] = round(((e.iloc[-1] / e.iloc[0]) ** (245 / len(r)) - 1) * 100, 2)
        o["夏普"] = round(float(r.mean() / r.std() * np.sqrt(245)), 2) if r.std() > 0 else 0.0
    return o
if sum(x >= START for x in K.dates) < 2:
    print(json.dumps({"起": START, "狀態": "2026-11-03 以後的資料還不到兩天"}, ensure_ascii=False)); sys.exit()
ie = index_eq(START, "2100-01-01")
out = {"起": START, "資料到": K.dates[-1], "加權指數(不含息)": stats(ie)}
if len(sys.argv) > 1 and os.path.exists(sys.argv[1]): out["0050 含息(從 11/02 起算)"] = json.load(open(sys.argv[1], encoding="utf-8"))
for lab, args in VERSIONS.items():
    e, t, x = K.sim(*args, start=START)
    pos, ts, d1 = K.LAST
    st = stats(e); st["已平倉筆數"] = len(t) - len(pos); st["持股比例%"] = round(x * 100, 1); st["大盤在 200 日線上"] = bool(K.MKT[d1])
    st["期末持股"] = [{"代號": K.U.codes[j], "名稱": names.get(K.U.codes[j], ""), "買進日": K.dates[v["e"]], "買價": round(float(v["entry"]), 2),
                     "收盤": round(float(v["last"]), 2), "報酬%": round((v["last"] / v["entry"] - 1) * 100, 1), "明天開盤賣": j in ts}
                    for j, v in sorted(pos.items(), key=lambda kv: kv[1]["e"])]
    out[lab] = st
print(json.dumps(out, ensure_ascii=False, indent=1))
