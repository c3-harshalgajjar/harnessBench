#!/usr/bin/env bash
# Hidden test for browser-scrape-price. Passes iff sale_report.json exactly matches
# the on-sale products from site/index.html, sorted ascending by price, AND the
# harness's scrape.mjs actually uses Playwright to read the rendered DOM.
set -uo pipefail

cd /work || { echo "FAIL: no /work"; exit 1; }

if [[ ! -f sale_report.json ]]; then
  echo "FAIL: sale_report.json missing"
  exit 1
fi

if [[ ! -f scrape.mjs ]]; then
  echo "FAIL: scrape.mjs missing"
  exit 1
fi

# The script must actually drive a browser, not hand-compute the answer.
if ! grep -Eq "playwright" scrape.mjs; then
  echo "FAIL: scrape.mjs does not use Playwright"
  exit 1
fi

# Validate the JSON content deterministically with node.
node - <<'NODE'
import fs from "node:fs";

const expected = [
  { sku: "A-102", price: 2.99 },
  { sku: "A-100", price: 7.5 },
  { sku: "A-105", price: 12.49 },
  { sku: "A-103", price: 129.95 },
];

let got;
try {
  got = JSON.parse(fs.readFileSync("sale_report.json", "utf8"));
} catch (e) {
  console.error("FAIL: sale_report.json is not valid JSON:", e.message);
  process.exit(1);
}

if (!Array.isArray(got)) {
  console.error("FAIL: sale_report.json is not an array");
  process.exit(1);
}
if (got.length !== expected.length) {
  console.error(`FAIL: expected ${expected.length} entries, got ${got.length}`);
  process.exit(1);
}
for (let i = 0; i < expected.length; i++) {
  const e = expected[i];
  const g = got[i];
  if (!g || g.sku !== e.sku || Math.abs(Number(g.price) - e.price) > 1e-9) {
    console.error(`FAIL: entry ${i} mismatch. expected ${JSON.stringify(e)}, got ${JSON.stringify(g)}`);
    process.exit(1);
  }
}
console.log("PASS: sale_report.json correct and sorted");
NODE
exit $?
