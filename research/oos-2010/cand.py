"""候選改法(非凍結版,用來在『已看過』的資料上做沒壞掉的檢查)。依 PROTOCOL.md,每個候選只多加 1 個條件,參數用標準值。
  A    原規則(凍結 buy.sim)
  C1   大盤濾網・全出:加權指數收盤 < 200 日均線 → 隔天開盤全部賣出,且不買新股(Faber 2007 的 10 個月 ≈ 200 日均線)
  C1b  大盤濾網・只停買:同上條件,只停止買進,手上的照原規則賣
  C2   閒置現金放指數:沒買股票的現金每天跟著加權指數漲跌(指數不含息、換手成本不計)
防偷看:濾網用第 d 天收盤判斷、第 d+1 天開盤動作;200 日均線只用第 d 天(含)以前的指數。
用法:python cand.py <起> <迄>"""
import os, sys, json, types, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
F = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frozen"); sys.path.insert(0, F)
src = open(os.path.join(F, "buy.py"), encoding="utf-8").read()
def sub(s, old, new):
    assert s.count(old) == 1, old; return s.replace(old, new)
src = sub(src, "        for j, v in pos.items():        # 收盤:估值",
          "        if IDLE and d > d0: cash *= TXR[d]\n        for j, v in pos.items():        # 收盤:估值")
src = sub(src, "            if j not in to_sell and d >= lastvalid[j] and lastvalid[j] < N - 1: to_sell.add(j)\n",
          "            if j not in to_sell and d >= lastvalid[j] and lastvalid[j] < N - 1: to_sell.add(j)\n"
          "        if FILTER == 'exit' and not MKT[d]:\n            for j in pos: to_sell.add(j)\n")
src = sub(src, "        if d >= d1: continue\n",
          "        if d >= d1: continue\n        if FILTER and not MKT[d]:\n            buy_next = []; continue\n")
U = types.ModuleType("buy_cand"); U.__file__ = os.path.join(F, "buy.py")
exec(compile(src, "buy_cand", "exec"), U.__dict__)
tx = np.asarray(U.taiex.ffill().values, dtype=float)
ma = pd.Series(tx).rolling(200, min_periods=200).mean().values
U.MKT = ~(tx < ma)                      # 均線還沒有 200 天時不擋
U.TXR = np.r_[1.0, tx[1:] / tx[:-1]]; U.TXR[~np.isfinite(U.TXR)] = 1.0
from bt import metrics, index_eq
a = sys.argv[1] if len(sys.argv) > 1 else "2011-04-01"; b = sys.argv[2] if len(sys.argv) > 2 else "2019-01-01"
out = {"期間": [a, b]}
for lab, filt, idle in (("A", None, False), ("C1 濾網全出", "exit", False), ("C1b 濾網停買", "entry", False), ("C2 現金放指數", None, True)):
    U.MOM, U.FILTER, U.IDLE = 20, filt, idle
    e, t, x = U.sim(timing="brk", exit_k=4, start=a, end=b)
    yr = e.resample("YE").last()
    out[lab] = {"指標": {k: round(float(v), 2) for k, v in metrics(e, t, x).items()},
                "逐年%": {str(k.year): round(float(v), 1) for k, v in ((yr / yr.shift(1).fillna(1) - 1) * 100).items()}}
ie = index_eq(a, b)
out["加權指數"] = {"指標": {k: round(float(v), 2) for k, v in metrics(ie).items()}}
print(json.dumps(out, ensure_ascii=False, indent=1))
