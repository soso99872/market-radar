"""Sprint 004 進場時機回測：起漲雷達名單內，「今天」符合某進場規則的樣本，之後表現是否比同名單其他天好。

防未來視角：
  - 規則只用第 t 天收盤（含）以前的資料；月營收次月 11 日起才算知道（load.py）
  - 第 t+1 天開盤進場、第 t+h 天收盤出場，扣交易成本 0.585%（signals.COST）
  - 樣本內：出場日早於 SPLIT 的樣本（不讓樣本內的報酬期間跨進樣本外）；樣本外：t ≥ SPLIT
比較基準：同一天起漲雷達上、不符合該規則的股票（差＝規則組平均 − 其他組平均，逐日配對後平均，排除大盤漲跌的影響）。
樣本數：n＝股票×天，ep＝不同的「股票×營收月份」段數（同一段連續上榜的天數高度相關，真正獨立的樣本接近 ep）。
用法：python entry_backtest.py [--stars 4] > 報告.txt；結果另寫 results-<stars>.json
"""
import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

from load import load, radar_members, S

SPLIT = "2024-01-01"
COST = S.COST
HZ = {"short": (5, 10, 20), "long": (60, 120)}
MAIN = {"short": 10, "long": 60}
LOSS = {5: -0.10, 10: -0.10, 20: -0.15, 60: -0.25, 120: -0.30}   # 大跌門檻（扣成本後）
MIN_EP_OOS = 30      # 樣本外不同段數少於這個 → 不採用
MIN_EP_REF = 80      # 少於這個 → 僅供參考


def ma(x, n):
    return x.rolling(n, min_periods=int(n * 0.8)).mean()


def features(X):
    c, h, l, o, v = X["close"], X["high"], X["low"], X["open"], X["vyi"]
    chg = X["chg"]
    m5, m10, m20, m50, m60, m120, m150, m200, m240 = (ma(c, n) for n in (5, 10, 20, 50, 60, 120, 150, 200, 240))
    av20 = v.shift(1).rolling(20, min_periods=15).mean()
    av50 = v.shift(1).rolling(50, min_periods=40).mean()
    hi20p, hi40p, hi60p = (c.shift(1).rolling(n, min_periods=int(n * .8)).max() for n in (20, 40, 60))
    hi250, lo250 = c.rolling(250, min_periods=200).max(), c.rolling(250, min_periods=200).min()
    hi20 = c.rolling(20, min_periods=15).max()
    r = c.pct_change()
    ret5, ret20, ret60, ret120 = (c / c.shift(n) - 1 for n in (5, 20, 60, 120))
    b20, b60, b240 = c / m20 - 1, c / m60 - 1, c / m240 - 1
    # KD(9,3,3)
    ll9, hh9 = l.rolling(9, min_periods=9).min(), h.rolling(9, min_periods=9).max()
    rsv = ((c - ll9) / (hh9 - ll9) * 100).clip(0, 100)
    K = rsv.ewm(alpha=1 / 3, adjust=False).mean()
    Dk = K.ewm(alpha=1 / 3, adjust=False).mean()
    # RSI14
    up, dn = r.clip(lower=0), (-r).clip(lower=0)
    rsi = 100 - 100 / (1 + up.ewm(alpha=1 / 14, adjust=False).mean() / dn.ewm(alpha=1 / 14, adjust=False).mean())
    # MACD(12,26,9)
    dif = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    hist = dif - dif.ewm(span=9, adjust=False).mean()
    dea = dif.ewm(span=9, adjust=False).mean()
    up2, dn2 = up.ewm(alpha=1 / 2, adjust=False).mean(), dn.ewm(alpha=1 / 2, adjust=False).mean()
    rsi2 = 100 - 100 / (1 + up2 / dn2)
    sd20 = c.rolling(20, min_periods=15).std()
    bw = 4 * sd20 / m20
    squeeze = (bw <= bw.rolling(120, min_periods=100).min() * 1.0001).rolling(5, min_periods=1).max() > 0
    above150 = c > m150
    cross150 = (above150 & ~above150.shift(1).fillna(False).astype(bool)).rolling(10, min_periods=1).max().astype(bool) & above150
    vcp = r.rolling(20, min_periods=15).std() / r.rolling(120, min_periods=80).std()
    tr, fo = X["tr"], X["fo"]
    trd20 = (tr > 0).astype(float).where(tr.notna()).rolling(20, min_periods=15).sum()
    fo5 = fo.rolling(5, min_periods=5).sum()
    tr3 = (tr > 0).rolling(3, min_periods=3).sum() == 3
    fo20p = fo.rolling(20, min_periods=15).sum() / X["value"].rolling(20, min_periods=15).sum() * 100
    tx = X["taiex"].astype(float)
    tx60 = tx.rolling(60, min_periods=40).mean()
    bull = (tx > tx60) & (tx60 > tx60.shift(20))
    tradable = v >= 0.3
    mom121 = (c.shift(21) / c.shift(250) - 1).where(tradable)
    rs = mom121.rank(axis=1, pct=True) * 100
    days = X["pub_days"]
    one = pd.DataFrame(True, index=c.index, columns=c.columns)
    R = {
        # ---- 營收公布後時點 ----
        "公布後 0～2 天": (days <= 2),
        "公布後 3～5 天": (days >= 3) & (days <= 5),
        "公布後 6～10 天": (days >= 6) & (days <= 10),
        "公布後 11 天以上": (days >= 11),
        # ---- 均線排列與位置 ----
        "均線多頭排列（收>20>60>240 日均）": (c > m20) & (m20 > m60) & (m60 > m240),
        "短均線多頭（5>10>20 日均）": (m5 > m10) & (m10 > m20),
        "跌破年線（收<240 日均）": c < m240,
        "跌破季線（收<60 日均）": c < m60,
        "Minervini 趨勢模板": (c > m50) & (m50 > m150) & (m150 > m200) & (m200 > m200.shift(20)) & (c >= lo250 * 1.3) & (c >= hi250 * 0.75),
        "Stage 2（收>150 日均且均線上揚）": (c > m150) & (m150 > m150.shift(20)),
        # ---- 乖離／已漲幅度 ----
        "乖離 20 日均 0～5%": (b20 >= 0) & (b20 <= 0.05),
        "乖離 20 日均 >15%": b20 > 0.15,
        "乖離季線 0～10%": (b60 >= 0) & (b60 <= 0.10),
        "乖離季線 >25%": b60 > 0.25,
        "乖離季線 >40%": b60 > 0.40,
        "乖離年線 >80%": b240 > 0.80,
        "20 日漲幅 ≥30%": ret20 >= 0.30,
        "120 日已翻倍": ret120 >= 1.0,
        "5 日跌 ≥8%（短線急跌）": ret5 <= -0.08,
        "連 3 天收跌": (r < 0) & (r.shift(1) < 0) & (r.shift(2) < 0),
        "自 20 日高點回落 5～15% 且在季線上": (c / hi20 - 1 <= -0.05) & (c / hi20 - 1 >= -0.15) & (c > m60),
        # ---- 拉回均線 ----
        "拉回 20 日均線（低點觸及、收在上方、均線上揚）": (l <= m20 * 1.02) & (c >= m20) & (m20 > m20.shift(5)),
        "拉回季線（低點觸及、收在上方、季線上揚）": (l <= m60 * 1.02) & (c >= m60) & (m60 > m60.shift(20)),
        # ---- 突破／新高 ----
        "創 20 日新高": c > hi20p,
        "CANSLIM 買點（突破 40 日高、未超過 5%、量 ≥1.4 倍）": (c > hi40p) & (c <= hi40p * 1.05) & (v >= 1.4 * av50),
        "距 52 週高點 3% 內": c >= hi250 * 0.97,
        "布林上軌之上": c > m20 + 2 * sd20,
        "跳空上漲 ≥3%": (o / c.shift(1) - 1 >= 0.03) & (l > h.shift(1)),
        # ---- 量價 ----
        "價漲量增（漲、量 ≥1.5 倍 20 日均）": (chg > 0) & (v >= 1.5 * av20),
        "爆量長紅（量 ≥3 倍、漲 ≥5%）": (chg >= 5) & (v >= 3 * av20),
        "量縮回檔（跌、量 <0.7 倍 20 日均）": (chg < 0) & (v < 0.7 * av20),
        "波動收縮（20 日/120 日波動 <0.7）": vcp < 0.7,
        # ---- 指標 ----
        "KD 低檔黃金交叉（K<30 上穿 D）": (K > Dk) & (K.shift(1) <= Dk.shift(1)) & (K.shift(1) < 30),
        "KD 黃金交叉（任何位置）": (K > Dk) & (K.shift(1) <= Dk.shift(1)),
        "KD 高檔（K>80）": K > 80,
        "RSI14 >70": rsi > 70,
        "RSI14 <40": rsi < 40,
        "MACD 柱狀體翻正": (hist > 0) & (hist.shift(1) <= 0),
        # ---- 法人 ----
        "外資 5 日買超": fo5 > 0,
        "投信連買 3 天": tr3,
        "投信 20 日買超 ≥12 天": trd20 >= 12,
        "外資 20 日大賣（≤−10% 成交）": fo20p <= -10,
        # ---- 大盤／相對強度 ----
        "大盤多頭（加權>季線且季線上揚）": one & bull.values[:, None],
        "相對強度 RS ≥70（12-1 動能）": rs >= 70,
        "相對強度 RS ≥90": rs >= 90,
        # ---- 研究員補充（research.md 短線 2、3、4、9、10、11、12；長線 3、4、7） ----
        "KD 低檔黃金交叉（D<20，財訊原文門檻）": (K > Dk) & (K.shift(1) <= Dk.shift(1)) & (Dk < 20),
        "負乖離反彈（收<季線 10% 以上＋KD 金叉）": (b60 < -0.10) & (K > Dk) & (K.shift(1) <= Dk.shift(1)),
        "RSI(2)<10 且收>200 日均（Connors）": (rsi2 < 10) & (c > m200),
        "布林壓縮後突破（5 日內帶寬 120 日最低、收>上軌、量增）": squeeze & (c > m20 + 2 * sd20) & (v > av20),
        "MACD 零軸上黃金交叉": (dif > dea) & (dif.shift(1) <= dea.shift(1)) & (dif > 0),
        "跳空不補（開>昨高 1%、收≥昨高、量增）": (o >= h.shift(1) * 1.01) & (c >= h.shift(1)) & (v > av20),
        "外資投信同步連買 2 天": (fo > 0) & (fo.shift(1) > 0) & (tr > 0) & (tr.shift(1) > 0),
        "創 55 日新高（海龜長版）": c > c.shift(1).rolling(55, min_periods=44).max(),
        "Stage 2 進場（10 日內首次站上 150 日均、量 ≥2 倍 50 日均）": cross150 & (v.rolling(10, min_periods=1).max() >= 2 * av50),
        "拉回年線（低點觸及、收在上方、年線上揚）": (l <= m240 * 1.02) & (c >= m240) & (m240 > m240.shift(20)),
        "120 日漲幅 ≤30%": ret120 <= 0.30,
        "120 日漲幅 ≤50%": ret120 <= 0.50,
        "120 日漲幅 >80%": ret120 > 0.80,
        "乖離季線 ≤15%": b60 <= 0.15,
    }
    return {k: v.fillna(False).astype(bool) for k, v in R.items()}


def nw_t(x, lag):
    return S.nw_t(np.asarray(x, float), lag)


DATE_RULES = ("公布後 0～2 天", "公布後 3～5 天", "公布後 6～10 天", "公布後 11 天以上", "大盤多頭（加權>季線且季線上揚）")


def date_diff(sel, other, fwd, mkt, h, raw=False):
    """全市場同一天同值的規則（公布後天數、大盤）：同一天沒有對照組，改比「規則日 vs 其他日」名單的平均超額報酬
    （raw=True 比絕對報酬）。重疊持有期用 h 放大變異數（近似 Newey-West）。"""
    y = fwd if raw else fwd.sub(mkt, axis=0)
    a, b = y.where(sel).mean(axis=1).dropna(), y.where(other).mean(axis=1).dropna()
    if len(a) < h * 2 or len(b) < h * 2:
        return None, None
    d = a.mean() - b.mean()
    se = np.sqrt(a.var() * h / len(a) + b.var() * h / len(b))
    return round(float(d) * 100, 2), round(float(d / se), 2)


def stat(sel, other, fwd, mkt, ep, pos_ok, h, loss, date_rule=False):
    """sel/other：布林矩陣（限縮在名單內）；回傳規則組統計與逐日配對差。"""
    s = sel & pos_ok & fwd.notna()
    o = other & pos_ok & fwd.notna()
    n = int(s.values.sum())
    if n == 0:
        return {"n": 0}
    f = fwd.values[s.values]
    rs_ = fwd.where(s).mean(axis=1)
    ro_ = fwd.where(o).mean(axis=1)
    diff = (rs_ - ro_).dropna()
    if date_rule:
        d, t = date_diff(s, o, fwd, mkt, h)
        dr, tr_ = date_diff(s, o, fwd, mkt, h, raw=True)
    exc = fwd.sub(mkt, axis=0).values[s.values]
    eps = len(set(zip(np.where(s.values)[1], ep.values[s.values])))
    return {
        "n": n, "ep": eps, "days": int(rs_.notna().sum()),
        "avg": round(float(np.mean(f)) * 100, 2), "med": round(float(np.median(f)) * 100, 2),
        "exc": round(float(np.nanmean(exc)) * 100, 2),
        "win": round(float((f > 0).mean()) * 100, 1), "loss": round(float((f < loss).mean()) * 100, 1),
        "diff": round(float(diff.mean()) * 100, 2) if len(diff) else None,
        "t": round(float(nw_t(diff.values, h)), 2) if len(diff) > h * 2 else None,
        **({"diff": d, "t": t, "diff_raw": dr, "t_raw": tr_} if date_rule else {}),
    }


def run(stars_min=4, out_dir=None):
    X = load()
    member, stars = radar_members(X)
    univ = member & (stars >= stars_min)
    c, o = X["close"], X["open"]
    idx = pd.to_datetime(c.index)
    pub_i = X["pub_i"]
    X["pub_days"] = pd.DataFrame(np.repeat((np.arange(len(c)) - pub_i.values)[:, None], c.shape[1], axis=1),
                                 index=c.index, columns=c.columns)
    ep = pd.DataFrame(np.repeat(pub_i.fillna(-1).values[:, None], c.shape[1], axis=1), index=c.index, columns=c.columns)
    R = features(X)
    entry = o.shift(-1)
    tradable = X["vyi"] >= 0.3
    split_i = int(idx.searchsorted(pd.Timestamp(SPLIT)))
    pos = np.arange(len(c))
    res = {"split": SPLIT, "stars_min": stars_min, "cost": COST, "last": str(c.index[-1]), "horizons": {}, "base": {}}
    for kind, hs in HZ.items():
        for h in hs:
            fwd = c.shift(-h) / entry - 1 - COST
            mkt = fwd.where(tradable & fwd.notna()).mean(axis=1)
            is_ok = pd.DataFrame(np.repeat((pos + h < split_i)[:, None], c.shape[1], axis=1), index=c.index, columns=c.columns)
            oos_ok = pd.DataFrame(np.repeat((pos >= split_i)[:, None], c.shape[1], axis=1), index=c.index, columns=c.columns)
            base = {}
            for nm, ok in (("is", is_ok), ("oos", oos_ok)):
                st = stat(univ, univ & False, fwd, mkt, ep, ok, h, LOSS[h])
                st.pop("diff", None), st.pop("t", None)
                base[nm] = st
            res["base"][str(h)] = base
            out = {}
            for k, m in R.items():
                sel = univ & m
                oth = univ & ~m
                dr = k in DATE_RULES
                out[k] = {"is": stat(sel, oth, fwd, mkt, ep, is_ok, h, LOSS[h], dr),
                          "oos": stat(sel, oth, fwd, mkt, ep, oos_ok, h, LOSS[h], dr)}
            res["horizons"][str(h)] = out
            print("完成 h=%d" % h, file=sys.stderr)
    if out_dir:
        with open(os.path.join(out_dir, "results-%d.json" % stars_min), "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
    return res


def verdict(a, b):
    """a=樣本內、b=樣本外。"""
    if b.get("n", 0) == 0 or a.get("n", 0) == 0 or a.get("diff") is None or b.get("diff") is None:
        return "無樣本"
    if b["ep"] < MIN_EP_OOS:
        return "樣本太少，不採用"
    same = np.sign(a["diff"]) == np.sign(b["diff"])
    strong = a.get("t") is not None and abs(a["t"]) >= 2.5
    tag = ("加分" if a["diff"] > 0 else "扣分") if same and strong else "不顯著"
    if tag != "不顯著" and b["ep"] < MIN_EP_REF:
        tag += "（僅供參考）"
    return tag


def report(res):
    print("進場時機回測（%s 星以上起漲雷達名單；樣本外自 %s；成本 %.3f%%；資料到 %s）" % (res["stars_min"], res["split"], res["cost"] * 100, res["last"]))
    for h, out in res["horizons"].items():
        b = res["base"][h]
        print("\n== 持有 %s 個交易日 ==  基準（名單全部）樣本內 n=%d 平均 %.2f%% 大跌 %.1f%%｜樣本外 n=%d 平均 %.2f%% 大跌 %.1f%%"
              % (h, b["is"]["n"], b["is"]["avg"], b["is"]["loss"], b["oos"]["n"], b["oos"]["avg"], b["oos"]["loss"]))
        print("規則｜樣本內 n/段 差 t 大跌%｜樣本外 n/段 平均 差 大跌% 勝率｜判定")
        rows = sorted(out.items(), key=lambda kv: -(kv[1]["oos"].get("diff") or -99))
        for k, v in rows:
            a, o = v["is"], v["oos"]
            if not a.get("n") or not o.get("n"):
                print("%s｜無樣本" % k)
                continue
            print("%s｜%d/%d %+.2f t=%s %.1f｜%d/%d %.2f %+.2f %.1f %.1f｜%s" % (
                k, a["n"], a["ep"], a["diff"] or 0, a["t"], a["loss"], o["n"], o["ep"], o["avg"], o["diff"] or 0, o["loss"], o["win"], verdict(a, o)))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stars", type=int, default=4)
    a = ap.parse_args()
    report(run(a.stars, os.path.dirname(os.path.abspath(__file__))))
