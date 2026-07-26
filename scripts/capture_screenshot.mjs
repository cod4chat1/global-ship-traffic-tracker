import path from "node:path";
import fs from "node:fs";
import { chromium } from "playwright";

const [htmlPath, outputPath] = process.argv.slice(2);
if (!htmlPath || !outputPath) {
  throw new Error("Usage: capture_screenshot.mjs <input.html> <output.png>");
}
const browserCandidates = [
  process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
].filter(Boolean);
const executablePath = browserCandidates.find((candidate) => fs.existsSync(candidate));
const launchOptions = { headless: true };
if (executablePath) launchOptions.executablePath = executablePath;
const browser = await chromium.launch(launchOptions);
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
  await page.goto(`file:///${path.resolve(htmlPath).replaceAll("\\", "/")}`, { waitUntil: "load" });
  await page.screenshot({ path: outputPath, fullPage: false });
} finally {
  await browser.close();
}
