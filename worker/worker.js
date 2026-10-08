/* 盤中即時報價代理:證交所 MIS 即時報價 API 不允許瀏覽器跨網域讀取,由這支 Cloudflare Worker 代為讀取並加上 CORS。
   只接受股票代號清單、只轉發到 MIS 這一個網址,不是通用代理。
   GET /?codes=2330,6488  →  {"date":"2026-10-08","time":"13:30:00","s":{"2330":[名稱, 現價, 漲跌%, 成交張數, 時間, 市場]}}
   上市/上櫃不必先知道:每檔同時查 tse_ 與 otc_,MIS 只會回傳存在的那一個。 */

const MIS = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp";
const MAX_CODES = 300;
const CHUNK = 40;            // 每次查 40 檔 = 80 個 ex_ch,網址長度安全
const CACHE_SEC = 10;
const ALLOW = [/^https:\/\/soso99872\.github\.io$/, /^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/];

function num(s) {
  const v = parseFloat(s);
  return isFinite(v) && v > 0 ? v : null;
}

function firstQuote(s) {
  return num(String(s || "").split("_")[0]);
}

function parse(m) {
  const prev = num(m.y);
  // z 是最近一筆成交價;5 秒內沒成交時是 "-",改用前一筆成交 pz,再退而用最佳買價
  const px = num(m.z) || num(m.pz) || firstQuote(m.b) || prev;
  if (!px) return null;
  const chg = prev ? Math.round((px / prev - 1) * 10000) / 100 : 0;
  return [m.n, px, chg, parseInt(m.v, 10) || 0, m.t, m.ex];
}

async function fetchChunk(codes) {
  const exch = codes.map((c) => "tse_" + c + ".tw|otc_" + c + ".tw").join("|");
  const r = await fetch(MIS + "?ex_ch=" + exch + "&json=1&delay=0&_=" + Date.now(), {
    headers: { "User-Agent": "Mozilla/5.0", Referer: "https://mis.twse.com.tw/stock/index.jsp" },
  });
  if (!r.ok) throw new Error("MIS " + r.status);
  const j = await r.json();
  return j.msgArray || [];
}

function cors(req) {
  const o = req.headers.get("Origin") || "";
  return {
    "Access-Control-Allow-Origin": ALLOW.some((re) => re.test(o)) ? o : "https://soso99872.github.io",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    Vary: "Origin",
  };
}

function reply(req, status, body, extra) {
  return new Response(JSON.stringify(body), {
    status,
    headers: Object.assign({ "Content-Type": "application/json; charset=utf-8" }, cors(req), extra || {}),
  });
}

export default {
  async fetch(req, env, ctx) {
    if (req.method === "OPTIONS") return new Response(null, { headers: cors(req) });
    if (req.method !== "GET") return reply(req, 405, { error: "GET only" });
    const url = new URL(req.url);
    const codes = [...new Set((url.searchParams.get("codes") || "").split(",").map((s) => s.trim()))]
      .filter((c) => /^\d{4,6}[A-Z]?$/.test(c))
      .sort();
    if (!codes.length) return reply(req, 400, { error: "codes required" });
    if (codes.length > MAX_CODES) return reply(req, 400, { error: "too many codes (max " + MAX_CODES + ")" });

    // 同一組代號 10 秒內共用結果,避免多人同時開頁面時重複打 MIS
    const key = new Request("https://cache.local/q?codes=" + codes.join(","));
    const cache = caches.default;
    const hit = await cache.match(key);
    if (hit) {
      const body = await hit.text();
      return new Response(body, { headers: Object.assign({ "Content-Type": "application/json; charset=utf-8" }, cors(req)) });
    }

    const chunks = [];
    for (let i = 0; i < codes.length; i += CHUNK) chunks.push(codes.slice(i, i + CHUNK));
    let rows;
    try {
      rows = (await Promise.all(chunks.map(fetchChunk))).flat();
    } catch (e) {
      return reply(req, 502, { error: String(e.message || e) });
    }
    const out = { date: null, time: null, s: {} };
    rows.forEach((m) => {
      if (!m.c) return;
      const v = parse(m);
      if (!v) return;
      out.s[m.c] = v;
      if (m.d && (!out.date || m.d > out.date.replace(/-/g, ""))) out.date = m.d.slice(0, 4) + "-" + m.d.slice(4, 6) + "-" + m.d.slice(6);
      if (m.t && (!out.time || m.t > out.time)) out.time = m.t;
    });
    const body = JSON.stringify(out);
    ctx.waitUntil(cache.put(key, new Response(body, { headers: { "Cache-Control": "max-age=" + CACHE_SEC } })));
    return new Response(body, { headers: Object.assign({ "Content-Type": "application/json; charset=utf-8" }, cors(req)) });
  },
};
