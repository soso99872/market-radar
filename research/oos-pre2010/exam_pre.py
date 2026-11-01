"""2005-04 ～ 2009-12 一次性考試(凍結,依 PROTOCOL.md)。只輸出指標、逐年報酬、判定。
送考:A(原規則,對照)、C1(大盤濾網・全出)、C1b(大盤濾網・只停買)。C2 沒過 2011–2018 的回撤檢查,不送考。
規則程式:oos-2010/frozen/buy.py(凍結),候選的改動和 oos-2010/cand.py 一字不差。
判定(事先定好):主要 = 年化與夏普都贏加權指數(不含息);次要 = 最大回撤比 A 淺。
敏感度(只參考):漲停門檻 +6.5%。
用法:python exam_pre.py [起 迄](預設 2005-04-01 2010-01-01)"""
import os, sys, json, types, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
F = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "oos-2010", "frozen"); sys.path.insert(0, F)
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
src = sub(src, "o >= pc * 1.095", "o >= pc * LIM")
U = types.ModuleType("buy_exam"); U.__file__ = os.path.join(F, "buy.py")
exec(compile(src, "buy_exam", "exec"), U.__dict__)
tx = np.asarray(U.taiex.ffill().values, dtype=float)
ma = pd.Series(tx).rolling(200, min_periods=200).mean().values
U.MKT = ~(tx < ma)
U.TXR = np.r_[1.0, tx[1:] / tx[:-1]]; U.TXR[~np.isfinite(U.TXR)] = 1.0
U.IDLE = False
from bt import metrics, index_eq
a, b = (sys.argv[1], sys.argv[2]) if len(sys.argv) > 2 else ("2005-04-01", "2010-01-01")
R = lambda m: {k: round(float(v), 2) for k, v in m.items()}
ie = index_eq(a, b); im = R(metrics(ie)); iy = ie.resample("YE").last()
out = {"期間": [a, b], "加權指數(不含息)": {"指標": im, "逐年%": {str(k.year): round(float(v), 1) for k, v in ((iy / iy.shift(1).fillna(1) - 1) * 100).items()}}}
res = {}
for lab, filt in (("A 原規則", None), ("C1 大盤濾網・全出", "exit"), ("C1b 大盤濾網・只停買", "entry")):
    U.MOM, U.FILTER, U.LIM = 20, filt, 1.095
    e, t, x = U.sim(timing="brk", exit_k=4, start=a, end=b)
    yr = e.resample("YE").last(); m = R(metrics(e, t, x)); res[lab] = m
    U.LIM = 1.065
    e2, t2, x2 = U.sim(timing="brk", exit_k=4, start=a, end=b); m2 = R(metrics(e2, t2, x2))
    out[lab] = {"指標": m, "逐年%": {str(k.year): round(float(v), 1) for k, v in ((yr / yr.shift(1).fillna(1) - 1) * 100).items()},
                "敏感度 漲停+6.5%": {k: m2[k] for k in ("年化%", "最大回撤%", "夏普")}}
for lab, m in res.items():
    main = m["年化%"] > im["年化%"] and m["夏普"] > im["夏普"]
    out[lab]["判定"] = {"主要(年化與夏普都贏指數)": "通過" if main else "沒通過",
                       "次要(回撤比 A 淺)": None if lab.startswith("A") else ("是" if m["最大回撤%"] > res["A 原規則"]["最大回撤%"] else "否")}
print(json.dumps(out, ensure_ascii=False, indent=1))
