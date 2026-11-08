const { chromium } = require("playwright");

const BASE = process.env.BASE_URL || "http://127.0.0.1:8849";

(async () => {
  const browser = await chromium.launch({
    headless: true,
    args: ["--no-sandbox"],
    ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}),
  });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1100 },
    reducedMotion: "reduce",
  });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error" && !message.text().includes("favicon")) {
      errors.push(message.text());
    }
  });

  const suffix = Date.now().toString().slice(-6);
  const today = new Date();
  const year = today.getFullYear();
  const monthNumber = today.getMonth() + 1;
  const month = `${year}-${String(monthNumber).padStart(2, "0")}`;
  const daysInMonth = new Date(year, monthNumber, 0).getDate();
  const periodStart = `${month}-01`;
  const periodEnd = `${month}-${String(daysInMonth).padStart(2, "0")}`;
  const issueDate = `${month}-${String(today.getDate()).padStart(2, "0")}`;
  const property = await page.request.post(`${BASE}/api/properties`, {
    data: { name: `UI测试房源${suffix}`, address: "自动化测试地址" },
  });
  const propertyData = await property.json();
  const room = await page.request.post(`${BASE}/api/rooms`, {
    data: {
      property_id: propertyData.id,
      room_no: `R${suffix}`,
      tenant_name: "测试租客",
      rent: 420,
      electric_rate: 1.1,
      water_rate: 5.2,
      billing_day: 19,
      status: "rented",
    },
  });
  const roomData = await room.json();
  const nextRoom = await page.request.post(`${BASE}/api/rooms`, {
    data: {
      property_id: propertyData.id,
      room_no: `N${suffix}`,
      tenant_name: "下一间租客",
      rent: 360,
      electric_rate: 1,
      water_rate: 5,
      billing_day: 19,
      status: "rented",
    },
  });
  const nextRoomData = await nextRoom.json();

  await page.goto(`${BASE}/#/rooms/${roomData.id}`, { waitUntil: "networkidle" });
  await page.locator('[data-action="first-receipt"]').first().click();
  await page.locator("#dateStart").fill(periodStart);
  await page.locator("#dateEnd").fill(periodEnd);
  await page.locator("#dateIssue").fill(issueDate);
  await page.locator("#dateLedger").fill(month);
  await page.locator('[data-confirm-date]').click();
  await page.locator(".editor-card").waitFor();

  await page.locator('[data-bill-field="prev_electric"]').fill("100");
  await page.locator('[data-bill-field="prev_water"]').fill("20");
  await page.locator('[data-bill-field="current_electric"]').fill("155");
  await page.locator('[data-bill-field="current_water"]').fill("24");
  await page.locator('[data-action="add-other"]').click();
  await page.locator('[data-fee-slot="1"][data-fee-field="name"]').fill("清洁费");
  await page.locator('[data-fee-slot="1"][data-fee-field="amount"]').fill("20");
  await page.waitForTimeout(1400);

  const totalText = await page.locator("#liveTotal").innerText();
  const saveState = await page.locator("#saveState").innerText();
  if (totalText !== "¥521.30") {
    throw new Error(`金额计算不正确：${totalText}`);
  }
  if (!saveState.includes("已自动保存")) {
    throw new Error(`自动保存未完成：${saveState}`);
  }

  await page.locator('[data-action="confirm-bill"]').click();
  await page.waitForURL(`**/#/bills/*`, { timeout: 10000 });
  await page.locator(".editor-card").waitFor({ timeout: 5000 });
  const nextRoomDetail = await (
    await page.request.get(`${BASE}/api/rooms/${nextRoomData.id}`)
  ).json();
  if (nextRoomDetail.latest_bill?.status !== "draft") {
    throw new Error("确认后没有自动打开下一间草稿");
  }
  if ((await page.locator(".editor-sub").first().innerText()).includes("测试租客")) {
    throw new Error("确认后仍停留在原房间");
  }

  const roomDetail = await (await page.request.get(`${BASE}/api/rooms/${roomData.id}`)).json();
  if (!roomDetail.latest_bill || roomDetail.latest_bill.status !== "confirmed") {
    throw new Error("收据未确认");
  }
  if (roomDetail.latest_bill.total_cents !== 52130) {
    throw new Error(`后端金额不正确：${roomDetail.latest_bill.total_cents}`);
  }
  if (roomDetail.latest_bill.payment_status !== "paid") {
    throw new Error(`确认后未默认已收：${roomDetail.latest_bill.payment_status}`);
  }

  await page.goto(`${BASE}/#/receipts`, { waitUntil: "networkidle" });
  const receiptRow = page.locator("tr", { hasText: roomDetail.latest_bill.receipt_no });
  await receiptRow.waitFor({ timeout: 5000 });
  await receiptRow.locator('[data-action="toggle-payment-status"]').click();
  await page.waitForTimeout(800);
  const unpaidBill = await (
    await page.request.get(`${BASE}/api/bills/${roomDetail.latest_bill.id}`)
  ).json();
  if (unpaidBill.payment_status !== "unpaid") {
    throw new Error(`点击未收后状态不正确：${unpaidBill.payment_status}`);
  }

  await page.goto(`${BASE}/#/ledger`, { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: "房间水电变化" }).waitFor({ timeout: 5000 });
  const ledgerText = await page.locator("#view").innerText();
  if (!ledgerText.includes("经营台账") || !ledgerText.includes("房间水电变化")) {
    throw new Error("总台账页面未正常渲染");
  }

  if (errors.length) {
    throw new Error(`页面脚本错误：${errors.join(" | ")}`);
  }

  console.log(
    JSON.stringify(
      {
        ok: true,
        propertyId: propertyData.id,
        roomId: roomData.id,
        nextRoomId: nextRoomData.id,
        receiptNo: roomDetail.latest_bill.receipt_no,
        totalText,
      },
      null,
      2,
    ),
  );
  await browser.close();
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
