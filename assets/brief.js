/* 晨報新版面的組字邏輯:MRBrief.build(reports) 由晨報 JSON 算出標題、一句法人、4 個重點數字與時間軸文字(純函式、不碰 DOM) */
(function () {
  "use strict";

  var WEEK = "一二三四五六日";
  var SHORT = [["^SOX", "費半"], ["TSM", "台積電 ADR"], ["^IXIC", "那斯達克"], ["^GSPC", "S&P 500"], ["^DJI", "道瓊"]];

  function has(v) { return v != null; }
  function sg(v) { return v > 0 ? 1 : v < 0 ? -1 : 0; }
  function md(d) { var p = d.split("-"); return parseInt(p[1], 10) + "/" + parseInt(p[2], 10); }
  function wd(d) {
    var p = d.split("-");
    var w = new Date(Date.UTC(+p[0], +p[1] - 1, +p[2])).getUTCDay(); // 0=日
    return WEEK.charAt((w + 6) % 7);
  }
  // 千分位並固定小數位;負零也帶負號(同 Python 的 f"{v:,.nf}")
  function num(v, dec) {
    var neg = v < 0 || (v === 0 && 1 / v < 0);
    var s = Math.abs(v).toFixed(dec).split(".");
    s[0] = s[0].replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    return (neg ? "-" : "") + s.join(".");
  }
  function sgn(v, dec) { var s = num(v, dec); return s.charAt(0) === "-" ? s : "+" + s; }
  function ab(v, dec) { return num(Math.abs(v), dec); }

  function item(rep, sym) {
    var gs = rep.markets || [];
    for (var i = 0; i < gs.length; i++) {
      var its = gs[i].items || [];
      for (var j = 0; j < its.length; j++) if (its[j].symbol === sym) return its[j];
    }
    return null;
  }

  function streakCtx(it) {
    var sp = (it.spark || []).filter(has);
    if (sp.length < 2) return "晨報沒有近期走勢";
    var n = 0, s = 0;
    for (var i = sp.length - 1; i > 0; i--) {
      var ds = sg(sp[i] - sp[i - 1]);
      if (ds === 0 || (s && ds !== s)) break;
      s = ds;
      n++;
    }
    if (n >= 2) return "連 " + n + " 天" + (s > 0 ? "漲" : "跌");
    var p = (sp[sp.length - 1] / sp[0] - 1) * 100;
    if (Number(p.toFixed(1)) === 0) return (sp.length - 1) + " 個交易日持平";
    return (sp.length - 1) + " 個交易日" + (p > 0 ? "漲" : "跌") + " " + ab(p, 1) + "%";
  }

  function priceKpi(rep, sym, label) {
    var it = item(rep, sym);
    if (!it || !has(it.last)) return { label: label, value: "—", chg: "", ctx: "晨報沒有這項資料" };
    var dec = it.decimals === undefined ? 2 : it.decimals;
    var chg = "";
    if (has(it.change) && has(it.change_pct)) chg = sgn(it.change, dec) + " (" + sgn(it.change_pct, 2) + "%)";
    var ctx = streakCtx(it);
    if (sym === "TSM" && has(rep.tsm_adr_premium_pct)) {
      var p = rep.tsm_adr_premium_pct;
      ctx = "對台股現股" + (p >= 0 ? "溢價" : "折價") + " " + ab(p, 2) + "%";
    }
    return { label: label, value: num(it.last, dec), chg: chg, ctx: ctx, asof: it.as_of ? md(it.as_of) : "" };
  }

  function bs(x) { return x > 0 ? "買超" : x < 0 ? "賣超" : "持平"; }

  function foreignKpi(reps) {
    var f0 = reps[0].tw_flows || {};
    var v = f0.foreign;
    if (!has(v)) return { label: "外資買賣超", value: "—", chg: "", ctx: "晨報沒有這項資料" };
    var s = sg(v), n = 1, first = f0.date, prev = null;
    for (var i = 0; i < reps.length - 1; i++) {
      var a = reps[i].tw_flows || {}, b = reps[i + 1].tw_flows || {};
      if (!a.date || reps[i + 1].date !== a.date || !has(b.foreign)) break;
      if (i === 0) prev = b;
      var bv = b.foreign;
      if (s === 0 || sg(bv) !== s) break;
      n++;
      first = b.date;
    }
    var ctx;
    if (n >= 2) ctx = md(first) + " 起連 " + n + " 天" + bs(v);
    else if (prev) ctx = "前一天 " + md(prev.date) + " " + bs(prev.foreign) + " " + num(Math.abs(prev.foreign), 0) + " 億";
    else ctx = "前一交易日不在晨報紀錄";
    return { label: "外資買賣超", value: sgn(v, 2), chg: md(f0.date) + " 外資" + bs(v), ctx: ctx, asof: md(f0.date) };
  }

  function events(rep) {
    var out = [], i;
    var cal = (rep.calendar || []).map(function (c, k) { return { c: c, k: k }; });
    cal.sort(function (x, y) {
      var a = x.c.time || "99:99", b = y.c.time || "99:99";
      return a < b ? -1 : a > b ? 1 : x.k - y.k;
    });
    for (i = 0; i < cal.length; i++) {
      var c = cal[i].c;
      if (c.date && c.event) out.push({ date: c.date, text: c.event + (c.time ? " " + c.time : ""), high: c.importance === "高", tw: false });
    }
    var er = rep.earnings || [];
    for (i = 0; i < er.length; i++) {
      var e = er[i];
      if (e.date && e.name) out.push({ date: e.date, text: e.name + (e.timing || "財報"), high: false, tw: e.region === "台", kind: "earn", name: e.name });
    }
    return out;
  }

  function build(reps) {
    var r = reps[0];
    var D = r.date;
    var ev = events(r);
    var i, j;
    // 標題前半:五項美股與台積電 ADR 取漲跌幅絕對值最大的兩項
    var mv = [];
    for (i = 0; i < SHORT.length; i++) {
      var it0 = item(r, SHORT[i][0]);
      if (it0 && has(it0.change_pct)) mv.push({ a: Math.abs(it0.change_pct), n: SHORT[i][1], p: it0.change_pct, k: i });
    }
    mv.sort(function (x, y) { return (y.a - x.a) || (x.k - y.k); });
    var parts = [];
    for (i = 0; i < mv.length && i < 2; i++) {
      var n = mv[i].n, p = mv[i].p;
      var sp_ = n.charCodeAt(n.length - 1) < 128 ? n + " " : n;
      parts.push(sp_ + (p > 0 ? "漲" : p < 0 ? "跌" : "平盤") + (p ? " " + ab(p, 2) + "%" : ""));
    }
    var head = parts.join("、");
    // 標題後半:今天要盯的一件事或一個點位
    var watch = null;
    var tw = ev.filter(function (e) { return e.date === D && e.tw; });
    var hi = ev.filter(function (e) { return e.date === D && e.high; });
    if (tw.length) watch = tw[0].text;
    else if (hi.length) watch = hi[0].text;
    else {
      var twIt = item(r, "^TWII"), adr = item(r, "TSM");
      var sp = ((twIt || {}).spark || []).filter(has);
      if (sp.length) {
        var down = adr !== null && (adr.change_pct || 0) < 0;
        watch = "加權近 15 日" + (down ? "低點" : "高點") + " " + num(down ? Math.min.apply(null, sp) : Math.max.apply(null, sp), 0);
      }
    }
    var title = head + (watch ? "，今天先看" + watch : "");
    // 標題下一句:三大法人
    var f = r.tw_flows || {};
    var lede = "";
    if (f.date && has(f.foreign) && has(f.trust) && has(f.dealer)) {
      var tot = f.foreign + f.trust + f.dealer;
      lede = md(f.date) + " 三大法人合計" + (tot > 0 ? "買超" : "賣超") + " " + ab(tot, 2) + " 億：外資 " + sgn(f.foreign, 2) +
        "、投信 " + sgn(f.trust, 2) + "、自營商 " + sgn(f.dealer, 2);
    }
    var ga = r.generated_at || "";
    var asof = ga.length >= 16 ? "資料截至 " + ga.slice(11, 16) : "";
    var kpis = [priceKpi(r, "^TWII", "加權指數"), priceKpi(r, "^SOX", "費城半導體"), priceKpi(r, "TSM", "台積電 ADR"), foreignKpi(reps)];
    var set = {};
    set[D] = 1;
    for (i = 0; i < ev.length; i++) if (ev[i].date > D) set[ev[i].date] = 1;
    var days = Object.keys(set).sort().slice(0, 6);
    var tl = [];
    for (i = 0; i < days.length; i++) {
      var d = days[i];
      var cal = ev.filter(function (e) { return e.date === d && !e.kind; }).map(function (e) { return e.text; });
      var its = [];
      for (j = 0; j < ev.length; j++) {
        var e = ev[j];
        if (e.date !== d) continue;
        if (e.kind === "earn") {
          var key = e.name.split("(")[0];
          if (cal.some(function (c) { return c.indexOf(key) >= 0; })) continue;
        }
        its.push({ text: e.text, high: e.high });
      }
      tl.push({ date: md(d), wd: wd(d), today: d === D, items: its.slice(0, 3), more: Math.max(0, its.length - 3) });
    }
    return { date: D, title: title, lede: lede, asof: asof, kpis: kpis, timeline: tl };
  }

  window.MRBrief = { build: build };
})();
