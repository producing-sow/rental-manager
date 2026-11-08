const { chromium } = require("playwright");

const BASE = process.env.BASE_URL || "http://127.0.0.1:8849";

(async () => {
  const browser = await chromium.launch({
    headless: true,
    args: ["--no-sandbox"],
    ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}),
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
  const suffix = Date.now().toString().slice(-7);
  const today = new Date();
  const month = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}`;

  const property = await (
    await page.request.post(`${BASE}/api/properties`, {
      data: { name: `成本台账测试${suffix}`, address: "成本台账测试地址" },
    })
  ).json();
  const room = await (
    await page.request.post(`${BASE}/api/rooms`, {
      data: {
        property_id: property.id,
        room_no: "301",
        rent: 260,
        electric_rate: 1,
        water_rate: 5,
        billing_day: 19,
        status: "rented",
      },
    })
  ).json();
  const draft = await (
    await page.request.post(`${BASE}/api/rooms/${room.id}/bills/new`, {
      data: {
        custom_dates: true,
        start_date: `${month}-01`,
        end_date: `${month}-28`,
        issue_date: `${month}-08`,
        ledger_month: month,
      },
    })
  ).json();
  await page.request.put(`${BASE}/api/bills/${draft.bill.id}`, {
    data: { prev_electric: 100, current_electric: 110, prev_water: 20, current_water: 22 },
  });
  await page.request.post(`${BASE}/api/bills/${draft.bill.id}/confirm`, {
    data: { payment_status: "paid" },
  });

  await page.goto(`${BASE}/#/ledger`, { waitUntil: "networkidle" });
  await page.locator('[data-action="cost-add"]').first().click();
  await page.locator("#costProperty").selectOption(String(property.id));
  await page.locator("#costElectricityAmount").fill("120");
  await page.locator("#costWaterAmount").fill("30");
  const otherRows = page.locator(".other-cost-row");
  await otherRows.first().locator("[data-cost-name]").fill("修水管");
  await otherRows.first().locator("[data-cost-amount]").fill("50");
  await page.locator("[data-add-other-cost]").click();
  await otherRows.nth(1).locator("[data-cost-name]").fill("清洁费");
  await otherRows.nth(1).locator("[data-cost-amount]").fill("20");

  if (!(await page.locator("#costEntryTotal").innerText()).includes("-¥220.00")) {
    throw new Error("本月支出合计不正确");
  }
  await page.locator("[data-save-cost]").click();
  await page.locator(".modal-card").waitFor({ state: "detached", timeout: 10000 });
  await page.waitForTimeout(600);

  const ledger = await (
    await page.request.get(`${BASE}/api/ledger?month=${month}`)
  ).json();
  const row = ledger.properties.find((item) => item.property_id === property.id);
  if (
    row.electric_cost_cents !== 12000 ||
    row.water_cost_cents !== 3000 ||
    row.other_cost_cents !== 7000
  ) {
    throw new Error(`成本保存不正确：${JSON.stringify(row)}`);
  }
  const text = await page.locator(".ledger-property-table").innerText();
  for (const expected of ["房租", "水电收入", "水电支出", "其他支出", "-¥150.00", "-¥70.00"]) {
    if (!text.includes(expected)) throw new Error(`台账缺少内容：${expected}`);
  }

  console.log(JSON.stringify({ ok: true, electricity: 120, water: 30, other: 70 }));
  await browser.close();
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
