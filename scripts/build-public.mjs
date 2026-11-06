// 把網站真的會載入的檔案複製到 dist/，Cloudflare Pages 只發布 dist/（原始碼、腳本、排程設定不公開）。
// 用白名單：新增網頁要用的檔案時，記得加進下面的清單，不然線上會 404。
// 用法：node scripts/build-public.mjs（不需要安裝任何套件）
import { cpSync, existsSync, mkdirSync, readdirSync, rmSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const out = join(root, "dist");

// 根目錄：所有 .html 加上這幾個檔
const rootFiles = [
  ...readdirSync(root).filter((f) => f.endsWith(".html")),
  "manifest.webmanifest",
  ".nojekyll",
];
// 整個資料夾複製，但只收這些副檔名
const dirs = {
  assets: [".js", ".css", ".png", ".svg"],
  data: [".json", ".json.gz"],
};

rmSync(out, { recursive: true, force: true });
mkdirSync(out);
for (const f of rootFiles) {
  if (!existsSync(join(root, f))) throw new Error("找不到 " + f);
  cpSync(join(root, f), join(out, f));
}
for (const [d, exts] of Object.entries(dirs)) {
  cpSync(join(root, d), join(out, d), {
    recursive: true,
    filter: (src) => {
      const name = src.split(/[\\/]/).pop();
      if (name.startsWith(".")) return false;
      return statSync(src).isDirectory() || exts.some((e) => name.endsWith(e));
    },
  });
}

let n = 0;
(function count(p) { for (const e of readdirSync(p, { withFileTypes: true })) e.isDirectory() ? count(join(p, e.name)) : n++; })(out);
console.log("dist/ 完成：" + n + " 個檔案");
