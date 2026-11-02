"""前進觀察(紙上交易,凍結,依 oos-pre2010/PROTOCOL.md 第五筆)。
2026-11-02 起,用凍結規則記錄 A(原規則)和 C1(大盤濾網・全出)。規則改動和 exam_pre.py 一字不差;
這支只多做一件事:把期末持股抄出來(不影響買賣)。
判定(事先定好,滿 12 個月才判):年化與夏普都贏加權指數(不含息),而且年化贏 0050 含息報酬。
用法:python forward.py [0050含息報酬 json]"""
import os, sys, json, types, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
START = "2026-11-02"
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
src = sub(src, "    s = pd.Series([x[1] for x in eq]",            # 只抄出期末持股
          "    globals()['LAST'] = ({j: dict(v) for j, v in pos.items()}, set(to_sell), d1)\n    s = pd.Series([x[1] for x in eq]")
U = types.ModuleType("buy_fwd"); U.__file__ = os.path.join(F, "buy.py")
exec(compile(src, "buy_fwd", "exec"), U.__dict__)
tx = np.asarray(U.taiex.ffill().values, dtype=float)
ma = pd.Series(tx).rolling(200, min_periods=200).mean().values
U.MKT = ~(tx < ma); U.TXR = np.r_[1.0, tx[1:] / tx[:-1]]; U.TXR[~np.isfinite(U.TXR)] = 1.0
U.IDLE, U.LIM, U.MOM = False, 1.095, 20
names = U.D.get("names", {}) if hasattr(U, "D") else {}

def stats(e):
    """累積、最大回撤;滿 245 個交易日才算年化和夏普。"""
    r = e.pct_change().dropna()
    o = {"交易日": int(len(e)), "累積%": round((e.iloc[-1] / e.iloc[0] - 1) * 100, 2),
         "最大回撤%": round(float((e / e.cummax() - 1).min() * 100), 2)}
    if len(r) >= 245:
        o["年化%"] = round(((e.iloc[-1] / e.iloc[0]) ** (245 / len(r)) - 1) * 100, 2)
        o["夏普"] = round(float(r.mean() / r.std() * np.sqrt(245)), 2) if r.std() > 0 else 0.0
    return o

if not any(x >= START for x in U.dates):
    print(json.dumps({"起": START, "狀態": "還沒有 2026-11-02 以後的資料"}, ensure_ascii=False)); sys.exit()
ie = U.index_eq(START, "2100-01-01")
out = {"起": START, "資料到": U.dates[-1], "加權指數(不含息)": stats(ie),
       "月報酬%": {"加權指數": {k.strftime("%Y-%m"): round(float(v) * 100, 2) for k, v in
                              ie.resample("ME").last().pct_change().fillna(ie.resample("ME").last().iloc[0] - 1).items()}}}
if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
    out["0050 含息"] = json.load(open(sys.argv[1], encoding="utf-8"))
for lab, filt in (("A 原規則", None), ("C1 大盤濾網・全出", "exit")):
    U.FILTER = filt
    e, t, x = U.sim(timing="brk", exit_k=4, start=START)
    pos, ts, d1 = U.LAST
    m = e.resample("ME").last()
    out["月報酬%"][lab] = {k.strftime("%Y-%m"): round(float(v) * 100, 2) for k, v in m.pct_change().fillna(m.iloc[0] - 1).items()}
    st = stats(e); st["已平倉筆數"] = len(t) - len(pos); st["持股比例%"] = round(x * 100, 1)
    st["大盤在 200 日線上"] = bool(U.MKT[d1])
    st["期末持股"] = [{"代號": U.codes[j], "名稱": names.get(U.codes[j], ""), "買進日": U.dates[v["e"]],
                     "買價": round(float(v["entry"]), 2), "收盤": round(float(v["last"]), 2),
                     "報酬%": round((v["last"] / v["entry"] - 1) * 100, 1), "明天開盤賣": j in ts}
                    for j, v in sorted(pos.items(), key=lambda kv: kv[1]["e"])]
    out[lab] = st
months = len(out["月報酬%"]["加權指數"])
if months < 12:
    out["判定"] = f"觀察中(第 {months} 個月,滿 12 個月才判)"
else:
    im, b = out["加權指數(不含息)"], out.get("0050 含息", {}).get("年化%")
    out["判定"] = {lab: ("通過" if out[lab]["年化%"] > im["年化%"] and out[lab]["夏普"] > im["夏普"]
                         and b is not None and out[lab]["年化%"] > b else "沒通過") for lab in ("A 原規則", "C1 大盤濾網・全出")}
print(json.dumps(out, ensure_ascii=False, indent=1))
