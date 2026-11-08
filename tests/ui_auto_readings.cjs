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
  const nextMonth = new Date(today.getFullYear(), today.getMonth() + 1, 1);
  const nextMonthText = `${nextMonth.getFullYear()}-${String(nextMonth.getMonth() + 1).padStart(2, "0")}`;

  const property = await (
    await page.request.post(`${BASE}/api/properties`, {
      data: { name: `自动抄表测试${suffix}`, address: "自动抄表测试地址" },
    })
  ).json();
  const room = await (
    await page.request.post(`${BASE}/api/rooms`, {
      data: {
        property_id: property.id,
        room_no: `A${suffix}`,
        rent: 300,
        electric_rate: 1,
        water_rate: 5,
        billing_day: 19,
        electric_auto_enabled: true,
        electric_auto_increment: 12,
        water_auto_enabled: true,
        water_auto_increment: 2,
        status: "rented",
      },
    })
  ).json();
  const nextRoom = await (
    await page.request.post(`${BASE}/api/rooms`, {
      data: {
        property_id: property.id,
        room_no: `B${suffix}`,
        rent: 280,
        electric_rate: 1,
        water_rate: 5,
        billing_day: 19,
        status: "rented",
      },
    })
  ).json();

  const generated = await (
    await page.request.post(`${BASE}/api/rooms/${room.id}/bills/new`, { data: {} })
  ).json();
  const firstBill = await (
    await page.request.put(`${BASE}/api/bills/${generated.bill.id}`, {
      data: { prev_electric: 100, current_electric: 110, prev_water: 20, current_water: 22 },
    })
  ).json();
  await page.request.post(`${BASE}/api/bills/${firstBill.id}/confirm`, {
    data: { payment_status: "paid" },
  });

  const nextDraft = await (
    await page.request.post(`${BASE}/api/rooms/${room.id}/bills/new`, {
      data: {
        custom_dates: true,
        start_date: `${month}-19`,
        end_date: `${nextMonthText}-18`,
        issue_date: `${month}-20`,
        ledger_month: nextMonthText,
      },
    })
  ).json();
  await page.goto(`${BASE}/#/bills/${nextDraft.bill.id}`, { waitUntil: "networkidle" });

  const electric = page.locator('[data-bill-field="current_electric"]');
  const water = page.locator('[data-bill-field="current_water"]');
  if ((await electric.inputValue()) !== "122" || (await water.inputValue()) !== "24") {
    throw new Error("新单没有按上期读数加月增量自动填写");
  }
  if (!(await electric.evaluate((node) => node.readOnly)) || !(await water.evaluate((node) => node.readOnly))) {
    throw new Error("自动填写读数没有默认锁定");
  }
  const rates = page.locator('[data-bill-field="electric_rate"], [data-bill-field="water_rate"]');
  for (const rate of await rates.all()) {
    if (!(await rate.evaluate((node) => node.readOnly)) || (await rate.getAttribute("tabindex")) !== "-1") {
      throw new Error("单价没有默认锁定或仍进入 Tab 顺序");
    }
  }
  await page.locator('[data-action="unlock-rates"]').click();
  if (await rates.first().evaluate((node) => node.readOnly)) {
    throw new Error("点击解锁后单价仍不可编辑");
  }

  await page.locator('[data-action="unlock-reading"][data-field="electric"]').click();
  await electric.fill("125");
  await electric.press("Enter");
  await page.waitForFunction(
    (billId) => !location.hash.endsWith(`/bills/${billId}`),
    String(nextDraft.bill.id),
    { timeout: 10000 },
  );

  const confirmed = await (
    await page.request.get(`${BASE}/api/rooms/${room.id}`)
  ).json();
  const nextQueue = await (
    await page.request.get(`${BASE}/api/rooms/${nextRoom.id}`)
  ).json();
  if (confirmed.bills[0]?.current_electric !== 125) {
    throw new Error("解锁后的读数没有保存");
  }
  if (nextQueue.latest_bill?.status !== "draft") {
    throw new Error("回车确认后没有进入下一间");
  }

  console.log(
    JSON.stringify({
      ok: true,
      autoElectric: 122,
      autoWater: 24,
      editedElectric: 125,
      nextRoom: nextRoom.room_no,
    }),
  );
  await browser.close();
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
