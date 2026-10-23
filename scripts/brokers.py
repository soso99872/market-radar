"""逐家券商目標價:經濟日報新聞標題／內文解析(純函式,不連網)。

來源是經濟日報搜尋「目標價」的新聞(前半解析,後半抓取、合併、輸出)。規則式解析,不用 LLM:
  parse(title, body, names) -> [{code, broker, target, rating, dir, prev_target}, ...]
    title  新聞標題(可含 <u> 等標籤)
    body   內文純文字,可為 None;標題抽不到券商或金額時才看內文
    names  全市場 {代號: 名稱}(用 load_names() 取得),或 build_index(names) 的結果
無法明確解析(券商、股票、金額對不起來)就不產生事件。

dir 依 PRD A 第 8 點優先順序,本檔做 ① 與 ③:
  ① 新聞寫明前次目標價(例「從 6,055 元調升至 6,800 元」)→ 兩數比較,並填 prev_target
  ③ 關鍵字:調升／上修／調高／上調 → up,調降／下修／調低／下調 → down,維持／重申 → keep
  都沒有 → None。② 與我們前一筆比較,存檔前用 apply_dir 補(覆蓋 ③,不覆蓋 ①)。

用法:python scripts/brokers.py [--backfill] [--check]
  預設抓搜尋前 3 頁;--backfill 抓到最後一頁;--check 只驗證 data/brokers/events.json(AC-B2)。
"""
import argparse
import glob
import gzip
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY = os.path.join(ROOT, "data", "history")
OUT_DIR = os.path.join(ROOT, "data", "brokers")
EVENTS = os.path.join(OUT_DIR, "events.json")
SCORES = os.path.join(OUT_DIR, "scores.json")
SEEN = os.path.join(OUT_DIR, "seen.json")   # 已處理過的網址(含沒產生事件的),重跑跳過

UNNAMED = "未具名"

# 外資券商:正規名稱 → 寫法(新聞用的簡稱、別名)。對照不到的具名券商照原名,不在此表就不認得
FOREIGN_BROKERS = {
    "摩根士丹利": ["摩根士丹利", "大摩"],
    "摩根大通": ["摩根大通", "小摩"],
    "美銀證券": ["美銀證券", "美銀美林", "美國銀行", "美銀", "美林"],
    "高盛": ["高盛"],
    "瑞銀": ["瑞銀"],
    "花旗": ["花旗環球", "花旗證券", "花旗"],
    "麥格理": ["麥格理"],
    "里昂證券": ["里昂證券", "法商里昂", "里昂"],
    "野村": ["野村"],
    "滙豐": ["滙豐", "匯豐"],
    "德意志": ["德意志", "德銀"],
    "巴克萊": ["巴克萊"],
    "大和": ["大和資本", "大和證券", "大和"],
    "瑞穗": ["瑞穗"],
    "星展": ["星展"],
    "法巴": ["法國巴黎", "法巴"],
    "杰富瑞": ["杰富瑞"],
    "CLSA": ["CLSA"],
    "Aletheia": ["Aletheia資本", "Aletheia"],
}
# 本土券商:單獨的名字可能是股票(統一、國泰…),所以要求後面接「證券／投顧／證」,
# 或是不會跟股票撞名的(凱基、元大…,後面不接「金」「控」「銀」)
DOMESTIC_BROKERS = {
    "凱基": ["凱基"], "元大": ["元大"], "富邦": ["富邦"], "群益": ["群益"], "永豐": ["永豐"],
    "統一": ["統一"], "國泰": ["國泰"], "中信": ["中信"], "兆豐": ["兆豐"], "第一金": ["第一金"],
    "華南永昌": ["華南永昌"], "日盛": ["日盛"], "玉山": ["玉山"], "康和": ["康和"],
    "宏遠": ["宏遠"], "台新": ["台新"], "國票": ["國票"], "新光": ["新光"], "合庫": ["合庫"],
}
# 只寫這些詞、沒寫券商名的,記「未具名」
UNNAMED_RE = re.compile(r"外資|法人|投顧|券商|大行|外商|亞系|美系|歐系|日系|分析師")

# 股票簡稱(資料裡的全名去掉後綴之外的常見說法)
STOCK_ALIASES = {
    "台積": "2330", "日月光": "3711", "台達": "2308", "華邦": "2344", "鴻準": "4062",
    "聯發": "2454",
}

_NAME_SUFFIX = re.compile(r"(-KY|-創|-DR|\*)+$")

_RATINGS = "強力買進|買進|買入|增持|優於大盤|跑贏大盤|超越大盤|加碼|中立|中性|持有|減碼|減持|賣出|劣於大盤|落後大盤|表現遜於大盤"
_RT = r"(?!(?:至|到)?[「『]?(?:" + _RATINGS + "))"   # 評等升降(「升至『優於大盤』」)不是目標價方向
_UP_RE = re.compile(r"(?:調升|上修|調高|上調|大升|同步升|升至|升到)" + _RT + r"|升目標|升" + _RT + r"[^，。；\s]{0,6}?目標價|提高目標價")
_DOWN_RE = re.compile(r"(?:調降|下修|調低|下調|降至|降到)" + _RT + r"|降目標|降" + _RT + r"[^，。；\s]{0,6}?目標價")
# ③ 的維持／重申只在後面接目標價時才算(「重申買進」只是評等)
_KEEP_RE = re.compile(r"(?:維持|重申)(?:[^，,。；;、\s]|(?<=\d),(?=\d)){0,10}?(?:目標價|目標股價)|目標價(?:維持|不變)")
# 標題寫了調升／調降卻沒給前次目標價 → 內文找「從 X 元…至 Y 元」補 prev_target
_CUM_RE = re.compile(r"今年來|年來|[二兩三四五六七八九十]度|累計|最高|最低|\d點")
_MOVE_RE = re.compile(r"調(?!整|查)|上修|下修|升至|降至|升到|降到|大升|提高")

_RATING_RE = re.compile(r"[「『](" + _RATINGS + r")[」』]|(" + _RATINGS + r")(?=評等)|(?:評等|建議|給予|維持|予以)(?:至|為|於|調升至|調降至)?[「『]?(" + _RATINGS + ")")

_NUM = r"\d[\d,]*(?:\.\d+)?"
_BAD_UNIT = r"(?!\d)(?![.,]\d)(?![\d,.]*[美港日歐%％倍億萬月日年檔家張季點成度台片顆支套人股xX])(?![–—~～-]\d)(?!元?以上)"   # 後面接單位或「480–500」這種範圍都不是目標價
# 「從 X 元…至 Y 元」「由 X 元直衝 Y 元」「從 500 元升到 725 元」
_FROM_TO = re.compile(r"[從由](?:原先的?)?\s*(" + _NUM + r")\s*元?\s*((?:[^\d，。；、]|\d+%){0,14}?)\s*(" + _NUM + r")\s*元((?:[、與及]\s*" + _NUM + r"(?!\d)(?![.,]\d)元?(?![^\d，。；、]{0,3}[升降調修]))*(?:、[^\d，,。；、]{0,10}?(?:再|又)?[升降調修]+至\s*" + _NUM + r"(?!\d)(?![.,]\d)元?)?)")   # 第 4 組:「從30元升至38元、42元、50元」連續調整清單
# 「分別由A元上調至B元、C元上調至D元」第二組沒有「由」,前面接「、」,中間一定要有升降字眼
_FROM_TO_B = re.compile(r"(?<=、)\s*(" + _NUM + r")\s*元([^\d，,。；、]{0,3}[升降調修][^\d，,。；、]{0,10}?)\s*(" + _NUM + r")\s*元")
# 「分別由1,000元、2,000元」前次目標價清單(兩個以上)
# 「落在5,000至5,500元不等」「介於…之間」是統計區間,不是某份報告的目標價
_RANGE = re.compile(r"(落在|介於)?\s*(" + _NUM + r")\s*元?\s*[至到~～-]\s*(" + _NUM + r")\s*元?\s*(不等|之間|區間)?")
_PREV_LIST = re.compile(r"[從由](?:原先的?)?\s*" + _NUM + r"\s*元?(?:[、與]" + _NUM + r"\s*元?)+")
# 金額觸發:強觸發可省略「元」;弱觸發一定要有「元」
_STRONG = r"(?:目標價維持|目標價為|目標價|目標股價|調升至|上調至|調高至|上修至|調降至|下調至|下修至|提高至|升至|升到|降至|降到|喊到|喊|上看)"
_WEAK = r"(?:看到|看|為|至|到|達)"
_AMT_STRONG = re.compile(_STRONG + r"\s*(" + _NUM + r")" + _BAD_UNIT + r"(元)?((?:[、與及]\s*" + _NUM + r"元?)*)")
_AMT_WEAK = re.compile(_WEAK + r"\s*(" + _NUM + r")\s*元(?!以上)((?:[、與及]\s*" + _NUM + r"元?)*)")
# 「維持4,750元目標價」這種金額在前、目標價在後的寫法
_AMT_POST = re.compile(r"(" + _NUM + r")\s*元\s*(?:的)?目標(?:股)?價")
_TP_RE = re.compile(r"目標價|目標股價|合理股價")
# 非目標價的金額:前 15 字(最近一個「元」之後)有獲利類字眼;彭博／平均／共識的目標價;年份
_EPS_RE = re.compile(r"EPS|每股純益|每股盈餘|獲利|營收", re.I)
_CONSENSUS_RE = re.compile(r"彭博|平均|共識")
_SCENE_RE = re.compile(r"樂觀情境|悲觀情境|(?<!基本)情境|牛市|熊市")   # 情境價不是這次的目標價
_OLD_RE = re.compile(r"先前|此前|之前|稍早|日前")   # 引用舊報告(看金額所在子句)
_OLD_VETO = re.compile(r"先前|此前|之前|稍早")    # 標題金額要不要被內文否決:「日前」常是幾天前的同一份報告,不算
_OLD_SENT = re.compile(r"綜合近期|第[一二三四五]家為|(?:\d+月[底初]|年初)[^，。；]{0,4}?(?:率先|曾)")   # 整句(到句號)都是舊報告回顧
_TOP_NOW = re.compile(r"目前以[^，。；]{0,12}?的\s*(" + _NUM + r")\s*元")
_OLD_NUM = re.compile(r"(?:先前|此前|之前|稍早|日前)(?:的|為)?(?=\d)")    # 「從先前的3,000元調升至3,300元」:舊的是前次金額,不是這份報告
_PRICE_RE = re.compile(r"盤中|(?<!合理)(?<!目標)股價|收盤|衝達|一度|壓至|新高|漲停")
_CLAUSE_END = re.compile(r"[，,](?!\d{3})")
_YEAR_RE = re.compile(r"(?:19|20)\d\d")
_FX_RE = re.compile(r"人民幣|美元|美金|日圓|港幣|ADR")


# 被比較對象:「超越瑞銀的11,000元」「高於大摩的目標價」——這家的金額不是這句的主詞
_CMP_BEFORE = re.compile(r"(?:超越|超過|高於|低於|優於|勝過)[^，。；、\d「」『』]{0,3}$")
_CMP_AFTER = re.compile(r"的\s*(?:目標(?:股)?價\s*)?" + _NUM + r"元?")


def _compared(clause, ents):
    """回傳被比較的券商 [(券商, 金額結束位置)]。有「的＋金額」或前面有超越／高於等字眼才算。"""
    out = []
    names = {v for _, _, k, v in ents if k == "broker"}
    for s, e, k, v in ents:
        if k != "broker":
            continue
        m = _CMP_AFTER.match(clause, e)
        if clause.startswith("率先", e):    # 「Aletheia率先喊出萬元價後,大摩…」:率先的是先前那份報告,不是這句的主詞
            out.append((v, s, clause.find("後", e) + 1 or e))
        elif _CMP_BEFORE.search(clause[max(0, s - 8):s]):
            out.append((v, s, m.end() if m else e))
        elif m and names - {v}:    # 「X的金額」要同子句還有另一家券商當主詞才算被比較
            out.append((v, s, m.end()))
    return out


# 股票名剛好是一般詞(材料、新產、三星…):同篇有「（代號）」或名稱後面直接接「目標價」「評等」才算股票
AMBIGUOUS_STOCK = {
    "材料", "新產", "大中", "三星", "大成", "新興", "至上", "數字", "宏觀", "藍天", "資通", "雙喜", "泰山",
    "可成", "力士", "日成", "上銀", "業旺", "新建", "世紀", "中工", "台產", "光明", "中租", "冠軍", "大量",
    "國產", "海光", "南亞", "惠光",    # 惠光:「受惠光通訊」
}
# 本土券商單獨名後面接這些是 ETF／期貨(富邦旗艦50、群益半導體),不是券商
_ETF_AFTER = ("台", "臺", "旗艦", "費城", "半導體", "精選", "期貨")
_BIG_AFTER = "關幅升增漲跌降減"          # 元大 + 這些字:「大關」「大幅」「大升」,不是券商
_BIG_BEFORE = "千萬億兆美 	"             # 元大 前面是數字或這些字:「1兆美元大關」「20 元大幅」


def _broker_ok(text, s, e, alias, bare_domestic):
    """比對到的券商寫法在上下文裡是不是真的券商(排除 ETF、元大＋大關／大幅、中信建投、衛星展等)。"""
    before, after = text[max(0, s - 2):s], text[e:e + 3]
    if before.endswith("主動"):
        return False
    if alias == "中信" and text.startswith("建投", e):
        return False
    if alias == "星展" and before.endswith("衛"):
        return False
    if bare_domestic:
        if text.startswith(_ETF_AFTER, e):
            return False
        if alias == "元大":
            if after[:1] and after[0] in _BIG_AFTER:
                return False
            if s and (text[s - 1].isdigit() or text[s - 1] in _BIG_BEFORE):
                return False
    return True


class _Index:
    """名稱比對用的索引:股票名稱與券商寫法分開找出所有候選(含重疊),重疊時依 find 的規則取捨。"""

    def __init__(self, names):
        stock = {}   # 名稱／簡稱 → 代號
        for code, name in names.items():
            if not name or len(name) < 2:
                continue
            stock[name] = code
        for code, name in names.items():            # 去後綴的簡稱(臻鼎-KY → 臻鼎),不蓋掉全名
            short = _NAME_SUFFIX.sub("", name or "")
            if len(short) >= 2 and short not in stock:
                stock[short] = code
        for short, code in STOCK_ALIASES.items():
            if code in names and short not in stock:
                stock[short] = code
        self.stock = stock
        self.stock_by_first = {}     # 首字 → 名稱(長的在前),找候選不用逐字比整張表
        for n in sorted(stock, key=lambda x: -len(x)):
            self.stock_by_first.setdefault(n[0], []).append(n)
        self.broker = {}   # 寫法 → 正規名稱
        self.domestic = set()
        forms = []         # (排序用長度, 正規表示式片段)
        for canon, aliases in FOREIGN_BROKERS.items():
            for a in aliases:
                self.broker[a] = canon
                forms.append((len(a), re.escape(a)))
        for canon, aliases in DOMESTIC_BROKERS.items():
            for a in aliases:
                self.broker[a] = canon
                self.domestic.add(a)
                forms.append((len(a) + 2, re.escape(a) + r"(?:證券|投顧|證)"))
                if a not in stock:     # 不會撞到股票名的,單獨寫也算(後面不接金／控／銀／台灣)
                    forms.append((len(a), re.escape(a) + r"(?![金控銀台])"))
        forms.sort(key=lambda x: -x[0])
        self.regex = re.compile("(?=(" + "|".join(p for _, p in forms) + "))")   # lookahead:每個位置都能找出候選

    def find(self, text, codes=()):
        """回傳依出現順序、不重疊的 [(起, 迄, 'stock'|'broker', 值)]。
        先找出所有候選(含重疊),重疊時 ①長的贏 ②一樣長時股票名贏單獨券商名(不帶證券／投顧) ③都是股票名時後面的贏。
        codes = 同篇出現「（代號）」的代號集合,AMBIGUOUS_STOCK 要靠它或「目標價」才算股票。"""
        cands = []   # (起, 迄, kind, 值, 優先序)
        for m in self.regex.finditer(text):
            s = m.group(1)
            st = m.start()
            if st and text[st - 1].isdigit() and s not in self.stock:
                continue     # 「2,988元大幅」的元大不是券商
            base = _broker_base(s, self.broker)
            if base is None:
                continue
            alias = s if s in self.broker else next(a for a in self.domestic if s.startswith(a))
            bare = s in self.domestic
            if _broker_ok(text, st, st + len(s), alias, bare):
                cands.append((st, st + len(s), "broker", base, 1 if bare else 0))
        for i, ch in enumerate(text):
            for n in self.stock_by_first.get(ch, ()):
                if not text.startswith(n, i):
                    continue
                e = i + len(n)
                if text[max(0, i - 2):i] == "主動":
                    continue
                code = self.stock[n]
                if n in AMBIGUOUS_STOCK and code not in codes and not text.startswith(("目標價", "目標股價", "評等"), e):
                    continue
                cands.append((i, e, "stock", code, 0))
        cands.sort(key=lambda c: (-(c[1] - c[0]), c[4], -c[0]))
        taken = []
        for c in cands:
            if not any(c[0] < t[1] and t[0] < c[1] for t in taken):
                taken.append(c)
        taken.sort()
        return [c[:4] for c in taken]


def _broker_base(s, table):
    """比對到的字串 → 正規券商名;不是券商回傳 None。本土券商去掉「證券／投顧／證」後綴再查。"""
    if s in table:
        return table[s]
    for suf in ("證券", "投顧", "證"):
        if s.endswith(suf) and s[:-len(suf)] in table:
            return table[s[:-len(suf)]]
    return None


def build_index(names):
    return _Index(names)


def load_names(root=ROOT):
    """從 data/history 最新一天的 s 取全市場 {代號: 名稱}。"""
    files = sorted(glob.glob(os.path.join(root, "data", "history", "*", "*.json.gz")))
    if not files:
        return {}
    with gzip.open(files[-1], "rt", encoding="utf-8") as f:
        s = json.load(f).get("s", {})
    return {code: v[0] for code, v in s.items()}


# ---------- 文字處理 ----------

_FULL = str.maketrans("０１２３４５６７８９，．", "0123456789,.")


_NUM_UNIT_GAP = re.compile(r"(\d) (?=[億萬兆美元%％倍])")    # 「850 億美元」「3,088 元」:數字與單位之間的空白去掉,單位排除才擋得到


def _clean(text):
    """去標籤、全形數字轉半形、連續空白壓成一個。換行保留給內文斷句。"""
    text = re.sub(r"<[^>]+>", "", text or "")
    text = text.translate(_FULL)
    text = re.sub(r"[ \t　\xa0]+", " ", text)
    return _NUM_UNIT_GAP.sub(lambda m: m.group(1), text)


def _num(s):
    v = float(s.replace(",", ""))
    return int(v) if v == int(v) else v


def _first(regex, *texts):
    for t in texts:
        m = regex.search(t)
        if m:
            return m
    return None


def _direction(prev, target, *texts):
    """① 有前次目標價就比較;③ 否則看關鍵字(同時有調升與調降視為不明)。"""
    if prev is not None:
        return "up" if target > prev else "down" if target < prev else "keep"
    for t in texts:
        up, down = bool(_UP_RE.search(t)), bool(_DOWN_RE.search(t))
        if up != down:
            return "up" if up else "down"
        if up and down:
            return None
        if _KEEP_RE.search(t):
            return "keep"
    return None


# 「從「中立」上調到「優於大盤」」「評等由A調降至B」:評等取調整後的 B
_RATING_MOVE = re.compile(r"[從由][「『]?(?:" + _RATINGS + r")[」』]?(?:上調|調高|調升|升級|上修|下調|調降|調低|降級|下修|調整|升|降)(?:至|到)[「『]?(" + _RATINGS + ")")


def _rating(*texts):
    for t in texts:
        m = _RATING_MOVE.search(t)
        if m:
            return m.group(1)
        m = _RATING_RE.search(t)
        if m:
            return next(g for g in m.groups() if g)
    return None


def _foreign(clause, pos):
    """目標價前面緊接外幣／ADR(例「人民幣目標價至6.4」「台積電ADR目標價」)→ 不是台幣目標價。"""
    tp = max(clause.rfind("目標價", 0, pos + 1), clause.rfind("目標股價", 0, pos + 1))
    head = clause[max(0, tp - 4):tp] if tp >= 0 else ""
    return bool(_FX_RE.search(head))


def _not_target(clause, start, num_at, num, yuan, sentence=""):
    """這個金額不是目標價(EPS 等獲利金額、彭博／平均／共識目標價、年份)就回傳 True。
    start = 金額（含觸發詞）在子句的起點;num_at = 數字本身的起點;yuan = 數字後面有沒有「元」。
    EPS 類字眼只看數字前 15 字,且只看最近一個「元」或「目標價」之後(前面的字眼屬於別的金額)。"""
    head = clause[max(0, num_at - 15):num_at]
    for cut in ("元", "目標價", "目標股價"):
        head = head[head.rfind(cut) + 1:] if cut in head else head
    if _EPS_RE.search(head):
        return True
    if _CONSENSUS_RE.search(clause[max(0, start - 8):start + 6]):
        return True
    if not yuan and _YEAR_RE.fullmatch(num):
        return True
    if any((m.group(1) or m.group(4)) and m.start(2) <= num_at < m.end(3) for m in _RANGE.finditer(clause)):
        return True
    if _SCENE_RE.search(clause[max(0, num_at - 40):num_at]):    # 10 字抓不到「樂觀情境，…目標價跟著提升到」
        return True
    if "目標" not in clause[start:num_at] and _PRICE_RE.search(clause, max(0, num_at - 10), num_at):
        return True     # 沒有「目標價」觸發詞的金額,前面是股價說法(盤中衝達2,770元)不是目標價
    off = max(sentence.find(clause), 0)
    if any(m.start() < off + num_at for m in _OLD_SENT.finditer(sentence)):    # 回顧舊報告的字眼在金額前面
        return True
    m = _TOP_NOW.search(clause)     # 「目前以里昂證券的3,030元目標價最高」:拿來排名的舊報告
    if m and m.start(1) == num_at:
        return True
    seg = _OLD_NUM.sub("", _CLAUSE_END.split(clause[:num_at])[-1])    # 金額所在子句(_clean 把全形逗號都轉成半形,所以兩種都要認;千分位逗號不算)
    return bool(_OLD_RE.search(seg))


# 一句裡「A升至X元、B升至Y元」與「…分別調高至X元與Y元」切成片段,各自配對
_SPLIT = re.compile(r"(?<=元)、(?=[^\d、，]{1,12}?[升降調修喊看])|，(?=[^，]*分別)")


def _amounts(clause, carry_tp, sentence=""):
    """抽出子句裡的目標價 [(位置, 目標價, 前次目標價)]。子句沒有「目標價」且前面也沒有時不抽。"""
    if not (_TP_RE.search(clause) or carry_tp):
        return []
    found, used = [], []
    pl = _PREV_LIST.search(clause) if "分別" in clause else None
    for m in list(_FROM_TO.finditer(clause)) + list(_FROM_TO_B.finditer(clause)):
        if any(m.start() < ue and us < m.end() for us, ue in used):
            continue
        if pl and pl.start() <= m.start() < pl.end():    # 「由A元、B元調高到…」前次清單交給後面依序配對
            continue
        if _not_target(clause, m.start(), m.start(3), m.group(3), True, sentence):
            continue
        tail = re.findall(_NUM, m.group(4)) if m.re.groups > 3 and "分別" not in clause else []
        if tail:    # 連續調整:最新是清單最後一個,前次是它前面那個
            found.append((m.start(), _num(tail[-1]), _num((m.group(1), m.group(3), *tail)[-2])))
        else:
            found.append((m.start(), _num(m.group(3)), _num(m.group(1))))
        used.append((m.start(), m.end()))

    def free(a, b):
        return not any(a < ue and us < b for us, ue in used)

    for m in _AMT_STRONG.finditer(clause):
        if not free(m.start(), m.end()):
            continue
        if _foreign(clause, m.start()):
            continue
        if _not_target(clause, m.start(), m.start(1), m.group(1), bool(m.group(2)), sentence):
            continue
        used.append((m.start(), m.end()))
        found.append((m.start(), _num(m.group(1)), None))
        for extra in re.findall(_NUM, m.group(3) or ""):
            if not _YEAR_RE.fullmatch(extra):
                found.append((m.start(), _num(extra), None))
    for m in _AMT_WEAK.finditer(clause):
        if not free(m.start(), m.end()):
            continue
        if _foreign(clause, m.start()):
            continue
        if _not_target(clause, m.start(), m.start(1), m.group(1), True, sentence):
            continue
        used.append((m.start(), m.end()))
        found.append((m.start(), _num(m.group(1)), None))
        for extra in re.findall(_NUM, m.group(2) or ""):
            if not _YEAR_RE.fullmatch(extra):
                found.append((m.start(), _num(extra), None))
    for m in _AMT_POST.finditer(clause):
        if not free(m.start(), m.end()) or _foreign(clause, m.start()):
            continue
        if _not_target(clause, m.start(), m.start(1), m.group(1), True, sentence):
            continue
        used.append((m.start(), m.end()))
        found.append((m.start(), _num(m.group(1)), None))
    found = sorted((f for f in found if f[1] > 0), key=lambda x: x[0])
    pm = _PREV_LIST.search(clause) if "分別" in clause else None    # 「分別由X元、Y元調高至A元、B元」:前次依序對應
    if pm:
        prevs = re.findall(_NUM, pm.group(0))
        if len(prevs) == len(found) and all(f[2] is None for f in found):
            found = [(p, t, _num(prevs[i])) for i, (p, t, _) in enumerate(found)]
    return found


def _analyze(text, idx, title="", fallback_stocks=()):
    """解析一段文字(標題或內文),回傳事件 list。"""
    events = []
    carry_broker = None
    carry_tp = False
    orphans = []
    codes = {c for c in re.findall(r"[（(](\d{4,5})[）)]", text)}
    last = (None, -9)    # (前面句子只提到的那一檔股票, 句序):下一句沒寫股票名就沿用
    si = 0
    for si, sentence in enumerate(re.split(r"[。！？\n]+", text) if "\n" in text or "。" in text else [text]):
        sentence = sentence.strip()
        if not sentence:
            continue
        for whole, clause in [(w, c) for w in sentence.split("；") for c in ([w] if any(re.search("[升降調修]", m.group(4)) for m in _FROM_TO.finditer(w)) else _SPLIT.split(w))]:    # 連續調整清單最後一項帶說明(「、法說前夕再降至X元」)不能被切開
            ents = idx.find(clause, codes)
            stocks = list(dict.fromkeys(v for _, _, k, v in idx.find(whole, codes) if k == "stock"))
            # 「台積電（2330）」括號代號也算
            for c in re.findall(r"[（(](\d{4,5})[）)]", clause):
                if c in idx.stock.values() and c not in stocks:
                    stocks.append(c)
            if len(stocks) == 1:
                last = (stocks[0], si)
            cmp_ = _compared(clause, ents)
            cmp_names = {c[0] for c in cmp_}
            cmp_names |= {v for s, e, k, v in ents if k == "broker" and re.search("除了?$", clause[max(0, s - 2):s]) and clause.startswith("外", e)}    # 「除了高盛外」的高盛不是主詞
            brokers = list(dict.fromkeys(v for _, _, k, v in ents if k == "broker" and v not in cmp_names))
            amts = [a for a in _amounts(clause, carry_tp, sentence) if not any(s <= a[0] < e for _, s, e in cmp_)]
            if "分別" in clause and len(amts) > 1 and len(brokers) != len(amts):    # 「繼小摩後,最新如大摩與高盛分別上調至A元及B元」:分別之前上一個逗號以前的券商不算
                cut = max((m.end() for m in _CLAUSE_END.finditer(clause, 0, clause.find("分別"))), default=0)
                near = list(dict.fromkeys(v for s, _, k, v in ents if k == "broker" and v not in cmp_names and s >= cut))
                brokers = near if len(near) == len(amts) else brokers
            has_tp = bool(_TP_RE.search(clause))
            if len(brokers) == 1:
                carry_broker = brokers[0]
            if has_tp:
                carry_tp = True
            if not amts:
                continue
            from_last = False
            if not stocks and len(fallback_stocks) == 1:
                stocks = list(fallback_stocks)
            elif not stocks and last[0] and si - last[1] <= 1:
                stocks = [last[0]]
                from_last = True
            if not stocks:
                who = brokers[0] if len(brokers) == 1 else None if brokers or clause != whole else carry_broker
                orphans += [(t, pv, who) for _, t, pv in amts if pv is not None]    # 前次目標價寫在沒有股票名的下一句
                continue
            if brokers:
                bl = brokers
            elif _person_subject(clause, ents, amts[0][0]):    # 「李明2日重申…」句首是分析師人名:不是前一句的券商
                continue
            elif cmp_ and carry_broker and clause == whole:    # 主詞被拿掉(被比較對象不算)→ 沿用前面的券商,優先於「外資」未具名
                bl = [carry_broker]
            elif UNNAMED_RE.search(clause):
                bl = [UNNAMED]
            elif carry_broker and clause == whole:     # 被切開的片段不沿用前面的券商
                bl = [carry_broker]
            else:
                continue
            if from_last and bl == [UNNAMED] and all(a[2] is None for a in amts):
                continue    # 沿用前一句的股票,只有券商明確(或有前次金額)才算
            if title and len(amts) == 1 and len(stocks) > 1 and len(bl) == 1:    # 只用在內文(標題沒股票可選就交給內文,別擋掉抓內文)
                stocks = _nearest_stock(clause, ents, amts[0][0]) or stocks
            pairs = _pair(stocks, bl, amts)
            ctx = (clause, sentence, title)
            quoted = re.findall(r"[「『](" + _RATINGS + r")[」』]", clause)
            by_order = "分別" in clause and not _RATING_MOVE.search(clause) and len(pairs) > 1 and len(quoted) == len(pairs)    # 「分別給予「中立」、「優於大盤」…」評等也依序配對
            for i, (code, broker, (_, target, prev)) in enumerate(pairs):
                events.append({
                    "code": code, "broker": broker, "target": target,
                    "rating": quoted[i] if by_order else _rating(clause, sentence),
                    "dir": _direction(prev, target, *ctx),
                    "prev_target": prev,
                })
    for e in events:    # 補前次:「…上看10,500元」下一句「目標價由6,890元大升至10,500元」
        for t, pv, who in orphans:
            if e["prev_target"] is None and e["target"] == t and who in (None, e["broker"]):
                e["prev_target"], e["dir"] = pv, _direction(pv, t)
    uniq = {}
    for e in events:    # 同檔同券商同金額只留一筆,有前次目標價的優先
        k = (e["code"], e["broker"], e["target"])
        if k not in uniq or (uniq[k]["prev_target"] is None and e["prev_target"] is not None):
            uniq[k] = e
    return _drop_unnamed(list(uniq.values()))


_PERSON_RE = re.compile(r"(?:^|[，,])(?!因此|因而|所以|同時|其中|另外|此外|主要|目前|不過|但是|並且|而且|此時|因為|由於|基於|整體|未來|後續|隨著|隨後|同步|同樣|接著|最新)([一-鿿]{2,3})(?:\d+日(?:則|也)?(?:重申|表示|指出|認為|預期|預估|看好|給予)|則?給予)")


def _person_subject(clause, ents, limit):
    """子句裡有「2～3 字人名＋(日期)＋動詞」(例「李明2日重申」「高多斯給予」(沒有日期的只認「給予」,免得「鄭盛元預估…」同一券商的分析師被擋)),且那幾個字不是股票或券商名。"""
    for m in _PERSON_RE.finditer(clause, 0, limit):    # 只看第一個金額之前
        if not UNNAMED_RE.search(m.group(1)) and not any(s < m.end(1) and m.start(1) < e for s, e, _, _ in ents):
            return True
    return False


def _drop_unnamed(events):
    """同檔同金額已有具名券商時,未具名那筆併進去(缺的前次目標價、方向補給具名那筆)後丟掉。"""
    named = {(e["code"], e["target"]): e for e in events if e["broker"] != UNNAMED}
    out = []
    for e in events:
        n = named.get((e["code"], e["target"]))
        if e["broker"] == UNNAMED and n:
            if n["prev_target"] is None and e["prev_target"] is not None:
                n["prev_target"], n["dir"] = e["prev_target"], _direction(e["prev_target"], e["target"])
            continue
        out.append(e)
    return out


def _nearest_stock(clause, ents, pos):
    """一個金額、同句多檔股票:取金額前最近的一檔,條件是其他股票都在更早的分句(金額所在分句與前一分句裡只有它)。"""
    before = [(s, v) for s, e, k, v in ents if k == "stock" and s < pos]
    if not before:
        return None
    cuts = [m.start() for m in _CLAUSE_END.finditer(clause, 0, pos)]
    seg_start = cuts[-2] if len(cuts) >= 2 else 0     # 金額所在分句的前一個分句起點
    near = {v for s, v in before if s >= seg_start}
    return list(near) if len(near) == 1 else None


def _pair(stocks, brokers, amts):
    """金額要能明確對應:一個金額 ↔ 一檔、一家;多個金額時,檔數(或家數)要剛好等於金額數。"""
    n = len(amts)
    if n == 1:
        if len(stocks) == 1 and len(brokers) == 1:
            return [(stocks[0], brokers[0], amts[0])]
        return []
    if len(stocks) == n and len(brokers) == 1:
        return [(stocks[i], brokers[0], amts[i]) for i in range(n)]
    if len(brokers) == n and len(stocks) == 1 and UNNAMED not in brokers:
        return [(stocks[0], brokers[i], amts[i]) for i in range(n)]
    return []


def needs_body(title, events):
    """標題解析的結果還要不要抓內文:沒事件、有未具名、或標題寫調升／調降卻沒有前次目標價。"""
    if not events or any(e["broker"] == UNNAMED for e in events):
        return True
    t = _clean(title)
    if _CUM_RE.search(t):    # 累計說法的前次不可靠、「最高」可能是回顧舊報告、「31,000點」是大盤預測的標題(金額可能是彭博共識),看內文確認
        return True
    return bool(_MOVE_RE.search(t)) and any(e["prev_target"] is None for e in events)


def _stale(body, target):
    """標題抽到的金額,內文裡每一次出現都是彭博／平均／共識或舊報告的說法 → True(不是這份報告的目標價)。"""
    amt = re.compile(r"(?<![\d,.])(?:%s|%s)(?![\d,]|\.\d)" % (re.escape("{:,}".format(target)), target))
    seen = False
    for sent in re.split(r"[。！？\n]+", body):
        for m in amt.finditer(sent):
            seen = True
            seg = _CLAUSE_END.split(sent[:m.start()])[-1]
            tn = _TOP_NOW.search(sent)
            if not (tn and tn.start(1) == m.start()) and not (_CONSENSUS_RE.search(seg[-15:]) or _OLD_VETO.search(seg) or _OLD_SENT.search(sent)):
                return False
    return seen


def parse(title, body, names):
    """標題優先;標題抽不到券商或金額、或缺前次目標價時再用內文補。
    回傳 [{code, broker, target, rating, dir, prev_target}]。"""
    idx = names if isinstance(names, _Index) else build_index(names)
    title = _clean(title).replace("\n", " ")
    t_events = _analyze(title, idx)
    if not body or not needs_body(title, t_events):
        return t_events
    t_codes = set(re.findall(r"[（(](\d{4,5})[）)]", title))
    t_stocks = list(dict.fromkeys(v for _, _, k, v in idx.find(title, t_codes) if k == "stock"))
    b_events = _analyze(_clean(body), idx, title=title, fallback_stocks=t_stocks)
    if t_stocks:
        b_events = [e for e in b_events if e["code"] in t_stocks]
    body_text = _clean(body)
    t_events = [e for e in t_events if not _stale(body_text, e["target"])]
    result = []
    for e in t_events:
        for b in b_events:      # 內文有同檔同金額的事件:補具名券商、前次目標價
            if b["code"] == e["code"] and b["target"] == e["target"]:
                prev = b["prev_target"] if b["prev_target"] is not None else e["prev_target"]   # 內文「由X至Y」優先(標題可能是累計說法)
                broker = b["broker"] if e["broker"] == UNNAMED and b["broker"] != UNNAMED else e["broker"]
                e = dict(e, broker=broker, rating=e["rating"] or b["rating"], prev_target=prev,
                         dir=_direction(prev, e["target"]) if prev is not None else e["dir"] or b["dir"])
                break
        result.append(e)
    if not t_events or any(e["broker"] == UNNAMED for e in t_events):
        have = {e["code"] for e in result}
        result += [b for b in b_events if b["code"] not in have]
    return _drop_unnamed(result)


# ---------- 抓取、合併、輸出 ----------

SEARCH = "https://money.udn.com/search/result/1001/" + urllib.parse.quote("目標價") + "/{page}"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
TIMEOUT, RETRIES, GAP = 20, 2, 1.0
DEFAULT_PAGES, MAX_PAGES = 3, 80
DIR_DAYS = 365

_ITEM = re.compile(
    r'<a href="(https://money\.udn\.com/money/story/\d+/\d+)[^"]*"[^>]*data-slotname="list_搜尋結果頁"[^>]*title="([^"]*)"'
    r'.*?<time>(\d{4}-\d{2}-\d{2})[^<]*</time>', re.S)
_last_req = [0.0]


def fetch(url):
    """GET 網頁文字。間隔 >= 1 秒、逾時 20 秒、失敗重試 2 次,仍失敗就丟例外。"""
    err = None
    for i in range(RETRIES + 1):
        wait = GAP - (time.time() - _last_req[0])
        if wait > 0:
            time.sleep(wait)
        _last_req[0] = time.time()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "zh-TW,zh;q=0.9"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            err = e
            time.sleep(2 * (i + 1))
    raise err


def parse_search(page_html):
    """搜尋結果頁 → [{url, title, date}](只取結果清單,不含側欄推薦)。"""
    return [{"url": u, "title": html.unescape(t), "date": d} for u, t, d in _ITEM.findall(page_html)]


def parse_article(page_html):
    """文章頁 → 正文純文字(只取 article_body 段落,不含廣告與側欄;不存檔)。"""
    m = re.search(r'id\s*=\s*"article_body"(.*?)id="story_end"', page_html, re.S)
    if not m:
        return ""
    paras = re.findall(r"<p>(.*?)</p>", m.group(1), re.S)
    out = [html.unescape(re.sub(r"<[^>]+>", "", p)).strip() for p in paras]
    return "\n".join(p for p in out if p)


def _days(a, b):
    return (datetime.strptime(b, "%Y-%m-%d") - datetime.strptime(a, "%Y-%m-%d")).days


def apply_dir(events):
    """dir 規則 ②:沒有前次目標價(① 沒結果)的事件,跟同券商對同檔 365 天內的前一筆比較。
    前一筆 = 日期較早、且不是同一份報告(同目標價 7 天內)的最近一筆;相同 → keep。
    找不到前一筆就保留原本的(③ 關鍵字)。回傳新 list,不改動輸入。"""
    evs = sorted((dict(e) for e in events), key=lambda e: (e["date"], e["code"], e["broker"]))
    last = {}   # (券商, 代號) → 已處理的事件們(舊 → 新)
    for e in evs:
        if e["broker"] == UNNAMED:
            continue
        prevs = last.setdefault((e["broker"], e["code"]), [])
        if e.get("prev_target") is None:
            cands = [p for p in prevs
                     if 0 < _days(p["date"], e["date"]) <= DIR_DAYS
                     and not (p["target"] == e["target"] and _days(p["date"], e["date"]) <= 7)]
            if cands:
                p = cands[-1]
                d = "up" if e["target"] > p["target"] else "down" if e["target"] < p["target"] else "keep"
                if {d, e.get("dir")} != {"up", "down"}:    # 原文關鍵字說上修,規則②卻比出下降(配股前後價格基準不同)→ 以原文為準
                    e["dir"] = d
                    e["prev_target"] = p["target"]
        prevs.append(e)
    return evs


RATIO_MIN, RATIO_MAX = 0.3, 5   # 目標價 ÷ 發布日前一交易日收盤 的合理範圍
DROPPED = []                    # 本次執行被合理性過濾丟掉的 (網址, 代號, 券商, 目標價, 比例)


def make_base_fn():
    """回傳 base_fn(代號, 日期) → 發布日前一交易日收盤(查不到回 None);讀 data/history,逐日快取。"""
    import bisect
    import history
    dates = history.all_dates()
    cache = {}

    def base_fn(code, date):
        i = bisect.bisect_left(dates, date) - 1
        if i < 0:
            return None
        d = dates[i]
        if d not in cache:
            cache[d] = history.load_day(d).get("s") or {}
        row = cache[d].get(code)
        return row[4] if row and len(row) > 4 and row[4] else None
    return base_fn


def ratio(base_fn, code, date, target):
    """目標價 ÷ 前一交易日收盤;沒有 base_fn 或查不到收盤回 None(保留)。"""
    base = base_fn(code, date) if base_fn else None
    return target / base if base else None


def collect(fetch_fn, names, seen, pages, existing, log=print, base_fn=None):
    """抓搜尋頁 → 解析 → (事件 list, seen set, 單篇失敗數, 搜尋頁是否失敗)。fetch_fn(url) → 文字。"""
    idx = build_index(names)
    seen = set(seen)
    events = list(existing)
    fail = 0
    for page in range(1, pages + 1):
        try:
            items = parse_search(fetch_fn(SEARCH.format(page=page)))
        except urllib.error.HTTPError as e:
            if e.code == 404 and page > 1:   # 超過最後一頁,經濟日報回 404
                break
            log("搜尋頁 %d 失敗:%s" % (page, e))
            return events, seen, fail, True
        except Exception as e:  # noqa: BLE001
            log("搜尋頁 %d 失敗:%s" % (page, e))
            return events, seen, fail, True
        if not items:
            break
        for it in items:
            if it["url"] in seen:
                continue
            try:
                found = parse(it["title"], None, idx)
                if needs_body(it["title"], found):
                    body = parse_article(fetch_fn(it["url"]))
                    found = parse(it["title"], body, idx)
            except Exception as e:  # noqa: BLE001
                fail += 1
                log("單篇失敗,略過:%s %s" % (it["url"], e))
                continue
            seen.add(it["url"])
            for f in found:
                r = ratio(base_fn, f["code"], it["date"], f["target"])
                if r is not None and not RATIO_MIN <= r <= RATIO_MAX:
                    DROPPED.append((it["url"], f["code"], f["broker"], f["target"], round(r, 3)))
                    log("合理性過濾丟棄:%s %s %s %s(目標價/收盤 %.2f)" % (it["url"], f["code"], f["broker"], f["target"], r))
                    continue
                events.append({"date": it["date"], "code": f["code"], "broker": f["broker"], "target": f["target"],
                               "rating": f["rating"], "prev_target": f["prev_target"], "dir": f["dir"],
                               "urls": [it["url"]], "title": re.sub(r"<[^>]+>", "", it["title"])})
        if page % 5 == 0:
            log("  已處理 %d 頁,事件 %d" % (page, len(events)))
    return events, seen, fail, False


def _dump(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def build_scores(events):
    """具名券商的紀錄。股價從最舊事件日前約 10 個交易日開始讀。"""
    import broker_stats
    import history
    named = [e for e in events if e["broker"] != UNNAMED]
    if not named:
        return {}
    ds = history.all_dates()
    oldest = min(e["date"] for e in named)
    i = max(0, next((k for k, d in enumerate(ds) if d >= oldest), len(ds)) - 10)
    since = ds[i] if ds else oldest
    closes, dates, taiex = broker_stats.load_closes({e["code"] for e in named}, since)
    return broker_stats.scores(named, closes, dates, taiex)


def save(events, seen, now=None, base_fn=None):
    """合併 → 補 dir → 加 base → 寫 events.json、seen.json、scores.json;回傳存檔的事件。"""
    import broker_stats
    events = apply_dir(broker_stats.merge(events))
    events.sort(key=lambda e: (e["date"], e["broker"], e["code"]))
    for e in events:    # base = 發布日前一交易日收盤(同 broker_stats 的基準價);查不到就不放
        b = base_fn(e["code"], e["date"]) if base_fn else None
        if b:
            e["base"] = round(b, 2)
        else:
            e.pop("base", None)
    _dump(EVENTS, events)
    _dump(SEEN, sorted(seen))
    now = now or datetime.now().strftime("%Y-%m-%d %H:%M")
    _dump(SCORES, {"meta": {"fetched": now, "n": len(events)}, "scores": build_scores(events)})
    return events


def check_events(events, names, base_fn=None):
    """AC-B2 檢查,回傳問題清單(空 = 通過)。"""
    import broker_stats
    bad = []
    if not isinstance(events, list) or not events:
        return ["events.json 不是非空 list"]
    for i, e in enumerate(events):
        tag = "#%d %s %s %s" % (i, e.get("date"), e.get("code"), e.get("broker"))
        for k in ("date", "code", "broker", "target", "urls"):
            if not e.get(k):
                bad.append("%s:缺 %s" % (tag, k))
        if e.get("date") and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(e["date"])):
            bad.append("%s:date 格式不對 %s" % (tag, e["date"]))
        if e.get("code") and e["code"] not in names:
            bad.append("%s:代號不在全市場代號表" % tag)
        t = e.get("target")
        if not isinstance(t, (int, float)) or isinstance(t, bool) or t <= 0:
            bad.append("%s:target 不是正數 %r" % (tag, t))
        us = e.get("urls")
        if not isinstance(us, list) or not all(isinstance(u, str) and urllib.parse.urlparse(u).hostname == "money.udn.com" for u in us):
            bad.append("%s:urls 不是 money.udn.com 網址 list" % tag)
        r = ratio(base_fn, e.get("code"), e.get("date") or "", t) if isinstance(t, (int, float)) and t > 0 else None
        if r is not None and not RATIO_MIN <= r <= RATIO_MAX:
            bad.append("%s:目標價 %s 是前一交易日收盤的 %.2f 倍(合理範圍 %s～%s)" % (tag, t, r, RATIO_MIN, RATIO_MAX))
    if not bad:
        if len(broker_stats.merge(events)) != len(events):
            bad.append("有同券商＋股票＋目標價在 7 天內沒合併的事件")
        for code in ("2330", "2454"):
            n = len({e["broker"] for e in events if e["code"] == code and e["broker"] != UNNAMED})
            if n < 5:
                bad.append("%s 具名券商只有 %d 家(AC-B2 要求至少 5 家)" % (code, n))
    return bad


def main(argv=None):
    ap = argparse.ArgumentParser(description="經濟日報券商目標價新聞")
    ap.add_argument("--backfill", action="store_true", help="抓到最後一頁(預設只抓前 3 頁)")
    ap.add_argument("--check", action="store_true", help="只驗證 events.json")
    a = ap.parse_args(argv)
    names = load_names()
    if a.check:
        bad = check_events(_load(EVENTS, None), names, make_base_fn())
        for b in bad[:50]:
            print("X", b)
        print("檢查%s:%d 個問題" % ("未通過" if bad else "通過", len(bad)))
        return 1 if bad else 0
    base_fn = make_base_fn()
    existing = _load(EVENTS, [])
    seen = set(_load(SEEN, []))
    events, seen, fail, page_fail = collect(fetch, names, seen, MAX_PAGES if a.backfill else DEFAULT_PAGES, existing,
                                         base_fn=base_fn)
    saved = save(events, seen, base_fn=base_fn)
    print("事件 %d(原 %d),單篇失敗 %d,已處理網址 %d,合理性過濾丟棄 %d" % (len(saved), len(existing), fail, len(seen), len(DROPPED)))
    return 1 if page_fail else 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.exit(main())
