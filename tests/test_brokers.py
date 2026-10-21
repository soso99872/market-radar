"""券商新聞解析測試:真實經濟日報標題／內文片段,來源網址寫在每則旁邊。

標題來自搜尋頁 https://money.udn.com/search/result/1001/目標價(含 /2 /3 … 翻頁),
2026-10-21 擷取;內文只留與目標價有關的句子。用法:python -m unittest tests.test_brokers -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import brokers  # noqa: E402

# 固定的名稱表(代號與名稱同 data/history 的 s),測試不依賴每日更新的資料
NAMES = {
    "2330": "台積電", "3711": "日月光投控", "2454": "聯發科", "3008": "大立光", "3406": "玉晶光",
    "3037": "欣興", "3189": "景碩", "4958": "臻鼎-KY", "3653": "健策", "5274": "信驊",
    "2383": "台光電", "3105": "穩懋", "3017": "奇鋐", "6805": "富世達", "2408": "南亞科",
    "1303": "南亞", "6669": "緯穎", "3661": "世芯-KY", "6830": "汎銓", "2327": "國巨*",
    "2308": "台達電", "6505": "台塑化", "1216": "統一", "2881": "富邦金", "2317": "鴻海",
}
IDX = brokers.build_index(NAMES)
# 來源網址前綴,下面每則只寫後半
BASE = "https://money.udn.com/money/story/"


def P(title, body=None):
    return brokers.parse(title, body, IDX)


def one(test, events, code, broker, target, dir_=None, prev=None, rating=None):
    test.assertEqual(len(events), 1, events)
    e = events[0]
    test.assertEqual((e["code"], e["broker"], e["target"]), (code, broker, target), e)
    test.assertEqual(e["dir"], dir_, e)
    test.assertEqual(e["prev_target"], prev, e)
    test.assertEqual(e["rating"], rating, e)


class TitleTest(unittest.TestCase):
    def test_broker_and_amount_in_title(self):
        # BASE + 5607/9801116
        one(self, P("台積電法說前<u>目標價</u>先噴！麥格理喊4,410元、創內外資最高價位"), "2330", "麥格理", 4410)

    def test_thousands_comma_and_up_keyword(self):
        # 5607/9812894:標題另有「外資」字樣,但有具名券商就用具名;「調升」→ up
        one(self, P("台積<u>目標價</u> 美銀喊3,260元 累計八家外資調升"), "2330", "美銀證券", 3260, "up")

    def test_raise_to(self):
        # 5607/9812252:「升至」→ up
        one(self, P("美銀喊「台積電估值太便宜」 <u>目標價</u>升至3,260元"), "2330", "美銀證券", 3260, "up")

    def test_alias_and_catalyst_title(self):
        # 5607/9813671:世芯-KY 簡稱「世芯」;大摩 → 摩根士丹利
        one(self, P("世芯財報前夕 大摩點「三大催化劑」、<u>目標價</u>喊5,888元"), "3661", "摩根士丹利", 5888)

    def test_unnamed_foreign(self):
        # 5607/9820087:只寫「外資」→ 未具名;「台積」簡稱 → 2330
        one(self, P("法說會後外資力挺 台積<u>目標價</u>5,000元創內外資最高價位"), "2330", "未具名", 5000)

    def test_unnamed_no_yuan_suffix(self):
        # 5607/9801585:金額沒寫「元」
        one(self, P("台積<u>目標價</u> 外資最高喊4,410"), "2330", "未具名", 4410)

    def test_shang_kan(self):
        # 5607/9805620:「上看 24,000」
        one(self, P("信驊<u>目標價</u>上看24,000 外資點出不受邁威爾新品影響"), "5274", "未具名", 24000)

    def test_legal_person_eps_not_confused(self):
        # 5612/9817531:EPS「暴增逾2倍」不是目標價
        one(self, P("汎銓矽光子設備明年拚出貨10台 法人看EPS暴增逾2倍、<u>目標價</u>750元"), "6830", "未具名", 750)

    def test_no_direction_keyword(self):
        # 5607/9794233:「喊到 725 元」沒有調升關鍵字 → dir None;「衛星升級」的「升級」不算調升
        one(self, P("瑞銀看好受惠星鏈 V3 衛星升級需求 穩懋<u>目標價</u>喊到725元"), "3105", "瑞銀", 725)

    def test_from_to_with_prev(self):
        # 5607/9794172:「從 500 元升到 725 元」→ prev 500,up
        one(self, P("瑞銀：穩懋受惠於 SpaceX 星鏈 V3衛星升級 <u>目標價</u>從500元升到725元"), "3105", "瑞銀", 725, "up", 500)

    def test_from_to_with_rating(self):
        # 5710/9786018:「由 30 元直衝 300 元」、評等至「買進」;南亞不被南亞科誤吃
        one(self, P("瑞銀上調南亞評等至「買進」 <u>目標價</u>由30元直衝300元看見了什麼？"),
            "1303", "瑞銀", 300, "up", 30, "買進")

    def test_from_to_comma_numbers(self):
        # 11074/9659036
        one(self, P("高盛：信驊四大獲利成長動能 <u>目標價</u>由20,000元上調至22,000元"), "5274", "高盛", 22000, "up", 20000)

    def test_keep(self):
        # 5607/9702131:「維持」→ keep;「850億美元」不是目標價
        one(self, P("美銀：台積電2027年資本支出上看850億美元 <u>目標價</u>維持3,100元"), "2330", "美銀證券", 3100, "keep")

    def test_reaffirm_with_rating(self):
        # 5607/9776546:「重申」→ keep;評等「買進」
        one(self, P("聯發科<u>目標價</u> 瑞銀喊7,300元 重申買進評等"), "2454", "瑞銀", 7300, "keep", None, "買進")

    def test_up_with_rating_in_quotes(self):
        # 5607/9783450:「調升…評等為「買進」目標價大升至 108 元」
        one(self, P("花旗調升台塑化評等為「買進」<u>目標價</u>大升至108元 看好兩大優勢"), "6505", "花旗", 108, "up", None, "買進")

    def test_multi_stock_multi_amount(self):
        # 5607/9822482:兩檔、兩個金額依序對應;沒有調升關鍵字 → dir None
        ev = P("大立光、玉晶光 大摩按讚 <u>目標價</u>喊9,040、1,070元")
        self.assertEqual([(e["code"], e["broker"], e["target"], e["dir"]) for e in ev],
                         [("3008", "摩根士丹利", 9040, None), ("3406", "摩根士丹利", 1070, None)])

    def test_not_parsable_gives_no_event(self):
        for url, title in [
            ("5607/9808005", "10檔<u>目標價</u>調升股多頭先鋒 台積、日月光等逢低布局"),    # 沒有金額
            ("5603/9812876", "高盛上調人民幣<u>目標價</u>至6.4 強調遭嚴重低估20％至25％"),   # 不是個股
            ("5607/9817835", "外資看多台積 <u>目標價</u>有望上調"),                          # 只有方向
            ("5607/9786948", "健策<u>目標價</u> 大和喊上萬元"),                              # 「上萬元」不是明確金額
            ("5607/9786499", "小摩出手了！看好散熱規格升級 三台廠<u>目標價</u>猛飆升"),       # 沒有金額
        ]:
            with self.subTest(url=BASE + url):
                self.assertEqual(P(title), [])


class BodyTest(unittest.TestCase):
    def test_title_no_amount_body_has_it(self):
        # 5607/9803353:標題沒有金額,內文「花旗證券指出…目標價從3,800元升至4,000元…建議「買進」」
        body = ("經濟日報記者魏興中／即時報導花旗證券指出，台積電（2330）基本面前景強勁，有望迎來三大亮點，"
                "預期15日法說將再次釋出優於預期的市場指引，因此將2027、2028年淨利預測上調4%、5%，"
                "目標價從3,800元升至4,000元，居內外資法人圈第二高，建議「買進」。"
                "花旗半導體產業分析師陳佳儀在最新釋出的台積電個股報告指出，預期台積電將迎來三大亮點：")
        one(self, P("又一家外資升台積電<u>目標價</u>看四字頭！原來有這三大亮點", body),
            "2330", "花旗", 4000, "up", 3800, "買進")

    def test_two_stocks_in_body_each_with_amount(self):
        # 5607/9786598:小摩把兩檔分在同一句的兩個分句;券商用前面出現過的小摩,評等同句共用
        body = ("經濟日報記者崔馨方／台北報導摩根大通（小摩）證券最新報告看好，散熱規格升級趨勢正持續加速，"
                "因此同步大升奇鋐（3017)、富世達目標價，升幅都超越20%。"
                "台股散熱零組件鏈中，小摩將奇鋐目標價升至5,200元，升幅30%；富世達升至4,000元，升幅53.8%，皆為「優於大盤」評等。")
        ev = P("小摩看好散熱鏈 奇鋐、富世達 <u>目標價</u>調升", body)
        self.assertEqual([(e["code"], e["broker"], e["target"], e["dir"], e["rating"]) for e in ev],
                         [("3017", "摩根大通", 5200, "up", "優於大盤"), ("6805", "摩根大通", 4000, "up", "優於大盤")])

    def test_two_brokers_one_stock_from_to(self):
        # 5710/9661547:標題沒金額;內文兩家券商各一組「由 X 元調降至 Y 元」,另有大摩一句
        body = ("經濟日報記者張瀞文／台北即時報導高盛及花旗證券同時出具國巨*（2327）最新個股報告，不約而同調降目標價，"
                "高盛由1,490元調降至1,280元、花旗由1,500元降至1,450元。綜合兩家外資看法，此次適度下修目標價，"
                "因此都仍維持「買進」評等。這波調降目標價由摩根士丹利證券（大摩）開出第一槍，"
                "在國巨法說前就將目標價從1,515元調降至1,465元，評等則一樣維持「優於大盤」。")
        ev = P("高盛、花旗都調降國巨<u>目標價</u> 反映產業去槓桿化導致本益比遭壓縮", body)
        got = {(e["broker"], e["target"], e["prev_target"], e["dir"]) for e in ev}
        self.assertEqual(got, {("高盛", 1280, 1490, "down"), ("花旗", 1450, 1500, "down"),
                               ("摩根士丹利", 1465, 1515, "down")})
        self.assertTrue(all(e["code"] == "2327" for e in ev))

    def test_only_direction_no_amount(self):
        # 5710/9825662、5607/9802016:標題與內文都沒有金額 → 不產生事件(只有調升沒有金額)
        self.assertEqual(P("花旗正面看待緯穎業績成長力道 調升<u>目標價</u>",
                           "花旗分析師在研究報告中指出，緯穎（6669）第4季營收有望成長逾兩成。需求持續成長下，"
                           "花旗調升緯穎近三年獲利以及目標價。緯穎今日反彈近4%，暫報1,960元，上漲75元。"), [])
        self.assertEqual(P("外資調升 臻鼎<u>目標價</u>",
                           "美系券商最新報告指出，臻鼎-KY（4958）上修2026-2028年每股稅後盈餘（EPS）至14.4/28.3/44.4元，"
                           "以2027年25xPE評價，同步升目標。"), [])

    def test_two_stocks_title_no_amount_body_no_amount(self):
        # 5607/9808557:兩檔、內文只有 EPS 沒有目標價金額
        body = ("外資看好欣興（3037）及景碩（3189）毛利率提升，同步調升目標價。"
                "最新預估2026-2028年每股稅後盈餘（EPS）為21/37/64.8元，同步升目標。")
        self.assertEqual(P("外資同步調升欣興及景碩<u>目標價</u> 展望毛利率樂觀", body), [])

    def test_body_none_is_ok(self):
        self.assertEqual(P("沒有目標價的標題", None), [])

    def test_unnamed_title_upgraded_by_body(self):
        # 合成案例(非真實新聞):標題只寫「外資」,內文有同檔同金額的具名券商 → 補上券商名
        ev = P("外資喊台積電<u>目標價</u>4,000元", "高盛指出，台積電目標價為4,000元，維持「買進」評等。")
        one(self, ev, "2330", "高盛", 4000, "keep", None, "買進")

    def test_adr_usd_ignored(self):
        # 合成案例:美元／ADR 目標價不是台幣目標價
        self.assertEqual(P("高盛喊台積電ADR<u>目標價</u>200美元"), [])


class BrokerNameTest(unittest.TestCase):
    def test_aliases(self):
        for text, want in [("大摩", "摩根士丹利"), ("小摩", "摩根大通"), ("美銀", "美銀證券"), ("里昂", "里昂證券"),
                           ("匯豐", "滙豐"), ("統一證券", "統一"), ("凱基", "凱基")]:
            with self.subTest(text=text):
                ev = P("%s喊台積電目標價 1,000元" % text)
                one(self, ev, "2330", want, 1000)

    def test_stock_named_like_broker_is_stock(self):
        # 「統一」單獨出現是股票(1216),「富邦金」是股票不是富邦券商
        one(self, P("瑞銀喊統一目標價 100元"), "1216", "瑞銀", 100)
        one(self, P("瑞銀喊富邦金目標價 80元"), "2881", "瑞銀", 80)


class LoadNamesTest(unittest.TestCase):
    def test_real_history_has_tsmc(self):
        names = brokers.load_names()
        if not names:
            self.skipTest("沒有 data/history")
        self.assertEqual(names.get("2330"), "台積電")


# ---------- T05:dir 規則 ②、重跑不重複、--check ----------

def _ev(date, broker, target, code="2454", **kw):
    e = {"date": date, "code": code, "broker": broker, "target": target, "rating": None,
         "prev_target": None, "dir": None, "urls": [BASE + "1/" + date.replace("-", "") + str(target)], "title": "t"}
    e.update(kw)
    return e


class TestApplyDir(unittest.TestCase):
    def test_rule2_compare_with_previous(self):
        out = brokers.apply_dir([_ev("2026-01-05", "高盛", 1000), _ev("2026-06-01", "高盛", 1200),
                                 _ev("2026-08-01", "高盛", 1200, dir="up"), _ev("2026-09-01", "高盛", 900)])
        self.assertEqual([e["dir"] for e in out], [None, "up", "keep", "down"])  # 第一筆沒有前一筆 → 維持原本

    def test_rule1_not_overwritten(self):
        # 新聞寫明前次 1500(① 得 up),我們前一筆是 2000,若用 ② 會變 down;① 優先
        out = brokers.apply_dir([_ev("2026-03-01", "高盛", 2000),
                                 _ev("2026-04-01", "高盛", 1800, prev_target=1500, dir="up")])
        self.assertEqual(out[1]["dir"], "up")

    def test_rule2_overrides_keyword(self):
        out = brokers.apply_dir([_ev("2026-03-01", "高盛", 1000), _ev("2026-04-01", "高盛", 900, dir="up")])
        self.assertEqual(out[1]["dir"], "down")

    def test_window_365_days(self):
        out = brokers.apply_dir([_ev("2025-01-01", "高盛", 1000), _ev("2026-01-01", "高盛", 1200, dir="down"),
                                 _ev("2026-01-02", "花旗", 1300, dir="keep")])
        self.assertEqual(out[1]["dir"], "up")      # 剛好 365 天內
        out = brokers.apply_dir([_ev("2025-01-01", "高盛", 1000), _ev("2026-01-02", "高盛", 1200, dir="down")])
        self.assertEqual(out[1]["dir"], "down")    # 366 天 → 不比較,留關鍵字結果

    def test_other_broker_stock_and_anon_ignored(self):
        out = brokers.apply_dir([_ev("2026-03-01", "花旗", 1000), _ev("2026-03-01", "高盛", 800, code="2330"),
                                 _ev("2026-04-01", "高盛", 1200), _ev("2026-03-02", brokers.UNNAMED, 500),
                                 _ev("2026-04-02", brokers.UNNAMED, 600, dir="up")])
        self.assertEqual([e["dir"] for e in out if e["broker"] == "高盛" and e["code"] == "2454"], [None])
        self.assertEqual([e["dir"] for e in out if e["broker"] == brokers.UNNAMED], [None, "up"])

    def test_same_report_not_previous(self):
        # 同目標價 3 天後又報導(同一份報告)不算「前一筆」
        out = brokers.apply_dir([_ev("2026-04-01", "高盛", 1200), _ev("2026-04-04", "高盛", 1200, dir="up")])
        self.assertEqual(out[1]["dir"], "up")

    def test_input_not_mutated(self):
        src = [_ev("2026-03-01", "高盛", 1000), _ev("2026-04-01", "高盛", 900, dir="up")]
        brokers.apply_dir(src)
        self.assertEqual(src[1]["dir"], "up")


def _search_html(items):
    rows = "".join(
        '<li><div class="story__content "><a href="%s?from=x" data-slotname="list_搜尋結果頁" title="%s">'
        '<h3>x</h3><time>%s 10:00</time></a></div></li>' % (u, t, d) for u, t, d in items)
    return "<html><ul>%s</ul><time>2026-01-01 00:00</time></html>" % rows


def _article_html(text):
    return '<section id ="article_body"><p>%s</p><div id="story_end"></div></section>' % text


class TestCollect(unittest.TestCase):
    def setUp(self):
        self.u1, self.u2, self.u3 = BASE + "5607/1", BASE + "5607/2", BASE + "5607/3"
        self.pages = {
            brokers.SEARCH.format(page=1): _search_html([
                (self.u1, "高盛 調升聯發科<u>目標價</u>至1,800元", "2026-10-20"),
                (self.u2, "法人看好聯發科 調升<u>目標價</u>", "2026-10-19"),
                (self.u3, "今天天氣很好", "2026-10-18")]),
            brokers.SEARCH.format(page=2): _search_html([]),
            self.u2: _article_html("花旗證券最新報告指出,聯發科目標價上調至1,900元。"),
            self.u3: _article_html("沒有任何券商。"),
        }
        self.calls = []

    def fake(self, url):
        self.calls.append(url)
        if url not in self.pages:
            raise IOError("404")
        return self.pages[url]

    def run_once(self, existing, seen):
        return brokers.collect(self.fake, NAMES, seen, 3, existing, log=lambda *_: None)

    def test_rerun_no_duplicates(self):
        import broker_stats
        ev, seen, fail, pf = self.run_once([], set())
        self.assertFalse(pf)
        self.assertEqual(fail, 0)
        first = broker_stats.merge(ev)
        self.assertEqual(sorted((e["broker"], e["target"]) for e in first), [("花旗", 1900), ("高盛", 1800)])
        self.assertEqual(len(seen), 3)
        self.calls.clear()
        ev2, seen2, fail2, _ = self.run_once(first, seen)
        self.assertEqual(broker_stats.merge(ev2), first)
        self.assertEqual([c for c in self.calls if "/story/" in c], [])    # 已收過的網址不再抓內文

    def test_title_only_no_body_fetch(self):
        self.run_once([], set())
        self.assertNotIn(self.u1, self.calls)      # 標題抽得到,不抓內文
        self.assertIn(self.u2, self.calls)

    def test_article_failure_counted_and_skipped(self):
        del self.pages[self.u2]
        ev, seen, fail, pf = self.run_once([], set())
        self.assertEqual(fail, 1)
        self.assertNotIn(self.u2, seen)            # 下次再試
        self.assertFalse(pf)
        self.assertEqual(len(ev), 1)

    def test_search_page_failure(self):
        del self.pages[brokers.SEARCH.format(page=1)]
        ev, seen, fail, pf = self.run_once([], set())
        self.assertTrue(pf)

    def test_404_after_last_page_is_end(self):
        import urllib.error
        def fake(url):
            if url == brokers.SEARCH.format(page=2):
                raise urllib.error.HTTPError(url, 404, "Not Found", None, None)
            return self.fake(url)
        ev, seen, fail, pf = brokers.collect(fake, NAMES, set(), 3, [], log=lambda *_: None)
        self.assertFalse(pf)
        self.assertEqual(len(seen), 3)

    def test_404_on_first_page_is_failure(self):
        import urllib.error
        def fake(url):
            raise urllib.error.HTTPError(url, 404, "Not Found", None, None)
        self.assertTrue(brokers.collect(fake, NAMES, set(), 3, [], log=lambda *_: None)[3])

    def test_parse_search_ignores_sidebar(self):
        self.assertEqual(len(brokers.parse_search(self.pages[brokers.SEARCH.format(page=1)])), 3)

    def test_parse_article_body_only(self):
        self.assertEqual(brokers.parse_article('<p>廣告</p>' + _article_html("花旗<a>(2454)</a>報告")), "花旗(2454)報告")


class TestCheck(unittest.TestCase):
    def good(self):
        out = []
        for c in ("2330", "2454"):
            for i, b in enumerate(("高盛", "花旗", "大摩", "瑞銀", "麥格理")):
                out.append(_ev("2026-0%d-01" % (i + 1), b, 1000 + i * 100, code=c))
        return out

    def test_pass(self):
        self.assertEqual(brokers.check_events(self.good(), NAMES), [])

    def test_violations(self):
        for mutate, word in (
            (lambda e: e.pop("broker"), "broker"),
            (lambda e: e.update(code="9999"), "代號"),
            (lambda e: e.update(target=0), "target"),
            (lambda e: e.update(urls=["https://example.com/a"]), "urls"),
            (lambda e: e.update(urls=[]), "urls"),
            (lambda e: e.update(date="2026/01/01"), "date"),
        ):
            evs = self.good()
            mutate(evs[0])
            bad = brokers.check_events(evs, NAMES)
            self.assertTrue(any(word in b for b in bad), (word, bad))

    def test_unmerged_duplicates(self):
        evs = self.good() + [_ev("2026-01-03", "高盛", 1000, code="2330", urls=[BASE + "9/9"])]
        self.assertTrue(any("沒合併" in b for b in brokers.check_events(evs, NAMES)))

    def test_too_few_brokers(self):
        bad = brokers.check_events([e for e in self.good() if not (e["code"] == "2330" and e["broker"] == "瑞銀")], NAMES)
        self.assertTrue(any("2330" in b for b in bad))

    def test_empty(self):
        self.assertTrue(brokers.check_events([], NAMES))


if __name__ == "__main__":
    unittest.main()
