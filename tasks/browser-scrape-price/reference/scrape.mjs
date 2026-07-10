import { chromium } from "playwright";
import { fileURLToPath } from "node:url";
import path from "node:path";
import fs from "node:fs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const pageUrl = "file://" + path.join(__dirname, "site", "index.html");

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();
await page.goto(pageUrl);

const sales = await page.$$eval(".product.on-sale", (cards) =>
  cards.map((c) => ({
    sku: c.getAttribute("data-sku"),
    price: parseFloat(c.querySelector(".price").textContent.replace(/[^0-9.]/g, "")),
  }))
);

sales.sort((a, b) => a.price - b.price);
fs.writeFileSync(path.join(__dirname, "sale_report.json"), JSON.stringify(sales, null, 2) + "\n");
await browser.close();
