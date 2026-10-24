// 建議頁（advice.html）的判斷區、訊號區規則：純函式、只吃傳入的資料（PRD 8.7）。
(function () {
  "use strict";
  var PCT_TH = 0.5, FLOW_TH = 50; // 方向門檻：漲跌幅 ±0.5%、三大法人合計 ±50 億
  var GRADES = ["強", "中", "反向"]; // 訊號區只列證據強度這三級（10 日）
  var STRAT = [["star4", "4★ 以上", "評級 4★ 以上・每月一籃"], ["star5", "5★", "評級 5★・每月一籃"]];

  function rnd(x, k) { var p = Math.pow(10, k); return Math.floor(x * p + 0.5) / p; }
  function num(v, dec) {
    var s = Math.abs(v).toFixed(dec).split(".");
    s[0] = s[0].replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    return (v < 0 ? "-" : "") + s.join(".");
  }
  function sgn(v, dec) { var s = num(v, dec); return s.charAt(0) === "-" ? s : "+" + s; }
  function md(d) { var a = d.split("-"); return parseInt(a[1], 10) + "/" + parseInt(a[2], 10); }
  function has(v) { return v !== null && v !== undefined; }
  function isObj(v) { return !!v && typeof v === "object" && Object.keys(v).length > 0; }
  function addDays(d, n) {
    var a = d.split("-");
    return new Date(Date.UTC(+a[0], +a[1] - 1, +a[2] + n)).toISOString().slice(0, 10);
  }

  function item(rep, sym) {
    var gs = rep.markets || [];
    for (var i = 0; i < gs.length; i++) {
      var its = gs[i].items || [];
      for (var j = 0; j < its.length; j++) if (its[j].symbol === sym) return its[j];
    }
    return null;
  }

  function judge(rep) {
    var D = rep.date, src = md(D) + " 晨報", parts = [], votes = [], i;
    var pairs = [["^SOX", "費半"], ["TSM", "台積電 ADR"]];
    for (i = 0; i < pairs.length; i++) {
      var it = item(rep, pairs[i][0]);
      if (it && has(it.change_pct)) {
        var p = it.change_pct;
        parts.push(pairs[i][1] + " " + sgn(p, 2) + "%" + (it.as_of ? "（" + md(it.as_of) + "）" : ""));
        votes.push(p >= PCT_TH ? 1 : p <= -PCT_TH ? -1 : 0);
      }
    }
    var f = rep.tw_flows || {};
    if (f.date && has(f.foreign) && has(f.trust) && has(f.dealer)) {
      var tot = rnd(f.foreign + f.trust + f.dealer, 2);
      parts.push(md(f.date) + " 三大法人合計" + (tot > 0 ? "買超" : tot < 0 ? "賣超" : "持平") + " " + num(Math.abs(tot), 2) + " 億");
      votes.push(tot >= FLOW_TH ? 1 : tot <= -FLOW_TH ? -1 : 0);
    }
    var dir = null;
    if (votes.length >= 2) {
      var up = 0, dn = 0, zero = 0;
      for (i = 0; i < votes.length; i++) { if (votes[i] === 1) up++; else if (votes[i] === -1) dn++; else zero++; }
      var sc = up - dn;
      dir = {
        label: sc >= 2 ? "偏多" : sc <= -2 ? "偏空" : "中性", text: parts.join("、"),
        tally: "偏多 " + up + " 項、偏空 " + dn + " 項、持平 " + zero + " 項", src: src
      };
    }
    // 今天要盯的一個點：今天的台股財報 → 今天重要程度高的經濟日曆 → 加權近 15 日低點／高點
    var watch = null, er = [], cal = [], e, c;
    var es = rep.earnings || [], cs = rep.calendar || [];
    for (i = 0; i < es.length; i++) if (es[i].date === D && es[i].name && es[i].region === "台") er.push(es[i]);
    for (i = 0; i < cs.length; i++) if (cs[i].date === D && cs[i].event && cs[i].importance === "高") cal.push([cs[i], i]);
    cal.sort(function (a, b) {
      var ta = a[0].time || "99:99", tb = b[0].time || "99:99";
      return ta < tb ? -1 : ta > tb ? 1 : a[1] - b[1];
    });
    if (er.length) {
      e = er[0];
      watch = { text: e.name + (e.timing || "財報"), basis: "排在今天（" + md(D) + "）的台股財報與法說", src: src };
    } else if (cal.length) {
      c = cal[0][0];
      watch = { text: c.event + (c.time ? " " + c.time : ""), basis: "排在今天（" + md(D) + "）、重要程度高的經濟日曆事件", src: src };
    } else {
      var tw = item(rep, "^TWII"), adr = item(rep, "TSM"), sp = [];
      var raw = (tw && tw.spark) || [];
      for (i = 0; i < raw.length; i++) if (has(raw[i])) sp.push(raw[i]);
      if (sp.length) {
        var ap = adr ? adr.change_pct : undefined;
        var down = has(ap) && ap < 0;
        var v = down ? Math.min.apply(null, sp) : Math.max.apply(null, sp);
        var b = "加權指數近 " + sp.length + " 個交易日收盤" + (tw.as_of ? "（至 " + md(tw.as_of) + "）" : "") + "；";
        if (!has(ap)) b += "台積電 ADR 沒有資料，看高點";
        else b += "台積電 ADR " + sgn(ap, 2) + "%" + (adr.as_of ? "（" + md(adr.as_of) + "）" : "") + (down ? "，下跌看低點" : "，沒有下跌看高點");
        watch = { text: "加權指數近 " + sp.length + " 日收盤" + (down ? "低點" : "高點") + " " + num(v, 0), basis: b, src: src };
      }
    }
    return { date: D, dir: dir, watch: watch };
  }

  function stratRow(key, ck, name, curve, d, advice) {
    var c = (curve || {})[ck];
    if (!c || !(c.eq && c.eq.length)) return null;
    var eq = c.eq, rs = [], prev = 1, last = null, i, state, st;
    // 不偷看未來：每一期要到「下一期進場日」（最後一期用進場日 +31 天）不晚於資料日，才算結算完成
    for (i = 0; i < eq.length; i++) {
      var end = i + 1 < eq.length ? eq[i + 1][0] : addDays(eq[i][0], 31);
      if (end <= d) { rs.push(eq[i][1] / prev - 1); last = eq[i][0]; }
      prev = eq[i][1];
    }
    var stats = null;
    if (rs.length) {
      var wins = 0, sum = 0;
      for (i = 0; i < rs.length; i++) { if (rs[i] > 0) wins++; sum += rs[i]; }
      stats = { win: rnd(100 * wins / rs.length, 1), avg: rnd(100 * sum / rs.length, 2), n: rs.length, span: [eq[0][0], last] };
    }
    if (d < eq[0][0]) {
      state = "空手"; st = "回測第一籃 " + eq[0][0] + " 才進場，資料日之前沒有持有";
    } else {
      var a = d.split("-"), m = +a[1];
      if (+a[2] < 12) m = m === 1 ? 12 : m - 1;
      var m2 = m === 12 ? 1 : m + 1;
      state = "持有"; st = m + " 月這一籃（約 " + m + "/12 起）；下次換股約 " + m2 + "/12";
    }
    return { key: key, name: name, kind: "strategy", grade: null, state: state, state_text: st, stats: stats,
      mdd: has(c.mdd) ? c.mdd : null, link: "strategy.html", advice: advice };
  }

  function watchCount(key, W) {
    var n = 0, i;
    if (key === "w_stretch") return [W.counts.stretch, "檔"];
    if (key === "w_pick") return [W.counts.picks, "檔"];
    if (key === "w_dump") return [W.counts.dump, "檔"];
    if (key === "w_theme_bottom") {
      for (i = 0; i < W.themes.length; i++) if (W.themes[i].bottom) n++;
      return [n, "個板塊"];
    }
    if (key === "w_theme_out") {
      for (i = 0; i < W.themes.length; i++) if (W.themes[i].state === "流出") n++;
      return [n, "個板塊"];
    }
    return [null, null];
  }

  function signals(S) {
    var T = S.today, ST = S.stats, W = S.watch, curve = S.curve, regime = S.regime || {};
    var d = T.date, rows = [], i;
    // 部位建議只放在 4★ 這一條（對應策略績效頁回測過的規則）
    var c4 = (curve || {})["4★ 以上"] || {};
    var adv = ["分散買，單檔不超過可投入金額的 1/10，只用虧得起的錢：從名單只買 1 檔，約 18% 的機率 60 日內虧超過 15%；分散買 10 檔降到約 5%。"];
    if (has(c4.mdd)) adv.push("回測最大回撤 " + num(c4.mdd, 1) + "%：要能接受帳面上虧掉這麼多，才適合照這個方法操作。");
    var g = (regime["5★ · 大盤空頭"] || {}).is;
    if ((T.regime_now || "").indexOf("空頭") === 0 && isObj(g) && has(g.med60) && has(g.crash)) {
      adv.push("目前加權指數在 60 日均線之下（空頭）：歷史上空頭時的 5★，60 日中位數 " + sgn(g.med60, 1) + "%、60 日內曾跌 25% 的有 " +
        rnd(g.crash, 0).toFixed(0) + "%（多頭時約 14–23%），宜降低投入或分批。");
    }
    adv.push("有財務地雷的股票（見個股健檢）中途大跌的機率約高 1.5–2.5 倍；評級沒有扣分，投入金額宜更少。");
    adv.push("不靠單檔停損控制風險：每檔各設 15% 停損的回測反而更差（大盤急跌時全部同時停損，剛好賣在低點），風險用投入金額控制。");
    for (i = 0; i < STRAT.length; i++) {
      var r = stratRow(STRAT[i][0], STRAT[i][1], STRAT[i][2], curve, d, STRAT[i][0] === "star4" ? adv : []);
      if (r) rows.push(r);
    }
    var sigs = ST.signals || {}, keys = [], all = Object.keys(sigs);
    for (i = 0; i < all.length; i++) {
      var h0 = (sigs[all[i]].horizons || {})["10"] || {};
      if (GRADES.indexOf(h0.grade) >= 0) keys.push([all[i], i]);
    }
    keys.sort(function (a, b) {
      var ga = GRADES.indexOf(sigs[a[0]].horizons["10"].grade), gb = GRADES.indexOf(sigs[b[0]].horizons["10"].grade);
      return ga - gb || a[1] - b[1];
    });
    var peek = (ST.span || [null, null])[1];
    for (i = 0; i < keys.length; i++) {
      var k = keys[i][0], s = sigs[k], h = s.horizons["10"], a = h.all || {};
      var cnt, unit, sd, state, st;
      if (s.group === "watch") {
        if (W && W.date && W.date <= d) { var wc = watchCount(k, W); cnt = wc[0]; unit = wc[1]; sd = W.date; }
        else { cnt = null; unit = null; sd = null; }
      } else if (k === "sector_flip") {
        cnt = (T.sector_flips || []).length; unit = "個板塊"; sd = d;
      } else {
        cnt = ((T.hits || {})[k] || []).length; unit = "檔"; sd = d;
      }
      if (!has(cnt)) { state = null; st = "沒有資料日當天或以前的名單"; }
      else { state = cnt > 0 ? "觸發" : "未觸發"; st = cnt + " " + unit + "（" + md(sd) + " 收盤）"; }
      var stats = null;
      if (peek && peek <= d && a.n) stats = { win: a.win, avg: a.avg_rel, n: a.n, span: ST.span };
      rows.push({ key: k, name: s.name, kind: "signal", grade: h.grade, state: state, state_text: st, stats: stats,
        mdd: null, link: "signals.html", advice: [] });
    }
    return { date: d, rows: rows };
  }

  window.MRAdvice = { judge: judge, signals: signals };
})();
