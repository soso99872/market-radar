"""技術指標(回測 technical_test.py 與每日 radar.py 共用同一套公式)。

輸入是還原後的收盤、最高、最低(signals.frames)與成交金額,都是 日期 × 代號 的 DataFrame。
回測結論(scripts/technical_test.py,2020–2026,每月營收公告日樣本,60 日比一般股,2019–22 與 2023 後方向一致者):
  偏多:均線多頭排列、站上年線、RSI > 70、KD 高檔鈍化、MACD 在零軸上、突破布林上軌、價漲量增、向上跳空缺口
  偏空:均線空頭排列、RSI < 30、KD 低檔黃金交叉、布林通道收窄、價跌量增
  不明顯:MACD 柱狀翻正
「超賣、低檔黃金交叉」這類抄底訊號在台股反而較差;順勢的訊號較好。
"""
import pandas as pd

# 名稱 → (方向, 是否有回測依據)
EVIDENCE = {
    "均線多頭排列": (1, True), "均線空頭排列": (-1, True), "站上年線": (1, True), "跌破年線": (-1, True),
    "KD 低檔黃金交叉": (-1, True), "KD 高檔鈍化": (1, True),
    "RSI > 70": (1, True), "RSI < 30": (-1, True),
    "MACD 柱狀翻正": (0, False), "MACD 在零軸上": (1, True),
    "突破布林上軌": (1, True), "布林通道收窄": (-1, True),
    "價漲量增": (1, True), "價跌量增": (-1, True), "向上跳空缺口": (1, True),
}


def compute(C, HI, LO, VAL):
    """回傳 (布林訊號 dict, 數值 dict)。事件型訊號(交叉、缺口、翻正)看最近 5 個交易日內是否出現。"""
    ma = {n: C.rolling(n, min_periods=int(n * .8)).mean() for n in (5, 20, 60, 240)}
    lo9, hi9 = LO.rolling(9, min_periods=7).min(), HI.rolling(9, min_periods=7).max()
    rsv = ((C - lo9) / (hi9 - lo9) * 100).clip(0, 100)
    K = rsv.ewm(alpha=1 / 3, adjust=False).mean()
    D = K.ewm(alpha=1 / 3, adjust=False).mean()
    d = C.diff()
    up, dn = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean(), (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = 100 - 100 / (1 + up / dn)
    dif = C.ewm(span=12, adjust=False).mean() - C.ewm(span=26, adjust=False).mean()
    hist = dif - dif.ewm(span=9, adjust=False).mean()
    sd = C.rolling(20, min_periods=16).std()
    bw = 4 * sd / ma[20]
    v5, v20 = VAL.rolling(5, min_periods=4).mean(), VAL.rolling(20, min_periods=15).mean()
    r5 = C / C.shift(5) - 1
    in5 = lambda m: m.rolling(5, min_periods=1).max().astype(bool)   # noqa: E731
    sig = {
        "均線多頭排列": (C > ma[5]) & (ma[5] > ma[20]) & (ma[20] > ma[60]),
        "均線空頭排列": (C < ma[5]) & (ma[5] < ma[20]) & (ma[20] < ma[60]),
        "站上年線": C > ma[240],
        "跌破年線": C < ma[240],
        "KD 低檔黃金交叉": in5((K > D) & (K.shift(1) <= D.shift(1)) & (K < 30)),
        "KD 高檔鈍化": (K > 80).rolling(3, min_periods=3).min().astype(bool),
        "RSI > 70": rsi > 70,
        "RSI < 30": rsi < 30,
        "MACD 柱狀翻正": in5((hist > 0) & (hist.shift(1) <= 0)),
        "MACD 在零軸上": dif > 0,
        "突破布林上軌": C > ma[20] + 2 * sd,
        "布林通道收窄": bw <= bw.rolling(120, min_periods=80).quantile(0.2),
        "價漲量增": (r5 > 0) & (v5 > 1.5 * v20),
        "價跌量增": (r5 < 0) & (v5 > 1.5 * v20),
        "向上跳空缺口": in5(LO > HI.shift(1)),
    }
    sig = {k: v.fillna(False) for k, v in sig.items()}
    vals = {"K": K, "D": D, "RSI": rsi, "MACD": dif, "MA5": ma[5], "MA20": ma[20], "MA60": ma[60], "MA240": ma[240]}
    return sig, vals


def last_row(C, HI, LO, VAL, tail=300):
    """每日用:只算最後一天(取最近 tail 個交易日,足夠年線與布林 120 日分位)。回傳 {代號: {"on": [成立訊號], "v": {數值}}}。"""
    sl = slice(-tail, None)
    sig, vals = compute(C.iloc[sl], HI.iloc[sl], LO.iloc[sl], VAL.iloc[sl])
    out = {}
    for c in C.columns:
        if pd.isna(C[c].iloc[-1]):
            continue
        on = [k for k, m in sig.items() if bool(m[c].iloc[-1])]
        v = {k: (None if pd.isna(x[c].iloc[-1]) else round(float(x[c].iloc[-1]), 2)) for k, x in vals.items()}
        out[c] = {"on": on, "v": v}
    return out
