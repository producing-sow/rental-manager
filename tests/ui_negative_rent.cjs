const { chromium } = require("playwright");

const BASE = process.env.BASE_URL || "http://127.0.0.1:8849";

(async () => {
  const browser = await chromium.launch({
    headless: true,
    args: ["--no-sandbox"],
    ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}),
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const suffix = Date.now().toString().slice(-7);
  const today = new Date();
  const month = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}`;

  const property = await (
    await page.request.post(`${BASE}/api/properties`, {
      data: { name: `负数房租测试${suffix}`, address: "负数房租测试地址" },
    })
  ).json();
  const room = await (
    await page.request.post(`${BASE}/api/rooms`, {
      data: {
        property_id: property.id,
        room_no: `N${suffix}`,
        rent: 200,
        electric_rate: 1,
        water_rate: 5,
        billing_day: 19,
        status: "rented",
      },
    })
  ).json();
  const generated = await (
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
  const billId = generated.bill.id;
  await page.goto(`${BASE}/#/bills/${billId}`, { waitUntil: "networkidle" });
  await page.locator('[data-bill-field="rent"]').fill("-40");
  await page.locator('[data-bill-field="prev_electric"]').fill("100");
  await page.locator('[data-bill-field="current_electric"]').fill("103");
  await page.locator('[data-bill-field="prev_water"]').fill("20");
  await page.locator('[data-bill-field="current_water"]').fill("22");
  await page.waitForTimeout(1200);

  const saved = await (await page.request.get(`${BASE}/api/bills/${billId}`)).json();
  if (saved.rent_cents !== -4000 || saved.total_cents !== -2700) {
    throw new Error(`负数房租没有正确保存：${JSON.stringify(saved)}`);
  }
  const responsePromise = page.waitForResponse(
    (response) => response.url().endsWith(`/api/bills/${billId}/confirm`),
  );
  await page.locator('[data-action="confirm-bill"]').click();
  const response = await responsePromise;
  if (!response.ok()) throw new Error(`负数房租确认失败：${await response.text()}`);
  const confirmed = await response.json();
  if (confirmed.total_cents !== -2700 || confirmed.payment_status !== "paid") {
    throw new Error("负数房租收据确认结果不正确");
  }

  console.log(JSON.stringify({ ok: true, rentCents: -4000, totalCents: -2700 }));
  await browser.close();
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
