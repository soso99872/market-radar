"""Sprint 004 進場時機回測：載入 market-radar 的歷史資料，重建「每一天的起漲雷達名單與星等」。

只讀產品 repo（products/market-radar），不寫任何產品檔案。第一次跑會把矩陣存到暫存資料夾，之後直接讀。
雷達名單的歷史重建規則與 scripts/radar.py build() 相同：
  - 月營收 (y, m) 視為 (y, m+1) 月 11 日起才知道
  - 名單 = 最新已知月份「營收創 12 個月新高且年增 ≥ 30%（或連 2 月 ≥ 20%）」，近 20 日平均成交 ≥ 0.1 億
  - 星等 = A 層（60 日漲 ≥ 20% 且同產業 60 日平均漲 ≥ 15%）5★、B 層（其一）4★、C 層 3★；
           營收減速或外資 20 日大賣各層扣 1★（與 radar.py 相同，最多扣 1）
"""
import os
import pickle
import sys
import tempfile

sys.dont_write_bytecode = True
PROD = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "products", "market-radar", "scripts"))
sys.path.insert(0, PROD)

import json  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import history  # noqa: E402
import radar  # noqa: E402
import signals as S  # noqa: E402

CACHE = os.path.join(tempfile.gettempdir(), "sprint004_entry_cache.pkl")


def load():
    if os.path.exists(CACHE):
        with open(CACHE, "rb") as f:
            return pickle.load(f)
    print("載入歷史資料（第一次較慢）…", file=sys.stderr)
    days = history.load_days()
    F, HI, LO, taiex, names = S.frames(days)
    close = F["close"].astype(float)
    codes = close.columns
    rp = radar.revenue_panels(codes)
    D = {k: radar.to_daily(rp[k], rp["months"], close.index) for k in ("yoy", "yoy3", "good")}
    accel = rp["yoy3"] - rp["yoy3"].shift(3)
    D["accel"] = radar.to_daily(accel, rp["months"], close.index)
    # 每天「最新已知營收月份」是第幾天公布的：公布日（次月 11 日後第一個交易日）
    pdates = pd.to_datetime(close.index)
    pub = pd.Series(np.nan, index=close.index)
    for y, m in rp["months"]:
        i = pdates.searchsorted(pd.Timestamp(y + (m == 12), m % 12 + 1, 11))
        if 0 <= i < len(pdates):
            pub.iloc[i] = i
    pub_i = pub.ffill()
    vyi = F["value"].astype(float) / 1e8
    raw = F["close_raw"].astype(float)
    fo = (F["fo"].astype(float) * raw)   # 外資買賣超金額（元）
    tr = (F["tr"].astype(float) * raw)
    with open(os.path.join(history.ROOT, "data", "profile", "industry.json"), encoding="utf-8") as f:
        ind = json.load(f)
    out = {
        "close": close, "open": F["open"].astype(float), "high": HI.astype(float), "low": LO.astype(float),
        "raw": raw, "vyi": vyi, "chg": F["chg"].astype(float), "fo": fo, "tr": tr, "value": F["value"].astype(float),
        "taiex": taiex, "names": names, "D": D, "pub_i": pub_i, "ind": ind,
        "rev_start": pd.Timestamp(rp["months"][0][0], rp["months"][0][1], 1) + pd.DateOffset(months=13),
    }
    with open(CACHE, "wb") as f:
        pickle.dump(out, f)
    return out


def radar_members(X):
    """回傳 (member 布林矩陣, stars 矩陣)：第 t 天收盤後看得到的雷達名單與星等。"""
    close, vyi, D = X["close"], X["vyi"], X["D"]
    good = D["good"] == 1
    liq = vyi.rolling(20, min_periods=15).mean() >= radar.MIN_VALUE / 3
    usable = pd.Series(pd.to_datetime(close.index) >= X["rev_start"], index=close.index)
    member = good & liq & close.notna() & usable.values[:, None]
    ret60 = close / close.shift(60) - 1
    tradable = vyi >= radar.MIN_VALUE
    g = pd.Series({c: (None if X["ind"].get(c) in radar.MIXED_IND else X["ind"].get(c)) for c in close.columns})
    peer = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    r = ret60.where(tradable)
    for grp, cs in g.dropna().groupby(g.dropna()):
        cols = list(cs.index)
        cnt = r[cols].notna().sum(axis=1)
        m = r[cols].mean(axis=1).where(cnt >= 5) * 100
        peer[cols] = np.repeat(m.values[:, None], len(cols), axis=1)
    mom_ok = ret60 * 100 >= radar.MOM60
    peer_ok = peer >= radar.PEER60
    tier5 = mom_ok & peer_ok
    base = np.where(tier5, 5, np.where(mom_ok | peer_ok, 4, 3))
    fo20 = X["fo"].rolling(20, min_periods=15).sum() / X["value"].rolling(20, min_periods=15).sum() * 100
    trap = (D["accel"] <= radar.DECEL) | (fo20 <= radar.FO_DUMP)
    stars = pd.DataFrame(base - trap.values.astype(int), index=close.index, columns=close.columns).where(member)
    return member, stars


if __name__ == "__main__":
    X = load()
    m, s = radar_members(X)
    print("交易日", len(X["close"]), X["close"].index[0], "~", X["close"].index[-1])
    last = X["close"].index[-1]
    print("最後一天名單", int(m.loc[last].sum()), "檔；4★以上", int((s.loc[last] >= 4).sum()))
    print("每日平均名單檔數", round(m.sum(axis=1)[m.sum(axis=1) > 0].mean(), 1))
