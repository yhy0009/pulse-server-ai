import { cpSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const source = dirname(fileURLToPath(import.meta.url));

export function buildFrontend(output = join(source, "dist")) {
  const address = (process.env.API_BASE_URL || "").trim().replace(/\/$/, "");
  if (process.env.VERCEL && !address) throw new Error("Set API_BASE_URL to the Render backend origin before building on Vercel.");
  if (address) {
    const url = new URL(address);
    if (!["https:", "http:"].includes(url.protocol) || url.username || url.password || url.search || url.hash || url.pathname !== "/") {
      throw new Error("API_BASE_URL must be an http(s) origin without credentials, /api, query, or fragment.");
    }
    if (process.env.VERCEL && url.protocol !== "https:") throw new Error("Vercel requires an HTTPS backend origin.");
  }
  rmSync(output, { recursive: true, force: true });
  mkdirSync(output, { recursive: true });
  for (const filename of ["index.html", "style.css", "app.js"]) {
    cpSync(join(source, filename), join(output, filename));
  }
  writeFileSync(join(output, "config.js"), `window.APP_CONFIG = ${JSON.stringify({ API_BASE_URL: address }).replaceAll("<", "\\u003c")};\n`);
  console.log("Built static frontend with public API_BASE_URL. No API keys are included.");
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) buildFrontend();
