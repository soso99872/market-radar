"""敏感度(非凍結):凍結程式把「開盤漲停買不到」寫成 ≥ 前收 +9.5%,但 2015-06-01 前台股漲跌幅是 7%。
這裡把 2015-06-01 前的門檻改成 +6.5%,其他完全不動,看結果差多少。用法:python limit_check.py [起] [迄]"""
import os, sys, json, types, warnings; warnings.filterwarnings("ignore")
F = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frozen")
sys.path.insert(0, F)
src = open(os.path.join(F, "buy.py"), encoding="utf-8").read()
old = "o >= pc * 1.095"
assert src.count(old) == 1, "找不到漲停判斷"
src = src.replace(old, "o >= pc * (1.065 if d < LIM_SWITCH else 1.095)")
U = types.ModuleType("buy_lim"); U.__file__ = os.path.join(F, "buy.py")
exec(compile(src, "buy_lim", "exec"), U.__dict__)
U.LIM_SWITCH = U.dates.index([x for x in U.dates if x >= "2015-06-01"][0])
from bt import metrics, index_eq
a = sys.argv[1] if len(sys.argv) > 1 else "2011-04-01"; b = sys.argv[2] if len(sys.argv) > 2 else "2019-01-01"
out = {"期間": [a, b], "說明": "2015-06-01 前開盤 ≥ 前收 +6.5% 視為漲停買不到"}
for lab, mo in (("A 動能20%(現行)", 20), ("B 動能10%(逐年前進選的)", 10)):
    U.MOM = mo
    e, t, x = U.sim(timing="brk", exit_k=4, start=a, end=b)
    yr = e.resample("YE").last()
    out[lab] = {"指標": {k: round(float(v), 2) for k, v in metrics(e, t, x).items()},
               "逐年%": {str(k.year): round(float(v), 1) for k, v in ((yr / yr.shift(1).fillna(1) - 1) * 100).items()}}
print(json.dumps(out, ensure_ascii=False, indent=1))
