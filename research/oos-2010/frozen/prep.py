"""把 market-radar 的歷史資料轉成矩陣快取。用法:python prep.py <market-radar 資料夾>"""
import os, sys, json, pickle
MR = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("MR_ROOT", r"C:\sideProject\products\market-radar")
sys.path.insert(0, os.path.join(MR, "scripts"))
import history, signals as S, radar

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache.pkl")
days = history.load_days()
F, hi, lo, taiex, names = S.frames(days)
rp = radar.revenue_panels(F["close"].columns)
ind = json.load(open(os.path.join(history.ROOT, "data", "profile", "industry.json"), encoding="utf-8"))
pickle.dump({"F": F, "taiex": taiex, "names": names, "rp": rp, "ind": ind}, open(OUT, "wb"))
print("ok", F["close"].shape, F["close"].index[0], F["close"].index[-1], "營收", rp["months"][0], "~", rp["months"][-1])
