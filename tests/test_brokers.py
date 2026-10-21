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


if __name__ == "__main__":
    unittest.main()
