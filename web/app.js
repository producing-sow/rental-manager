const view = document.querySelector("#view");
const monthSelect = document.querySelector("#monthSelect");
const monthControl = document.querySelector("#monthControl");
const pageEyebrow = document.querySelector("#pageEyebrow");
const pageTitle = document.querySelector("#pageTitle");
const pageSubtitle = document.querySelector("#pageSubtitle");
const quickNew = document.querySelector("#quickNew");
const modalRoot = document.querySelector("#modal-root");
const toastRegion = document.querySelector("#toast-region");

const state = {
  bootstrap: null,
  month: null,
  route: "/dashboard",
  token: 0,
  editor: null,
  currentRoomDetail: null,
  currentPropertyDetail: null,
  currentBill: null,
  selectedBillIds: new Set(),
  receiptFilter: "all",
  receiptProperty: "all",
  receiptRows: [],
  ledgerData: null,
  ledgerRoomProperty: "all",
};

let activeModalClose = null;

const moneyFormatter = new Intl.NumberFormat("zh-CN", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function el(selector, root = document) {
  return root.querySelector(selector);
}

function els(selector, root = document) {
  return Array.from(root.querySelectorAll(selector));
}

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function money(cents) {
  const value = Number(cents || 0);
  const sign = value < 0 ? "-" : "";
  return `${sign}¥${moneyFormatter.format(Math.abs(value) / 100)}`;
}

function moneyPlain(cents) {
  return moneyFormatter.format(Number(cents || 0) / 100);
}

function numberText(value, suffix = "") {
  if (value === null || value === undefined || value === "") return "—";
  const number = Number(value);
  const text = Number.isInteger(number)
    ? String(number)
    : number.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
  return `${text}${suffix}`;
}

function percentText(value, signed = false) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
  const number = Number(value) * 100;
  const prefix = signed && number > 0 ? "+" : "";
  return `${prefix}${number.toFixed(1)}%`;
}

function dateText(value) {
  if (!value) return "—";
  return String(value).replaceAll("-", ".");
}

function localDateISO(value = new Date()) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function monthLabel(value) {
  if (!value) return "未选择";
  const [year, month] = String(value).split("-");
  return `${year}年${Number(month)}月`;
}

function currentMonth() {
  return localDateISO().slice(0, 7);
}

function toNumber(value) {
  if (value === "" || value === null || value === undefined) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function toCents(value) {
  const number = toNumber(value);
  return number === null ? 0 : Math.round(number * 100);
}

function roundMoney(value) {
  return Math.round(Number(value || 0) * 100) / 100;
}

function sum(items, selector) {
  return items.reduce((total, item) => total + Number(selector(item) || 0), 0);
}

function pctWidth(value, max) {
  if (!max) return 0;
  return Math.max(2, Math.round((Number(value || 0) / max) * 100));
}

function statusInfo(bill) {
  if (!bill) return { label: "未开单", className: "badge--draft" };
  if (bill.status === "draft") return { label: "草稿", className: "badge--draft" };
  if (bill.status === "void") return { label: "已作废", className: "badge--void" };
  if (bill.overdue) return { label: "已逾期", className: "badge--overdue" };
  if (bill.payment_status === "paid") return { label: "已收", className: "badge--paid" };
  if (bill.payment_status === "partial") return { label: "部分收款", className: "badge--partial" };
  return { label: "未收", className: "badge--unpaid" };
}

function statusBadge(bill) {
  const info = statusInfo(bill);
  return `<span class="badge ${info.className}">${info.label}</span>`;
}

function receiptStatusControl(bill) {
  if (bill.status !== "confirmed") return statusBadge(bill);
  if (bill.payment_status === "partial") {
    return `<button class="status-toggle status-toggle--partial" data-action="toggle-payment-status" data-bill-id="${bill.id}" title="点击设为已收">部分收款</button>`;
  }
  const paid = bill.payment_status === "paid";
  return `<button class="status-toggle ${paid ? "status-toggle--paid" : "status-toggle--unpaid"}" data-action="toggle-payment-status" data-bill-id="${bill.id}" title="点击改为${paid ? "未收" : "已收"}">${paid ? "已收" : "未收"}</button>`;
}

function trendClass(value) {
  if (Number(value) > 0) return "positive";
  if (Number(value) < 0) return "negative";
  return "neutral";
}

function trendChip(value, label = "较上月") {
  const numeric = Number(value || 0);
  const arrow = numeric > 0 ? "↑" : numeric < 0 ? "↓" : "—";
  const display = numeric === 0 ? "持平" : `${arrow} ${money(Math.abs(numeric))}`;
  return `<span class="trend-chip ${trendClass(numeric)}">${label} ${display}</span>`;
}

function deltaMoney(delta, rate, positiveIsGood = true) {
  const numeric = Number(delta || 0);
  if (!numeric) return `<span class="delta-cell delta-flat">持平</span>`;
  const direction = numeric > 0 ? "up" : "down";
  const good = positiveIsGood ? numeric > 0 : numeric < 0;
  const colorClass = good ? "delta-up" : "delta-down";
  const sign = numeric > 0 ? "+" : "-";
  const rateText = rate === null || rate === undefined ? "" : ` · ${percentText(rate, true)}`;
  return `<span class="delta-cell ${direction === "up" ? "delta-up" : "delta-down"} ${colorClass}">${sign}${moneyPlain(Math.abs(numeric))}${rateText}</span>`;
}

function deltaValue(delta, rate) {
  const numeric = Number(delta || 0);
  if (!numeric) return `<span class="delta-cell delta-flat">持平</span>`;
  const className = numeric > 0 ? "delta-up" : "delta-down";
  const sign = numeric > 0 ? "+" : "-";
  const suffix = rate === null || rate === undefined ? "" : ` · ${percentText(rate, true)}`;
  return `<span class="delta-cell ${className}">${sign}${moneyPlain(Math.abs(numeric))}${suffix}</span>`;
}

function paperNumber(value) {
  if (value === null || value === undefined || value === "") return "—";
  const number = Number(value);
  return Number.isInteger(number) ? String(number) : String(Math.round(number * 100) / 100);
}

function rmbUpper(cents) {
  const digits = "零壹贰叁肆伍陆柒捌玖";
  const units = ["", "拾", "佰", "仟"];
  const bigUnits = ["", "万", "亿", "兆"];
  let value = Math.abs(Math.round(Number(cents || 0)));
  if (!value) return "零元整";
  const sign = Number(cents) < 0 ? "负" : "";
  const yuan = Math.floor(value / 100);
  const remainder = value % 100;
  const jiao = Math.floor(remainder / 10);
  const fen = remainder % 10;

  function groupCn(group) {
    let result = "";
    let zeroPending = false;
    for (let pos = 3; pos >= 0; pos -= 1) {
      const digit = Math.floor(group / 10 ** pos) % 10;
      if (digit) {
        if (zeroPending && result) result += "零";
        result += digits[digit] + units[pos];
        zeroPending = false;
      } else if (result) {
        zeroPending = true;
      }
    }
    return result;
  }

  const groups = [];
  let remaining = yuan;
  while (remaining > 0) {
    groups.push(remaining % 10000);
    remaining = Math.floor(remaining / 10000);
  }
  let integerText = "";
  for (let index = groups.length - 1; index >= 0; index -= 1) {
    const group = groups[index];
    if (!group) {
      if (integerText && !integerText.endsWith("零")) integerText += "零";
      continue;
    }
    if (integerText && group < 1000 && !integerText.endsWith("零")) integerText += "零";
    integerText += groupCn(group) + bigUnits[index];
  }
  integerText = integerText.replaceAll("零零", "零").replace(/零+$/g, "") || "零";
  if (!jiao && !fen) return `${sign}${integerText}元整`;
  let decimals = "";
  if (jiao) decimals += `${digits[jiao]}角`;
  else if (fen) decimals += "零";
  if (fen) decimals += `${digits[fen]}分`;
  return `${sign}${integerText}元${decimals}`;
}

function api(path, options = {}) {
  const request = {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  };
  if (request.body && typeof request.body !== "string" && !(request.body instanceof Blob)) {
    request.body = JSON.stringify(request.body);
  }
  return fetch(path, request)
    .then(async (response) => {
      const contentType = response.headers.get("content-type") || "";
      if (contentType.includes("application/json")) {
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || `请求失败 (${response.status})`);
        return data;
      }
      if (!response.ok) throw new Error(`请求失败 (${response.status})`);
      return response;
    })
    .catch((error) => {
      if (error instanceof TypeError) {
        throw new Error("无法连接本地服务，请保持“启动收租管理”命令行窗口开启后重试。");
      }
      throw error;
    });
}

function toast(message, type = "success") {
  const node = document.createElement("div");
  node.className = `toast ${type === "error" ? "error" : ""}`;
  node.textContent = message;
  toastRegion.appendChild(node);
  setTimeout(() => node.remove(), 4200);
}

function closeModal() {
  if (!activeModalClose) return;
  const close = activeModalClose;
  activeModalClose = null;
  close();
}

function openModal({ title, subtitle = "", body = "", footer = "", size = "", onMount, onClose }) {
  const root = modalRoot;
  root.innerHTML = `
    <div class="modal-backdrop" data-modal-backdrop>
      <div class="modal-card ${size}" role="dialog" aria-modal="true" aria-label="${esc(title)}">
        <div class="modal-head">
          <div>
            <h3>${esc(title)}</h3>
            ${subtitle ? `<p>${esc(subtitle)}</p>` : ""}
          </div>
          <button class="modal-close" type="button" data-modal-close aria-label="关闭">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none"><path d="m6 6 12 12M18 6 6 18" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
          </button>
        </div>
        <div class="modal-body">${body}</div>
        ${footer ? `<div class="modal-foot">${footer}</div>` : ""}
      </div>
    </div>`;
  const modal = el(".modal-card", root);
  let closed = false;
  function finish() {
    if (closed) return;
    closed = true;
    root.innerHTML = "";
    activeModalClose = null;
    onClose?.();
  }
  activeModalClose = finish;
  el("[data-modal-close]", modal)?.addEventListener("click", finish);
  el("[data-modal-backdrop]", root)?.addEventListener("mousedown", (event) => {
    if (event.target === event.currentTarget) finish();
  });
  onMount?.(modal, finish);
  requestAnimationFrame(() => {
    const focusable = modal.querySelector("input, select, textarea, button:not([data-modal-close])");
    focusable?.focus();
  });
  return { modal, close: finish };
}

function confirmDialog({ title, message, confirmLabel = "确定", danger = false }) {
  return new Promise((resolve) => {
    let settled = false;
    const modal = openModal({
      title,
      subtitle: "",
      size: "modal-small",
      body: `<div class="inline-note ${danger ? "accent" : ""}">${esc(message)}</div>`,
      footer: `
        <button class="btn btn-ghost" type="button" data-cancel>取消</button>
        <button class="btn ${danger ? "btn-danger" : "btn-primary"}" type="button" data-confirm>${esc(confirmLabel)}</button>
      `,
      onClose: () => {
        if (!settled) {
          settled = true;
          resolve(false);
        }
      },
    });
    el("[data-cancel]", modal.modal).addEventListener("click", () => {
      settled = true;
      modal.close();
      resolve(false);
    });
    el("[data-confirm]", modal.modal).addEventListener("click", () => {
      settled = true;
      modal.close();
      resolve(true);
    });
  });
}

function setPageMeta(eyebrow, title, subtitle) {
  pageEyebrow.textContent = eyebrow;
  pageTitle.textContent = title;
  pageSubtitle.textContent = subtitle;
}

function setActiveNav(section) {
  els("[data-nav]").forEach((link) => {
    link.classList.toggle("active", link.dataset.nav === section);
  });
}

function routeInfo(path) {
  const parts = path.split("/").filter(Boolean);
  if (!parts.length) return { name: "dashboard" };
  if (parts[0] === "properties" && parts[1]) {
    return { name: "property", id: Number(parts[1]) };
  }
  if (parts[0] === "rooms" && parts[1]) {
    return { name: "room", id: Number(parts[1]) };
  }
  if (parts[0] === "bills" && parts[1]) {
    return { name: "bill", id: Number(parts[1]) };
  }
  return { name: parts[0] };
}

function go(path, { replace = false } = {}) {
  const target = `#${path}`;
  if (location.hash === target) {
    renderRoute();
    return;
  }
  if (replace) {
    history.replaceState(null, "", target);
    renderRoute();
  } else {
    location.hash = path;
  }
}

function populateMonthSelect() {
  const months = state.bootstrap?.months || [state.month];
  monthSelect.innerHTML = months
    .map((value) => `<option value="${esc(value)}">${esc(monthLabel(value))}${value === state.bootstrap?.current_month ? " · 本月" : ""}</option>`)
    .join("");
  if (!months.includes(state.month)) {
    const option = document.createElement("option");
    option.value = state.month;
    option.textContent = monthLabel(state.month);
    monthSelect.appendChild(option);
  }
  monthSelect.value = state.month;
}

async function reloadBootstrap() {
  const bootstrap = await api("/api/bootstrap");
  state.bootstrap = bootstrap;
  const stored = localStorage.getItem("rental-month");
  if (!state.month) {
    state.month = stored && bootstrap.months.includes(stored) ? stored : bootstrap.default_month;
  } else if (!bootstrap.months.includes(state.month)) {
    state.month = bootstrap.default_month;
  }
  populateMonthSelect();
}

async function init() {
  document.querySelector("#todayLabel").textContent = new Intl.DateTimeFormat("zh-CN", {
    month: "long",
    day: "numeric",
    weekday: "short",
  }).format(new Date());

  try {
    await reloadBootstrap();
    monthSelect.addEventListener("change", () => {
      state.month = monthSelect.value;
      localStorage.setItem("rental-month", state.month);
      renderRoute();
    });
    quickNew.addEventListener("click", () => go("/properties"));
    document.querySelector("#menuToggle").addEventListener("click", () => {
      document.body.classList.toggle("nav-open");
    });
    document.querySelector("#mobileScrim").addEventListener("click", () => {
      document.body.classList.remove("nav-open");
    });
    els("[data-nav]").forEach((link) => {
      link.addEventListener("click", () => document.body.classList.remove("nav-open"));
    });
    window.addEventListener("hashchange", renderRoute);
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeModal();
      if (
        event.key === "Enter" &&
        !event.shiftKey &&
        !event.isComposing &&
        state.editor &&
        !el("#modal-root .modal-card") &&
        !event.target.closest("button, a, textarea, [contenteditable='true']")
      ) {
        const confirmButton = el('[data-action="confirm-bill"]');
        if (confirmButton && !confirmButton.disabled) {
          event.preventDefault();
          confirmCurrentBill(confirmButton);
        }
      }
    });
    view.addEventListener("click", handleViewClick);
    view.addEventListener("input", handleViewInput);
    view.addEventListener("change", handleViewChange);
    await renderRoute();
  } catch (error) {
    view.innerHTML = errorState(error.message);
  }
}

async function renderRoute() {
  const path = location.hash.replace(/^#/, "") || "/dashboard";
  if (state.editor && (state.editor.dirty || state.editor.saving)) {
    try {
      await flushEditor();
    } catch (error) {
      toast(`草稿尚未保存：${error.message}`, "error");
      history.replaceState(null, "", `#${state.route}`);
      return;
    }
  }
  state.route = path;
  const info = routeInfo(path);
  const token = ++state.token;
  state.editor = null;
  state.currentRoomDetail = null;
  state.currentPropertyDetail = null;
  state.currentBill = null;
  closeModal();

  const navMap = {
    dashboard: "dashboard",
    properties: "properties",
    property: "properties",
    room: "properties",
    bill: "receipts",
    receipts: "receipts",
    ledger: "ledger",
    help: "help",
    settings: "settings",
  };
  setActiveNav(navMap[info.name] || "dashboard");

  const meta = {
    dashboard: ["经营总览", "首页概览", "把每月收租和抄表，做成一件顺手的小事。"],
    properties: ["房源资产", "房源房间", "从一个房源进入，逐间完成本月的收据。"],
    receipts: ["账单留档", "收据记录", "查看、核对、导出每一张已生成的收据。"],
    ledger: ["经营分析", "总台账", "收入、成本、盈亏和房间水电变化，都集中在这里。"],
    help: ["新手指引", "使用帮助", "从首次建账到每月收租，按步骤完成常用操作。"],
    settings: ["本地数据", "系统设置", "调整收据信息、备份数据，管理这台电脑上的账本。"],
  }[info.name] || ["租舍", "收据管理", ""];
  setPageMeta(...meta);
  monthControl.classList.toggle("hidden", ["room", "bill", "help", "settings"].includes(info.name));
  quickNew.classList.toggle("hidden", ["room", "bill", "help", "settings"].includes(info.name));

  view.innerHTML = `
    <div class="page-loading">
      <span class="loading-mark"></span>
      <p>正在整理账本…</p>
    </div>`;

  try {
    if (info.name === "dashboard") await renderDashboard(token);
    else if (info.name === "properties") await renderProperties(token);
    else if (info.name === "property") await renderProperty(info.id, token);
    else if (info.name === "room") await renderRoom(info.id, token);
    else if (info.name === "bill") await renderBillPage(info.id, token);
    else if (info.name === "receipts") await renderReceipts(token);
    else if (info.name === "ledger") await renderLedger(token);
    else if (info.name === "help") await renderHelp(token);
    else if (info.name === "settings") await renderSettings(token);
    else {
      view.innerHTML = errorState("页面不存在");
    }
    if (token === state.token) {
      view.querySelector(".view-content")?.classList.add("fade-in");
    }
  } catch (error) {
    if (token === state.token) {
      view.innerHTML = errorState(error.message);
    }
  }
}

function errorState(message) {
  return `
    <div class="section-card empty-state">
      <div class="empty-illustration">
        <svg viewBox="0 0 24 24" fill="none"><path d="M12 8v5m0 3.5v.01M10.3 3.7 2.6 18.1A2 2 0 0 0 4.4 21h15.2a2 2 0 0 0 1.8-2.9L13.7 3.7a2 2 0 0 0-3.4 0Z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
      </div>
      <h3>刚才没能完成</h3>
      <p>${esc(message || "请稍后再试")}</p>
      <button class="btn btn-secondary" data-action="refresh-route">重新加载</button>
    </div>`;
}

function emptyIllustration() {
  return `<svg viewBox="0 0 48 48" fill="none"><path d="M8 21 24 8l16 13v18a2 2 0 0 1-2 2H10a2 2 0 0 1-2-2V21Z" stroke="currentColor" stroke-width="1.6"/><path d="M18 41V28h12v13M15 19h.01M24 17h.01M33 19h.01" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>`;
}

function propertyIcon() {
  return `<svg viewBox="0 0 24 24" fill="none"><path d="M4 20V7.5L12 3l8 4.5V20M8 20v-5h8v5M8 9h.01M12 9h.01M16 9h.01" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
}

function showLoadingInline(target) {
  target.innerHTML = `<div class="page-loading"><span class="loading-mark"></span><p>正在加载…</p></div>`;
}

function selectedPropertyIdFromButton(button) {
  return Number(button.dataset.propertyId || state.currentPropertyDetail?.property?.id || 0);
}

function emptyState({ title, text, actions = "" }) {
  return `
    <div class="section-card empty-state">
      <div class="empty-illustration">${emptyIllustration()}</div>
      <h3>${esc(title)}</h3>
      <p>${esc(text)}</p>
      <div class="empty-actions">${actions}</div>
    </div>`;
}

function propertyCard(property) {
  const outstanding = Math.max(0, property.billed_cents - property.received_cents);
  return `
    <a class="property-card" href="#/properties/${property.id}">
      <div class="property-top">
        <div class="property-icon">${propertyIcon()}</div>
        <div style="min-width:0">
          <div class="property-name">${esc(property.name)}</div>
          <div class="property-location">${esc(property.address || "未填写地址")}</div>
        </div>
      </div>
      <div class="property-stats">
        <div class="property-stat"><span>房间</span><strong>${property.room_count} 间</strong></div>
        <div class="property-stat"><span>本月应收</span><strong>${money(property.billed_cents)}</strong></div>
        <div class="property-stat"><span>未收</span><strong>${money(outstanding)}</strong></div>
      </div>
      <div class="property-actions">
        <span>${property.rented_count} 间在租 · ${property.billed_count} 张收据</span>
        <span>进入房源 →</span>
      </div>
    </a>`;
}

function dashboardPropertyTable(rows) {
  if (!rows.length) return `<div class="field-hint">还没有房源。</div>`;
  return `
    <div class="table-scroll">
      <table class="data-table property-ledger-table">
        <thead><tr><th>房源</th><th class="align-right">本月应收</th><th class="align-right">实收</th><th class="align-right">未收</th><th class="align-right">经营毛利</th><th></th></tr></thead>
        <tbody>
          ${rows.map((row) => `
            <tr>
              <td><a class="cell-title" href="#/properties/${row.id || row.property_id}">${esc(row.name || row.property_name)}</a><div class="cell-sub">${row.rented_count}/${row.room_count} 间 · ${row.billed_count} 张 · ${esc(row.address || "")}</div></td>
              <td class="align-right price-cell">${money(row.billed_cents)}</td>
              <td class="align-right price-cell money--positive">${money(row.received_cents)}</td>
              <td class="align-right price-cell ${row.outstanding_cents ? "money--negative" : "money--muted"}">${money(row.outstanding_cents)}</td>
              <td class="align-right price-cell ${row.profit_cents >= 0 ? "money--positive" : "money--negative"}">${money(row.profit_cents)}</td>
              <td class="align-right"><a class="link-button" href="#/properties/${row.id || row.property_id}">进入 →</a></td>
            </tr>`).join("")}
        </tbody>
      </table>
    </div>`;
}

async function renderDashboard(token) {
  const data = await api(`/api/dashboard?month=${encodeURIComponent(state.month)}`);
  if (token !== state.token) return;
  if (!data.properties.length) {
    view.innerHTML = `
      <div class="view-content">
        ${emptyState({
          title: "先从一个房源开始",
          text: "创建房源和房间后，就可以进入房间确认日期、填写两个本月读数，生成第一张收据。也可以先载入截图里的示例数据体验完整流程。",
          actions: `
            <button class="btn btn-primary" data-action="add-property">新增房源</button>
            <button class="btn btn-secondary" data-action="seed-demo">载入示例数据</button>
          `,
        })}
      </div>`;
    return;
  }

  const deltaProfit = data.profit_delta_cents;
  const rentedRatio = data.rooms_total ? Math.round((data.rooms_rented / data.rooms_total) * 100) : 0;
  const recent = data.recent_bills || [];
  view.innerHTML = `
    <div class="view-content">
      <section class="dashboard-hero">
        <div class="hero-copy">
          <span class="hero-kicker">${esc(monthLabel(state.month))} · 经营简报</span>
          <div class="hero-number-row">
            <div class="price-tag ${data.profit_cents >= 0 ? "price-tag--positive" : "price-tag--negative"}">${money(data.profit_cents)}</div>
            <span class="hero-number-label">经营毛利</span>
          </div>
          <p>按已确认收据计算，已扣除已录入的水电成本。本月共有 ${data.bill_count} 张收据，${data.unpaid_count} 张还有未收金额。</p>
          <div class="hero-actions">
            <button class="btn btn-primary" data-action="go-properties">开始开收据</button>
            <a class="btn btn-secondary" href="#/ledger">查看总台账</a>
          </div>
        </div>
        <div class="hero-side">
          <div class="hero-side-label">本月应收合计</div>
          <div class="hero-side-value">${money(data.billed_cents)}</div>
          <div class="hero-side-row"><span>实收</span><strong>${money(data.received_cents)}</strong></div>
          <div class="hero-side-row"><span>在租房间</span><strong>${data.rooms_rented} / ${data.rooms_total}</strong></div>
          <div class="hero-side-row"><span>出租率</span><strong>${rentedRatio}%</strong></div>
        </div>
      </section>

      <section class="stat-grid">
        ${statCard("本月应收", data.billed_cents, trendChip(data.billed_delta_cents), "accent", "账单合计")}
        ${statCard("已收金额", data.received_cents, `<span class="trend-chip neutral">已收 ${percentText(data.billed_cents ? data.received_cents / data.billed_cents : 0)}</span>`, "sage", "实际到账")}
        ${statCard("未收金额", data.outstanding_cents, `<span class="trend-chip neutral">${data.unpaid_count} 张未收齐</span>`, "gold", "应收减实收")}
        ${statCard("经营毛利", data.profit_cents, trendChip(deltaProfit), "info", "计费收入减经营成本")}
      </section>

      <div class="content-grid">
        <section class="section-card">
          <div class="section-header">
            <div>
              <h3 class="section-title">房源经营台账</h3>
              <p class="section-sub">按房源查看本月应收、实收、未收与经营毛利。</p>
            </div>
            <a class="link-button" href="#/properties">全部房源 →</a>
          </div>
          ${dashboardPropertyTable(data.properties)}
        </section>

        <section class="section-card">
          <div class="section-header">
            <div>
              <h3 class="section-title">最近生成</h3>
              <p class="section-sub">最近确认的收据会出现在这里。</p>
            </div>
            <a class="link-button" href="#/receipts">收据记录 →</a>
          </div>
          ${recent.length ? `<div class="list-stack">${recent.map(recentReceiptRow).join("")}</div>` : `
            <div class="empty-state" style="padding:32px 10px 20px">
              <p>还没有已确认的收据。开一张收据后，这里会自动汇总。</p>
            </div>`}
          <div class="insight-card" style="margin-top:20px">
            <small>经营小记</small>
            <h3>${rentedRatio}% 的房间正在出租</h3>
            <p>本月计费收入 ${money(data.billed_cents)}，已录入成本 ${money(data.cost_cents)}。到总台账可查看水电差价和环比变化。</p>
            <div class="insight-divider"></div>
            <div class="insight-row"><span>草稿待确认</span><strong>${data.draft_count} 张</strong></div>
            <div class="insight-row"><span>成本数据</span><strong>${data.cost_cents ? "已录入" : "尚未录入"}</strong></div>
          </div>
        </section>
      </div>
    </div>`;
}

function statCard(label, cents, footer, iconType, sublabel) {
  const iconMap = {
    accent: `<path d="M5 5h14v14H5zM8 9h8M8 13h5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>`,
    sage: `<path d="M4 12.5 8.5 17 20 5.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>`,
    gold: `<circle cx="12" cy="12" r="8" stroke="currentColor" stroke-width="1.6"/><path d="M12 7.5v9M9.5 9.5h4a1.8 1.8 0 0 1 0 3.6h-3a1.8 1.8 0 0 0 0 3.6H15" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>`,
    info: `<path d="M4 19V9m5 10V5m5 14v-7m5 7V7" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>`,
  };
  return `
    <article class="stat-card">
      <div class="stat-top">
        <span class="stat-label">${label}</span>
        <span class="stat-icon ${iconType}"><svg viewBox="0 0 24 24" width="16" height="16" fill="none">${iconMap[iconType]}</svg></span>
      </div>
      <div class="stat-value amount-font">${money(cents)}</div>
      <div class="stat-foot"><span>${esc(sublabel)}</span>${footer}</div>
    </article>`;
}

function recentReceiptRow(bill) {
  return `
    <a class="recent-row" href="#/bills/${bill.id}">
      <div class="recent-main">
        <div class="recent-title">${esc(bill.property_name)} · ${esc(bill.room_no)} ${statusBadge(bill)}</div>
        <div class="recent-sub">${esc(bill.start_date)} 至 ${esc(bill.end_date)} · 单号 ${esc(bill.receipt_no || "草稿")}</div>
      </div>
      <div class="recent-amount">${money(bill.total_cents)}</div>
      <span class="link-button">查看</span>
    </a>`;
}

async function renderProperties(token) {
  const [data, bootstrap] = await Promise.all([
    api(`/api/properties?month=${encodeURIComponent(state.month)}`),
    api("/api/bootstrap"),
  ]);
  if (token !== state.token) return;
  state.bootstrap = { ...bootstrap, months: state.bootstrap?.months || bootstrap.months };
  const properties = data.properties;
  view.innerHTML = `
    <div class="view-content">
      <div class="page-lead">
        <div>
          <h2>${monthLabel(state.month)}的房源</h2>
          <p>${properties.length} 个房源 · 点击房源进入房间列表，逐间开收据。</p>
        </div>
        <div class="page-actions">
          <button class="btn btn-secondary" data-action="add-property">新增房源</button>
          <button class="btn btn-primary" data-action="go-properties">选择房间开单</button>
        </div>
      </div>
      ${properties.length ? propertiesTable(properties) : emptyState({
        title: "还没有房源",
        text: "先建立一个房源，再添加房间和租客。也可以在空账本中载入截图示例，快速体验。",
        actions: `
          <button class="btn btn-primary" data-action="add-property">新增房源</button>
          <button class="btn btn-secondary" data-action="seed-demo">载入示例数据</button>
        `,
      })}
    </div>`;
}

function propertiesTable(properties) {
  return `
    <div class="table-card">
      <div class="table-scroll">
        <table class="data-table property-list-table">
          <thead><tr><th>房源</th><th>地址</th><th class="align-right">房间</th><th class="align-right">在租</th><th class="align-right">本月应收</th><th class="align-right">实收</th><th class="align-right">未收</th><th class="align-right">操作</th></tr></thead>
          <tbody>
            ${properties.map((property) => {
              const outstanding = Math.max(0, property.billed_cents - property.received_cents);
              return `<tr>
                <td><a class="cell-title" href="#/properties/${property.id}">${esc(property.name)}</a><div class="cell-sub">${property.billed_count} 张本月收据</div></td>
                <td>${esc(property.address || "未填写地址")}</td>
                <td class="align-right tabular">${property.room_count}</td>
                <td class="align-right tabular">${property.rented_count}</td>
                <td class="align-right price-cell">${money(property.billed_cents)}</td>
                <td class="align-right price-cell money--positive">${money(property.received_cents)}</td>
                <td class="align-right price-cell ${outstanding ? "money--negative" : "money--muted"}">${money(outstanding)}</td>
                <td class="align-right"><a class="btn btn-ghost btn-small" href="#/properties/${property.id}">进入房源</a></td>
              </tr>`;
            }).join("")}
          </tbody>
        </table>
      </div>
    </div>`;
}

async function renderProperty(propertyId, token) {
  const data = await api(`/api/properties/${propertyId}?month=${encodeURIComponent(state.month)}`);
  if (token !== state.token) return;
  state.currentPropertyDetail = data;
  const property = data.property;
  const rooms = data.rooms;
  setPageMeta("房源房间", property.name, property.address || "逐间确认日期、读数并生成收据。");
  const monthBills = rooms.map((room) => room.month_bill).filter(Boolean);
  const billed = sum(monthBills, (bill) => bill.total_cents);
  const paid = sum(monthBills, (bill) => bill.paid_cents);
  const outstanding = sum(monthBills, (bill) => bill.outstanding_cents);
  const currentBills = monthBills.length;
  view.innerHTML = `
    <div class="view-content">
      <div class="breadcrumb"><a href="#/properties">房源房间</a><span>/</span><span>${esc(property.name)}</span></div>
      <div class="context-bar">
        <span class="context-note">${esc(property.address || "未填写地址")} · ${rooms.length} 间房 · ${monthBills.length} 张${monthLabel(state.month)}收据</span>
        <div class="page-actions">
          <button class="btn btn-secondary" data-action="edit-property" data-property-id="${property.id}">编辑房源</button>
          <button class="btn btn-primary" data-action="add-room" data-property-id="${property.id}">新增房间</button>
        </div>
      </div>
      <section class="hero-strip">
        <div class="hero-strip-main">
          <small>${esc(monthLabel(state.month))} · 房源概览</small>
          <strong>${money(billed)}</strong>
          <span style="font-size:10px;color:rgba(255,249,240,.48);margin-top:6px">本月应收</span>
        </div>
        <div class="hero-strip-metric"><span>房间总数</span><strong>${rooms.length} 间</strong></div>
        <div class="hero-strip-metric"><span>本月已出单</span><strong>${currentBills} 张</strong></div>
        <div class="hero-strip-metric"><span>实收</span><strong>${money(paid)}</strong></div>
        <div class="hero-strip-metric"><span>未收</span><strong>${money(outstanding)}</strong></div>
      </section>
      <section class="section-card" style="margin-top:18px">
        <div class="section-header">
          <div>
            <h3 class="section-title">房间列表</h3>
            <p class="section-sub">点击房间进入收据，确认后会自动返回这里，方便继续下一间。</p>
          </div>
          <span class="badge ${currentBills === rooms.length && rooms.length ? "badge--paid" : "badge--draft"}">${currentBills === rooms.length && rooms.length ? "本月已完成" : "还有房间未出单"}</span>
        </div>
        ${rooms.length ? roomTable(rooms) : emptyState({
          title: "这个房源还没有房间",
          text: "添加房间后，就可以从房间列表进入收据流程。",
          actions: `<button class="btn btn-primary" data-action="add-room" data-property-id="${property.id}">新增房间</button>`,
        })}
      </section>
    </div>`;
  restorePropertyScroll(propertyId);
}

function restorePropertyScroll(propertyId) {
  const key = `property-scroll-${propertyId}`;
  const stored = sessionStorage.getItem(key);
  if (!stored) return;
  sessionStorage.removeItem(key);
  requestAnimationFrame(() => {
    window.scrollTo({ top: Number(stored) || 0, behavior: "auto" });
  });
}

function roomCard(room) {
  const latest = room.month_bill || room.latest_bill;
  const isVacant = room.status === "vacant" || room.status === "inactive";
  const status = isVacant ? `<span class="badge badge--draft">空置</span>` : statusBadge(latest);
  const latestLine = latest
    ? `${latest.start_date} 至 ${latest.end_date}`
    : "尚未生成任何收据";
  return `
    <a class="room-card ${isVacant ? "is-vacant" : ""}" href="#/rooms/${room.id}">
      <div class="room-card-top">
        <div>
          <div class="room-number">${esc(room.room_no)}</div>
          <div class="room-tenant">${esc(room.tenant_name || "未填写租客")}</div>
        </div>
        ${status}
      </div>
      <div class="room-bill">
        <div class="room-bill-row"><span>最近账期</span><strong>${esc(latestLine)}</strong></div>
        <div class="room-bill-row"><span>账单合计</span><strong>${latest ? money(latest.total_cents) : "—"}</strong></div>
        <div class="room-bill-row"><span>未收金额</span><strong>${latest ? money(latest.outstanding_cents) : "—"}</strong></div>
      </div>
      <div class="room-actions">
        <span style="color:var(--muted);font-size:9px">${isVacant ? "只可查看历史" : latest ? "点击进入继续操作" : "点击确认日期开单"}</span>
        <span class="link-button">进入 →</span>
      </div>
    </a>`;
}

function roomTable(rooms) {
  return `
    <div class="table-scroll">
      <table class="data-table room-list-table">
        <thead><tr><th>房间</th><th>租客</th><th>最近账期</th><th class="align-right">账单合计</th><th class="align-right">已收</th><th class="align-right">未收</th><th>状态</th><th class="align-right">操作</th></tr></thead>
        <tbody>
          ${rooms.map((room) => {
            const latest = room.month_bill || room.latest_bill;
            const isVacant = room.status === "vacant" || room.status === "inactive";
            const latestLine = latest ? `${latest.start_date} 至 ${latest.end_date}` : "尚未生成收据";
            return `<tr class="${isVacant ? "row-muted" : ""}">
              <td><a class="room-number-cell" href="#/rooms/${room.id}">${esc(room.room_no)}</a></td>
              <td>${esc(room.tenant_name || "—")}</td>
              <td><span class="tabular">${esc(latestLine)}</span></td>
              <td class="align-right price-cell">${latest ? money(latest.total_cents) : "—"}</td>
              <td class="align-right price-cell money--positive">${latest ? money(latest.paid_cents) : "—"}</td>
              <td class="align-right price-cell ${latest?.outstanding_cents ? "money--negative" : "money--muted"}">${latest ? money(latest.outstanding_cents) : "—"}</td>
              <td>${isVacant ? `<span class="badge badge--draft">空置</span>` : statusBadge(latest)}</td>
              <td class="align-right"><a class="btn btn-ghost btn-small" href="#/rooms/${room.id}">${latest ? "进入收据" : "确认日期"}</a></td>
            </tr>`;
          }).join("")}
        </tbody>
      </table>
    </div>`;
}

async function renderRoom(roomId, token) {
  const data = await api(`/api/rooms/${roomId}`);
  if (token !== state.token) return;
  state.currentRoomDetail = data;
  const room = data.room;
  const latest = data.latest_bill;
  state.currentBill = latest;
  setPageMeta("房间收据", `${room.property_name} · ${room.room_no}`, room.tenant_name ? `${room.tenant_name} · 按房间完成本月收据。` : "填写租客资料后，开单会更顺手。");
  const actions = roomActionsHTML(data, { hideNew: latest?.status === "draft" });
  const content = latest
    ? latest.status === "draft"
      ? billEditorHTML(data, latest)
      : billViewHTML(latest, data)
    : firstBillStateHTML(data);
  view.innerHTML = `
    <div class="view-content">
      <div class="breadcrumb"><a href="#/properties">房源房间</a><span>/</span><a href="#/properties/${room.property_id}">${esc(room.property_name)}</a><span>/</span><span>${esc(room.room_no)}</span></div>
      <div class="context-bar">
        <span class="context-note">${esc(room.tenant_name || "未填写租客")} · ${room.status === "rented" ? "出租中" : room.status === "vacant" ? "空置" : "已停用"}${latest ? ` · 最近账期 ${esc(latest.start_date)} 至 ${esc(latest.end_date)}` : " · 还没有收据"}</span>
        <div class="page-actions">${actions}</div>
      </div>
      ${content}
      ${latest ? `<section class="section-card" style="margin-top:18px">
        <div class="section-header">
          <div><h3 class="section-title">历史收据</h3><p class="section-sub">这个房间最近生成的收据记录。</p></div>
          <button class="btn btn-secondary btn-small" data-action="custom-date">补录其他月份</button>
        </div>
        ${historyListHTML(data, latest.id)}
      </section>` : ""}
    </div>`;
  if (latest?.status === "draft") {
    mountBillEditor(data, latest);
  }
}

async function renderBillPage(billId, token) {
  const bill = await api(`/api/bills/${billId}`);
  const data = await api(`/api/rooms/${bill.room_id}`);
  if (token !== state.token) return;
  state.currentRoomDetail = data;
  const room = data.room;
  state.currentBill = bill;
  setPageMeta("收据详情", `${room.property_name} · ${room.room_no}`, bill.status === "draft" ? "草稿尚未生成正式单号。" : `单号 ${bill.receipt_no || "—"}`);
  const actions = roomActionsHTML(data, { hideNew: bill.status === "draft" });
  const content = bill.status === "draft" ? billEditorHTML(data, bill) : billViewHTML(bill, data);
  view.innerHTML = `
    <div class="view-content">
      <div class="breadcrumb"><a href="#/properties">房源房间</a><span>/</span><a href="#/properties/${room.property_id}">${esc(room.property_name)}</a><span>/</span><a href="#/rooms/${room.id}">${esc(room.room_no)}</a><span>/</span><span>${esc(bill.receipt_no || "草稿")}</span></div>
      <div class="page-lead">
        <div>
          <h2>${bill.status === "draft" ? "继续填写收据" : bill.status === "void" ? "已作废收据" : `收据 ${esc(bill.receipt_no)}`}</h2>
          <p>${esc(bill.start_date)} 至 ${esc(bill.end_date)} · ${esc(bill.tenant_name || "未填写租客")}</p>
        </div>
        <div class="page-actions">${actions}</div>
      </div>
      ${content}
      <section class="section-card" style="margin-top:18px">
        <div class="section-header">
          <div><h3 class="section-title">历史收据</h3><p class="section-sub">返回房间可继续开下一期。</p></div>
          <button class="btn btn-secondary btn-small" data-action="custom-date">补录其他月份</button>
        </div>
        ${historyListHTML(data, bill.id)}
      </section>
    </div>`;
  if (bill.status === "draft") {
    mountBillEditor(data, bill);
  }
}

function roomActionsHTML(data, { hideNew = false } = {}) {
  const room = data.room;
  const latest = data.latest_bill;
  const disabled = room.status !== "rented";
  const newLabel = latest?.status === "draft" ? "继续填写" : latest ? "新增下一期" : "确认日期开单";
  return `
    <a class="btn btn-ghost" href="#/properties/${room.property_id}">返回房间列表</a>
    <button class="btn btn-secondary" data-action="edit-room">编辑房间</button>
    ${!hideNew ? `<button class="btn btn-primary" data-action="${latest ? "new-receipt" : "first-receipt"}" ${disabled ? "disabled" : ""}>
      <svg viewBox="0 0 24 24" fill="none"><path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/></svg>
      ${newLabel}
    </button>` : ""}`;
}

function firstBillStateHTML(data) {
  const room = data.room;
  return `
    <div class="section-card empty-state">
      <div class="empty-illustration">${emptyIllustration()}</div>
      <h3>先确认这个房间的日期</h3>
      <p>首次开单需要确认账单周期和收据日期，并录入一次期初电表、水表读数。之后每月点“新增”就会自动衔接。</p>
      <div class="inline-note sage" style="max-width:520px;text-align:left;margin-bottom:18px">
        建议周期：${esc(data.suggested_start)} 至 ${esc(data.suggested_end)}。你也可以按实际抄表日修改。
      </div>
      <button class="btn btn-primary btn-large" data-action="first-receipt" ${room.status !== "rented" ? "disabled" : ""}>确认日期并开第一张收据</button>
    </div>`;
}

function feeListHTML(fees) {
  if (!fees.length) {
    return `<div class="field-hint">其他费用默认不出现。需要时再添加，最多三项。</div>`;
  }
  return `<div class="fee-table-head"><span>槽位</span><span>费用名称</span><span>金额</span><span></span></div>` + fees
    .sort((a, b) => a.slot - b.slot)
    .map(
      (fee) => `
      <div class="fee-row">
        <span class="fee-slot">其他费用 ${fee.slot}</span>
        <input class="input" data-fee-slot="${fee.slot}" data-fee-field="name" placeholder="费用名称" value="${esc(fee.name || "")}" />
        <div class="input-affix">
          <span class="prefix">¥</span>
          <input class="input has-suffix" type="number" min="0" step="0.01" data-fee-slot="${fee.slot}" data-fee-field="amount" placeholder="0.00" value="${fee.amount_cents ? (fee.amount_cents / 100).toFixed(2) : ""}" />
          <span class="suffix">元</span>
        </div>
        <button class="fee-remove" type="button" data-action="remove-other" data-slot="${fee.slot}" aria-label="删除其他费用">
          <svg viewBox="0 0 24 24" width="15" height="15" fill="none"><path d="M6 6l12 12M18 6 6 18" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>
        </button>
      </div>`,
    )
    .join("");
}

function previousBillForEditor(data, bill) {
  return (data.bills || []).find(
    (candidate) =>
      candidate.id !== bill.id &&
      candidate.status === "confirmed" &&
      candidate.start_date < bill.start_date,
  ) || null;
}

function comparisonDeltaInfo(deltaCents, previousCents) {
  const absolute = Math.abs(Number(deltaCents || 0));
  const direction = deltaCents > 0 ? "增加" : deltaCents < 0 ? "减少" : "持平";
  const className =
    absolute > 10000
      ? "is-alert"
      : deltaCents > 0
        ? "is-up"
        : deltaCents < 0
          ? "is-down"
          : "is-even";
  const rate = previousCents
    ? ` · ${((absolute / Math.abs(previousCents)) * 100).toFixed(1)}%`
    : "";
  return {
    text: `${direction} ${absolute ? money(absolute) : ""}${absolute ? rate : ""}`,
    className,
  };
}

function comparisonUtilityHTML(key, label, previousCents, currentCents, previousBill) {
  const delta = currentCents - previousCents;
  const deltaInfo = comparisonDeltaInfo(delta, previousCents);
  return `
    <div class="utility-compare-row ${deltaInfo.className}" data-compare-key="${key}" data-previous-cents="${previousCents}">
      <div class="utility-compare-title">
        <strong>${label}</strong>
        <span>上期 ${numberText(previousBill[`${key}_usage`], key === "electric" ? " 度" : " 吨")}</span>
      </div>
      <div class="utility-compare-prices">
        <div><span>上期</span><strong>${money(previousCents)}</strong></div>
        <i>→</i>
        <div><span>本期</span><strong data-compare-current>${money(currentCents)}</strong></div>
      </div>
      <div class="utility-compare-delta" data-compare-delta>${deltaInfo.text}</div>
    </div>`;
}

function previousBillCardHTML(previous, bill) {
  if (!previous) {
    return `
      <section class="editor-context-card previous-bill-card">
        <div class="context-card-head">
          <div><span class="context-kicker">上期对比</span><strong>暂无上期收据</strong></div>
        </div>
        <p class="context-empty">这是该房间的首张收据，填写期初读数后即可继续。</p>
      </section>`;
  }
  return `
    <section class="editor-context-card previous-bill-card">
      <div class="context-card-head">
        <div>
          <span class="context-kicker">上期对比</span>
          <strong>${esc(previous.start_date)} 至 ${esc(previous.end_date)}</strong>
        </div>
        <a class="context-link" href="#/bills/${previous.id}">查看</a>
      </div>
      <div class="utility-compare-list">
        ${comparisonUtilityHTML("electric", "电费", previous.electric_cents, bill.electric_cents, previous)}
        ${comparisonUtilityHTML("water", "水费", previous.water_cents, bill.water_cents, previous)}
      </div>
      <div class="comparison-total-row ${comparisonDeltaInfo(bill.total_cents - previous.total_cents, previous.total_cents).className}" data-compare-key="total" data-previous-cents="${previous.total_cents}">
        <div>
          <span>账单合计</span>
          <small>上期 ${money(previous.total_cents)} · ${statusInfo(previous).label}</small>
        </div>
        <strong data-compare-current>${money(bill.total_cents)}</strong>
        <span class="utility-compare-delta" data-compare-delta>${comparisonDeltaInfo(bill.total_cents - previous.total_cents, previous.total_cents).text}</span>
      </div>
    </section>`;
}

function receiptCalendarHTML(data, bill) {
  const year = Number(String(bill.ledger_month || "").slice(0, 4));
  if (!year) return "";
  const bills = data.bills || [];
  let paidCount = 0;
  const months = Array.from({ length: 12 }, (_, index) => {
    const month = `${year}-${String(index + 1).padStart(2, "0")}`;
    const matching = bills.find(
      (candidate) =>
        candidate.ledger_month === month &&
        candidate.status !== "void" &&
        candidate.id !== bill.id,
    ) || (bill.ledger_month === month ? bill : null);
    let stateClass = "";
    let stateLabel = "无收据";
    if (matching) {
      if (matching.status === "draft") {
        stateClass = "is-draft";
        stateLabel = "草稿";
      } else if (matching.payment_status === "paid") {
        stateClass = "is-paid";
        stateLabel = "已收";
        paidCount += 1;
      } else {
        stateClass = "is-unpaid";
        stateLabel = matching.payment_status === "partial" ? "部分收款" : "未收";
      }
    }
    if (month === bill.ledger_month) stateClass += " is-current";
    return `
      <div class="month-tile ${stateClass}" title="${month} ${stateLabel}">
        <strong>${index + 1}月</strong>
        <span>${stateLabel}</span>
      </div>`;
  });
  return `
    <section class="editor-context-card receipt-calendar-card">
      <div class="context-card-head">
        <div><span class="context-kicker">月度收据</span><strong>${year} 年 12 个月</strong></div>
        <div class="year-progress"><strong>${paidCount}</strong><span>个月已收</span></div>
      </div>
      <div class="calendar-legend"><i class="paid"></i>浅蓝色表示本月已收 <i class="unpaid"></i>未收 <i class="draft"></i>草稿</div>
      <div class="receipt-month-grid">${months.join("")}</div>
    </section>`;
}

function billEditorHTML(data, bill) {
  const room = data.room;
  const otherFees = (bill.other_fees || []).map((fee) => ({ ...fee }));
  const previousBill = previousBillForEditor(data, bill);
  const electricLocked = Boolean(bill.electric_auto_locked);
  const waterLocked = Boolean(bill.water_auto_locked);
  const prevElectric = bill.prev_electric === null || bill.prev_electric === undefined
    ? `<input class="reading-input table-prev-input" data-bill-field="prev_electric" type="number" step="0.01" min="0" placeholder="期初" value="" />`
    : `<div class="reading-static">${paperNumber(bill.prev_electric)}</div>`;
  const prevWater = bill.prev_water === null || bill.prev_water === undefined
    ? `<input class="reading-input table-prev-input" data-bill-field="prev_water" type="number" step="0.01" min="0" placeholder="期初" value="" />`
    : `<div class="reading-static">${paperNumber(bill.prev_water)}</div>`;
  return `
    <div class="receipt-layout">
      <section class="editor-card">
        <div class="editor-head">
          <div class="editor-head-top">
            <div>
              <h2 class="editor-title">本月收据</h2>
              <div class="editor-sub">${esc(room.property_name)} · ${esc(room.tenant_name || "未填写租客")}</div>
            </div>
            ${statusBadge(bill)}
          </div>
          <div class="period-strip">
            <span class="period-date">${esc(bill.start_date)}</span>
            <span class="period-arrow">→</span>
            <span class="period-date">${esc(bill.end_date)}</span>
            <span class="period-arrow">·</span>
            <span style="font-size:9.5px;color:var(--muted)">只需填写下面两个本月读数</span>
          </div>
        </div>
        <div class="editor-body">
          <section class="editor-section">
            <div class="section-label">
              <strong>本月水电</strong>
              <button class="link-button" type="button" data-action="unlock-rates">解锁单价</button>
            </div>
            <div class="table-scroll entry-table-wrap">
              <table class="entry-table">
                <thead><tr><th>项目</th><th>上月读数</th><th>本月读数</th><th class="align-right">实用读数</th><th>单价</th><th class="align-right">金额</th></tr></thead>
                <tbody>
                  <tr>
                    <td><span class="entry-item"><span class="meter-dot"></span>电费</span></td>
                    <td class="entry-reading">${prevElectric}</td>
                    <td class="entry-reading">
                      <div class="auto-reading-control ${electricLocked ? "is-locked" : ""}">
                        <input class="reading-input table-current-input" data-bill-field="current_electric" type="number" step="0.01" min="0" placeholder="0.00" value="${bill.current_electric ?? ""}" ${electricLocked ? 'readonly tabindex="-1"' : ""} />
                        ${electricLocked ? `<button class="reading-unlock" type="button" data-action="unlock-reading" data-field="electric">解锁</button>` : ""}
                      </div>
                    </td>
                    <td class="align-right tabular" id="electricUsageText">${numberText(bill.electric_usage, " 度")}</td>
                    <td><div class="unit-input"><span>¥</span><input data-bill-field="electric_rate" type="number" min="0" step="0.01" value="${paperNumber(bill.electric_rate)}" readonly tabindex="-1" /><span>/ 度</span></div></td>
                    <td class="align-right price-cell" id="electricAmountText">${money(bill.electric_cents)}</td>
                  </tr>
                  <tr>
                    <td><span class="entry-item entry-item--water"><span class="meter-dot"></span>水费</span></td>
                    <td class="entry-reading">${prevWater}</td>
                    <td class="entry-reading">
                      <div class="auto-reading-control ${waterLocked ? "is-locked" : ""}">
                        <input class="reading-input table-current-input" data-bill-field="current_water" type="number" step="0.01" min="0" placeholder="0.00" value="${bill.current_water ?? ""}" ${waterLocked ? 'readonly tabindex="-1"' : ""} />
                        ${waterLocked ? `<button class="reading-unlock" type="button" data-action="unlock-reading" data-field="water">解锁</button>` : ""}
                      </div>
                    </td>
                    <td class="align-right tabular" id="waterUsageText">${numberText(bill.water_usage, " 吨")}</td>
                    <td><div class="unit-input"><span>¥</span><input data-bill-field="water_rate" type="number" min="0" step="0.01" value="${paperNumber(bill.water_rate)}" readonly tabindex="-1" /><span>/ 吨</span></div></td>
                    <td class="align-right price-cell" id="waterAmountText">${money(bill.water_cents)}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <section class="editor-section">
            <div class="section-label">
              <strong>其他费用</strong>
              <span>默认隐藏，只有需要时才添加</span>
            </div>
            <div class="fee-list" id="feeList">${feeListHTML(otherFees)}</div>
            <button class="btn btn-ghost btn-small" type="button" data-action="add-other" style="margin-top:10px" ${otherFees.length >= 3 ? "disabled" : ""}>+ 添加其他费用</button>
          </section>

          <section class="editor-section">
            <div class="section-label">
              <strong>房租与账单信息</strong>
              <span>不改也可以，默认沿用上期</span>
            </div>
            <div class="field-grid">
              <div class="field">
                <label>房租</label>
                <div class="input-affix"><span class="prefix">¥</span><input class="input has-suffix amount-input" data-bill-field="rent" type="number" step="0.01" value="${(bill.rent_cents / 100).toFixed(2)}" /><span class="suffix">元</span></div>
                <div class="field-hint">允许负数，用于减免或调整。</div>
              </div>
              <div class="field">
                <label>收据日期</label>
                <input class="input" data-bill-field="issue_date" type="date" value="${esc(bill.issue_date)}" />
              </div>
              <div class="field">
                <label>周期开始</label>
                <input class="input" data-bill-field="start_date" type="date" value="${esc(bill.start_date)}" />
              </div>
              <div class="field">
                <label>周期结束</label>
                <input class="input" data-bill-field="end_date" type="date" value="${esc(bill.end_date)}" />
              </div>
              <div class="field">
                <label>经营账期</label>
                <input class="input" data-bill-field="ledger_month" type="month" value="${esc(bill.ledger_month)}" />
              </div>
              <div class="field field--span2">
                <label>备注</label>
                <input class="input" data-bill-field="note" placeholder="可选" value="${esc(bill.note || "")}" />
              </div>
            </div>
          </section>
        </div>
      </section>

      <aside class="editor-context">
        <section class="editor-context-card editor-action-card">
          <div class="context-card-head">
            <div>
              <span class="context-kicker">确认并继续</span>
              <strong>填写完成后直接进入下一间</strong>
            </div>
            ${statusBadge(bill)}
          </div>
          <div class="editor-total">
            <div>
              <span>本期应收</span>
              <div class="total-number" id="liveTotal">${money(bill.total_cents)}</div>
            </div>
            <div class="total-words" id="liveWords">${esc(rmbUpper(bill.total_cents))}</div>
          </div>
          <div class="payment-mode-control">
            <div>
              <strong>确认后收款状态</strong>
              <span id="paymentModeHint">默认已收，同时自动进入下一间待处理房间。</span>
            </div>
            <div class="payment-mode-buttons">
              <button class="payment-mode-button active" type="button" data-action="set-payment-mode" data-mode="paid">已收</button>
              <button class="payment-mode-button" type="button" data-action="set-payment-mode" data-mode="unpaid">未收</button>
            </div>
          </div>
          <div class="editor-actions">
            <span class="save-state" id="saveState">已载入</span>
            <div class="editor-action-buttons">
              <button class="btn btn-secondary" type="button" data-action="save-bill">保存草稿</button>
              <button class="btn btn-primary btn-large" type="button" data-action="confirm-bill">确认并进入下一间</button>
            </div>
            <span class="shortcut-hint">按 Enter 可直接确认</span>
          </div>
        </section>
        ${previousBillCardHTML(previousBill, bill)}
        ${receiptCalendarHTML(data, bill)}
      </aside>
    </div>`;
}

function mountBillEditor(data, bill) {
  state.editor = {
    bill,
    roomData: data,
    version: 0,
    dirty: false,
    saving: null,
    saveQueued: false,
    saveTimer: null,
    paymentMode: "paid",
  };
  updateEditorPreview();
}

function collectFeesFromDOM() {
  const fees = [];
  els("[data-fee-slot]").forEach((node) => {
    const slot = Number(node.dataset.feeSlot);
    let fee = fees.find((item) => item.slot === slot);
    if (!fee) {
      fee = { slot, name: "", amount_cents: 0 };
      fees.push(fee);
    }
    if (node.dataset.feeField === "name") fee.name = node.value;
    if (node.dataset.feeField === "amount") fee.amount_cents = toCents(node.value);
  });
  return fees.sort((a, b) => a.slot - b.slot);
}

function editorValues() {
  const field = (name) => el(`[data-bill-field="${name}"]`)?.value;
  const base = state.editor?.bill || {};
  const fees = collectFeesFromDOM();
  return {
    ...base,
    start_date: field("start_date") ?? base.start_date,
    end_date: field("end_date") ?? base.end_date,
    issue_date: field("issue_date") ?? base.issue_date,
    ledger_month: field("ledger_month") ?? base.ledger_month,
    rent_cents: toCents(field("rent") ?? base.rent),
    prev_electric: "prev_electric" in base && !el('[data-bill-field="prev_electric"]') ? base.prev_electric : toNumber(field("prev_electric")),
    current_electric: toNumber(field("current_electric")),
    electric_rate: toNumber(field("electric_rate") ?? base.electric_rate),
    prev_water: "prev_water" in base && !el('[data-bill-field="prev_water"]') ? base.prev_water : toNumber(field("prev_water")),
    current_water: toNumber(field("current_water")),
    water_rate: toNumber(field("water_rate") ?? base.water_rate),
    note: field("note") ?? base.note,
    other_fees: fees,
  };
}

function calculatePreview(values) {
  const electricUsage = values.prev_electric !== null && values.current_electric !== null
    ? roundMoney(values.current_electric - values.prev_electric)
    : null;
  const waterUsage = values.prev_water !== null && values.current_water !== null
    ? roundMoney(values.current_water - values.prev_water)
    : null;
  const electricCents = electricUsage === null ? 0 : Math.round(electricUsage * Number(values.electric_rate || 0) * 100);
  const waterCents = waterUsage === null ? 0 : Math.round(waterUsage * Number(values.water_rate || 0) * 100);
  const otherCents = sum(values.other_fees || [], (fee) => fee.amount_cents);
  return {
    electricUsage,
    waterUsage,
    electricCents,
    waterCents,
    otherCents,
    totalCents: Number(values.rent_cents || 0) + electricCents + waterCents + otherCents,
  };
}

function updateComparisonMetric(key, currentCents) {
  const row = el(`[data-compare-key="${key}"]`);
  if (!row) return;
  const previousCents = Number(row.dataset.previousCents || 0);
  const delta = Number(currentCents || 0) - previousCents;
  const info = comparisonDeltaInfo(delta, previousCents);
  const current = el("[data-compare-current]", row);
  const deltaNode = el("[data-compare-delta]", row);
  if (current) current.textContent = money(currentCents);
  if (deltaNode) deltaNode.textContent = info.text;
  row.classList.remove("is-alert", "is-up", "is-down", "is-even");
  row.classList.add(info.className);
}

function updateEditorPreview() {
  if (!state.editor) return;
  const values = editorValues();
  const calc = calculatePreview(values);
  if (el("#liveTotal")) el("#liveTotal").textContent = money(calc.totalCents);
  if (el("#liveWords")) el("#liveWords").textContent = rmbUpper(calc.totalCents);
  if (el("#electricUsageText")) el("#electricUsageText").textContent = numberText(calc.electricUsage, " 度");
  if (el("#waterUsageText")) el("#waterUsageText").textContent = numberText(calc.waterUsage, " 吨");
  if (el("#electricAmountText")) el("#electricAmountText").textContent = money(calc.electricCents);
  if (el("#waterAmountText")) el("#waterAmountText").textContent = money(calc.waterCents);
  if (el("#rateElectricText")) el("#rateElectricText").textContent = paperNumber(values.electric_rate);
  if (el("#rateWaterText")) el("#rateWaterText").textContent = paperNumber(values.water_rate);
  updateComparisonMetric("electric", calc.electricCents);
  updateComparisonMetric("water", calc.waterCents);
  updateComparisonMetric("total", calc.totalCents);
}

function editorPayload() {
  const values = editorValues();
  const payload = {
    start_date: values.start_date,
    end_date: values.end_date,
    issue_date: values.issue_date,
    ledger_month: values.ledger_month,
    rent: values.rent_cents / 100,
    current_electric: values.current_electric,
    electric_rate: values.electric_rate,
    current_water: values.current_water,
    water_rate: values.water_rate,
    note: values.note || "",
  };
  if (el('[data-bill-field="prev_electric"]')) payload.prev_electric = values.prev_electric;
  if (el('[data-bill-field="prev_water"]')) payload.prev_water = values.prev_water;
  for (let slot = 1; slot <= 3; slot += 1) {
    const fee = values.other_fees.find((item) => Number(item.slot) === slot);
    payload[`other${slot}_name`] = fee?.name || "";
    payload[`other${slot}`] = fee ? fee.amount_cents / 100 : "";
  }
  return payload;
}

function setSaveState(text, mode = "") {
  const node = el("#saveState");
  if (!node) return;
  node.textContent = text;
  node.className = `save-state ${mode}`;
}

function queueEditorSave() {
  if (!state.editor) return;
  state.editor.version += 1;
  state.editor.dirty = true;
  setSaveState("有更改，稍后自动保存");
  clearTimeout(state.editor.saveTimer);
  state.editor.saveTimer = setTimeout(() => {
    saveBillDraft().catch(() => {});
  }, 800);
}

async function saveBillDraft({ silent = false } = {}) {
  if (!state.editor) return null;
  if (state.editor.saving) {
    state.editor.saveQueued = true;
    return state.editor.saving;
  }
  clearTimeout(state.editor.saveTimer);
  if (!state.editor.dirty) return state.editor.bill;
  const version = state.editor.version;
  const billId = state.editor.bill.id;
  setSaveState("正在保存…", "saving");
  state.editor.saving = api(`/api/bills/${billId}`, {
    method: "PUT",
    body: editorPayload(),
  })
    .then((saved) => {
      if (!state.editor) return saved;
      if (state.editor.version === version) {
        state.editor.bill = saved;
        state.editor.dirty = false;
        setSaveState("已自动保存");
      } else {
        state.editor.saveQueued = true;
      }
      return saved;
    })
    .catch((error) => {
      if (!silent) toast(error.message, "error");
      setSaveState("保存失败，请检查输入", "error");
      throw error;
    })
    .finally(() => {
      if (!state.editor) return;
      state.editor.saving = null;
      if (state.editor.saveQueued) {
        state.editor.saveQueued = false;
        setTimeout(() => saveBillDraft().catch(() => {}), 120);
      }
    });
  return state.editor.saving;
}

async function flushEditor() {
  if (!state.editor) return null;
  for (let index = 0; index < 5; index += 1) {
    if (state.editor.saving) {
      await state.editor.saving;
      continue;
    }
    if (!state.editor.dirty) return state.editor.bill;
    await saveBillDraft();
  }
  return state.editor?.bill || null;
}

async function confirmCurrentBill(button) {
  if (!state.editor) return;
  button.disabled = true;
  const oldText = button.textContent;
  button.textContent = "正在生成…";
  try {
    await flushEditor();
    const confirmed = await api(`/api/bills/${state.editor.bill.id}/confirm`, {
      method: "POST",
      body: { payment_status: state.editor.paymentMode || "paid" },
    });
    state.month = confirmed.ledger_month;
    localStorage.setItem("rental-month", state.month);
    populateMonthSelect();
    let next = confirmed.next_room;
    try {
      const fresh = await api(
        `/api/properties/${confirmed.property_id}/next-room?month=${encodeURIComponent(confirmed.ledger_month)}&after_room_id=${confirmed.room_id}`,
      );
      next = fresh.next_room;
    } catch {
      // Older running servers may not expose the fresh lookup endpoint.
    }
    if (!next) {
      toast(`收据 ${confirmed.receipt_no} 已生成，本房源本月已全部处理`);
      go(`/properties/${confirmed.property_id}`);
      return;
    }
    try {
      let nextBillId = next.bill_id;
      if (next.action === "new") {
        const created = await api(`/api/rooms/${next.room_id}/bills/new`, {
          method: "POST",
          body: {
            custom_dates: true,
            start_date: next.start_date,
            end_date: next.end_date,
            issue_date: localDateISO(),
            ledger_month: state.month,
          },
        });
        nextBillId = created.bill.id;
      }
      toast(`收据 ${confirmed.receipt_no} 已生成，继续 ${next.room_no}`);
      go(`/bills/${nextBillId}`);
    } catch (nextError) {
      toast(`下一间 ${next.room_no} 未能自动打开：${nextError.message}`, "error");
      go(`/rooms/${next.room_id}`);
    }
  } catch (error) {
    toast(error.message, "error");
    button.disabled = false;
    button.textContent = oldText;
  }
}

function addOtherFee() {
  if (!state.editor) return;
  const fees = collectFeesFromDOM();
  if (fees.length >= 3) return;
  const slot = [1, 2, 3].find((value) => !fees.some((fee) => fee.slot === value));
  fees.push({ slot, name: "", amount_cents: 0 });
  state.editor.bill.other_fees = fees;
  el("#feeList").innerHTML = feeListHTML(fees);
  const addButton = el('[data-action="add-other"]');
  if (addButton) addButton.disabled = fees.length >= 3;
  queueEditorSave();
  updateEditorPreview();
}

function removeOtherFee(slot) {
  if (!state.editor) return;
  const fees = collectFeesFromDOM().filter((fee) => Number(fee.slot) !== Number(slot));
  state.editor.bill.other_fees = fees;
  el("#feeList").innerHTML = feeListHTML(fees);
  const addButton = el('[data-action="add-other"]');
  if (addButton) addButton.disabled = fees.length >= 3;
  queueEditorSave();
  updateEditorPreview();
}

function paperReceiptHTML(bill, settings = {}, room = {}) {
  const propertyName = bill.property_name || room.property_name || "";
  const roomNo = bill.room_no || room.room_no || "";
  const tenant = bill.tenant_name || room.tenant_name || "";
  const fees = (bill.other_fees || []).filter((fee) => fee.name || fee.amount_cents);
  return `
    <article class="paper-receipt">
      <div class="paper-head">
        <small>RENT RECEIPT</small>
        <div class="paper-title">${esc(settings.receipt_title || "租金收据")}</div>
        <div class="paper-meta">
          <span>日期：${esc(bill.issue_date || "—")}</span>
          <span>No. ${esc(bill.receipt_no || "草稿")}</span>
        </div>
      </div>
      <div class="paper-property">
        <span>${esc(propertyName)} · ${esc(roomNo)}</span>
        <strong>${settings.show_tenant_on_receipt === "1" || settings.show_tenant_on_receipt === 1 ? esc(tenant) : "住户收据"}</strong>
      </div>
      <div class="paper-rent">
        <span>房租 · ${esc(bill.start_date || "")} 至 ${esc(bill.end_date || "")}</span>
        <strong>${money(bill.rent_cents)}</strong>
      </div>
      <table class="paper-table">
        <thead><tr><th>项目</th><th>上月</th><th>本月</th><th>实用</th><th>单价</th><th>金额</th></tr></thead>
        <tbody>
          <tr>
            <td>电费</td><td>${paperNumber(bill.prev_electric)}</td><td>${paperNumber(bill.current_electric)}</td><td>${paperNumber(bill.electric_usage)}</td><td>${paperNumber(bill.electric_rate)}</td><td>${money(bill.electric_cents)}</td>
          </tr>
          <tr>
            <td>水费</td><td>${paperNumber(bill.prev_water)}</td><td>${paperNumber(bill.current_water)}</td><td>${paperNumber(bill.water_usage)}</td><td>${paperNumber(bill.water_rate)}</td><td>${money(bill.water_cents)}</td>
          </tr>
        </tbody>
      </table>
      ${fees.length ? `<div class="paper-other">${fees.map((fee) => `<div class="paper-other-row"><span>${esc(fee.name || `其他费用${fee.slot}`)}</span><strong>${money(fee.amount_cents)}</strong></div>`).join("")}</div>` : ""}
      <div class="paper-total-box">
        <span>合计金额</span>
        <div class="paper-total-number">${money(bill.total_cents)}</div>
      </div>
      <div class="paper-words">人民币（大写）：${esc(bill.chinese_total || rmbUpper(bill.total_cents))}</div>
      <div class="paper-footer">
        <span>开票人：${esc(settings.issuer_name || "房东")}</span>
        <span>收款人：${esc(settings.payee_name || "房东")}</span>
      </div>
      <div class="paper-stamp">${bill.status === "confirmed" ? "已确认" : "草稿"}</div>
    </article>`;
}

function billViewHTML(bill, data) {
  const info = statusInfo(bill);
  const payments = bill.payments || [];
  const paidPercent = bill.total_cents ? Math.min(100, Math.round((bill.paid_cents / bill.total_cents) * 100)) : 0;
  const otherFees = (bill.other_fees || []).filter((fee) => fee.name || fee.amount_cents);
  return `
    <div class="receipt-view-panel">
      <section class="receipt-summary-card">
        <div class="receipt-summary-top">
          <span class="receipt-no">单号 ${esc(bill.receipt_no || "草稿")}</span>
          ${receiptStatusControl(bill)}
        </div>
        <div class="receipt-summary-amount">${money(bill.total_cents)}</div>
        <div class="receipt-summary-words">人民币 ${esc(bill.chinese_total)}</div>
        <div class="receipt-detail-grid">
          <div class="detail-item"><span>房屋</span><strong>${esc(bill.property_name)} · ${esc(bill.room_no)}</strong></div>
          <div class="detail-item"><span>租客</span><strong>${esc(bill.tenant_name || "未填写")}</strong></div>
          <div class="detail-item"><span>账单周期</span><strong>${esc(bill.start_date)} 至 ${esc(bill.end_date)}</strong></div>
          <div class="detail-item"><span>收据日期</span><strong>${esc(bill.issue_date)}</strong></div>
          <div class="detail-item"><span>电费</span><strong>${money(bill.electric_cents)} · ${numberText(bill.electric_usage, " 度")}</strong></div>
          <div class="detail-item"><span>水费</span><strong>${money(bill.water_cents)} · ${numberText(bill.water_usage, " 吨")}</strong></div>
          ${otherFees.length ? `<div class="detail-item"><span>其他费用</span><strong>${otherFees.map((fee) => `${esc(fee.name)} ${money(fee.amount_cents)}`).join(" · ")}</strong></div>` : ""}
        </div>
        <div style="margin-top:20px">
          <div style="display:flex;justify-content:space-between;font-size:9.5px;color:var(--muted);margin-bottom:6px"><span>收款进度</span><span>${money(bill.paid_cents)} / ${money(bill.total_cents)}</span></div>
          <div class="progress-track"><span style="width:${paidPercent}%"></span></div>
        </div>
        <div class="receipt-actions">
          ${bill.status === "confirmed" ? `<button class="btn btn-primary" data-action="download-pdf">导出 PDF</button>` : ""}
          ${bill.status === "confirmed" && bill.outstanding_cents > 0 ? `<button class="btn btn-secondary" data-action="payment-add">登记收款</button>` : ""}
          ${bill.status === "confirmed" ? `<button class="btn btn-ghost" data-action="new-receipt">新增下一期</button>` : ""}
          ${bill.status === "confirmed" && bill.paid_cents === 0 ? `<button class="btn btn-danger btn-small" data-action="void-bill">作废</button>` : ""}
        </div>
        <div style="margin-top:22px;padding-top:18px;border-top:1px solid var(--line)">
          <div class="section-label"><strong>收款记录</strong><span>${payments.length} 笔</span></div>
          ${payments.length ? `<div class="payment-list">${payments.map((payment) => `
            <div class="payment-row">
              <div><strong>${money(payment.amount_cents)}</strong><small> · ${esc(payment.method)} · ${esc(payment.paid_at)}</small>${payment.note ? `<small> · ${esc(payment.note)}</small>` : ""}</div>
              <button class="link-button" data-action="payment-delete" data-payment-id="${payment.id}" style="color:var(--danger)">删除</button>
            </div>`).join("")}</div>` : `<div class="field-hint">还没有收款记录。</div>`}
        </div>
      </section>
      <aside class="preview-panel">
        <div class="preview-label"><span>正式收据</span><span>${bill.status === "void" ? "已作废" : "可导出或打印"}</span></div>
        ${paperReceiptHTML(bill, state.bootstrap.settings, data.room)}
      </aside>
    </div>`;
}

function historyListHTML(data, currentId) {
  const bills = data.bills || [];
  if (!bills.length) return `<div class="field-hint">暂无历史收据。</div>`;
  return `<div class="history-list">${bills.map((bill) => `
    <a class="history-row" href="#/bills/${bill.id}">
      <div><strong>${esc(bill.start_date)} 至 ${esc(bill.end_date)}</strong><div class="cell-sub">${esc(bill.receipt_no || "草稿")}${bill.id === currentId ? " · 当前" : ""}</div></div>
      <span class="money">${money(bill.total_cents)}</span>
      ${statusBadge(bill)}
    </a>`).join("")}</div>`;
}

function openDateModal({ custom = false } = {}) {
  const data = state.currentRoomDetail;
  if (!data) return;
  const room = data.room;
  const latest = data.latest_bill;
  const start = custom && latest ? data.next_start : data.suggested_start;
  const end = custom && latest ? data.next_end : data.suggested_end;
  const ledgerMonth = end ? end.slice(0, 7) : state.month;
  const modal = openModal({
    title: latest ? "补录或调整账单周期" : "确认第一张收据的日期",
    subtitle: `${room.property_name} · ${room.room_no}｜先确认日期，再进入本月收据`,
    size: "modal-small",
    body: `
      <div class="inline-note">账单周期决定这张收据覆盖的月份。首次开单确认后，后面点“新增”会自动进入下一期。</div>
      <div class="form-grid" style="margin-top:16px">
        <div class="field"><label>周期开始</label><input class="input" id="dateStart" type="date" value="${esc(start || "")}" /></div>
        <div class="field"><label>周期结束</label><input class="input" id="dateEnd" type="date" value="${esc(end || "")}" /></div>
        <div class="field"><label>收据日期</label><input class="input" id="dateIssue" type="date" value="${localDateISO()}" /></div>
        <div class="field"><label>经营账期</label><input class="input" id="dateLedger" type="month" value="${esc(ledgerMonth || state.month)}" /></div>
      </div>`,
    footer: `
      <button class="btn btn-ghost" type="button" data-close-date>取消</button>
      <button class="btn btn-primary" type="button" data-confirm-date>确定日期</button>`,
  });
  el("[data-close-date]", modal.modal).addEventListener("click", modal.close);
  el("[data-confirm-date]", modal.modal).addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      const result = await api(`/api/rooms/${room.id}/bills/new`, {
        method: "POST",
        body: {
          custom_dates: true,
          start_date: el("#dateStart", modal.modal).value,
          end_date: el("#dateEnd", modal.modal).value,
          issue_date: el("#dateIssue", modal.modal).value,
          ledger_month: el("#dateLedger", modal.modal).value,
        },
      });
      modal.close();
      toast(`已进入 ${result.bill.start_date} 至 ${result.bill.end_date} 的收据`);
      go(`/rooms/${room.id}`);
    } catch (error) {
      toast(error.message, "error");
      button.disabled = false;
    }
  });
}

async function createNextReceipt() {
  const data = state.currentRoomDetail;
  if (!data) return;
  const room = data.room;
  if (room.status !== "rented") {
    toast("空置或停用的房间不能新增收据", "error");
    return;
  }
  if (!data.latest_bill) {
    openDateModal();
    return;
  }
  try {
    const result = await api(`/api/rooms/${room.id}/bills/new`, {
      method: "POST",
      body: {},
    });
    const label = result.reused ? "已打开现有草稿" : `已进入 ${result.bill.start_date} 至 ${result.bill.end_date}`;
    toast(label);
    go(`/rooms/${room.id}`);
  } catch (error) {
    toast(error.message, "error");
  }
}

function openPropertyModal(property = null) {
  const editing = Boolean(property);
  const modal = openModal({
    title: editing ? "编辑房源" : "新增房源",
    subtitle: "一个房源下可以管理多个房间。",
    size: "modal-small",
    body: `
      <div class="form-grid">
        <div class="field field--full"><label>房源名称</label><input class="input" id="propertyName" placeholder="例如：新村" value="${esc(property?.name || "")}" /></div>
        <div class="field field--full"><label>详细地址</label><input class="input" id="propertyAddress" placeholder="例如：新村住宅区 3 栋" value="${esc(property?.address || "")}" /></div>
        <div class="field field--full"><label>备注</label><textarea class="textarea" id="propertyNote" placeholder="可选">${esc(property?.note || "")}</textarea></div>
      </div>`,
    footer: `
      <button class="btn btn-ghost" type="button" data-cancel-property>取消</button>
      <button class="btn btn-primary" type="button" data-save-property>${editing ? "保存修改" : "创建房源"}</button>`,
  });
  el("[data-cancel-property]", modal.modal).addEventListener("click", modal.close);
  el("[data-save-property]", modal.modal).addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      const payload = {
        name: el("#propertyName", modal.modal).value.trim(),
        address: el("#propertyAddress", modal.modal).value.trim(),
        note: el("#propertyNote", modal.modal).value.trim(),
      };
      const result = editing
        ? await api(`/api/properties/${property.id}`, { method: "PUT", body: payload })
        : await api("/api/properties", { method: "POST", body: payload });
      modal.close();
      toast(editing ? "房源已更新" : "房源已创建");
      await reloadBootstrap();
      go(`/properties/${result.id}`);
    } catch (error) {
      toast(error.message, "error");
      button.disabled = false;
    }
  });
}

function openRoomModal(room = null, propertyId = null) {
  const editing = Boolean(room);
  const parentId = propertyId || room?.property_id || state.currentPropertyDetail?.property?.id;
  if (!parentId) {
    toast("请先选择房源", "error");
    return;
  }
  const modal = openModal({
    title: editing ? "编辑房间" : "新增房间",
    subtitle: "房租和单价会作为之后开收据的默认值。",
    size: "modal-wide",
    body: `
      <div class="form-grid">
        <div class="field"><label>房间号</label><input class="input" id="roomNo" placeholder="例如：402" value="${esc(room?.room_no || "")}" /></div>
        <div class="field"><label>房间状态</label>
          <select class="select" id="roomStatus">
            <option value="rented" ${room?.status === "rented" || !room ? "selected" : ""}>出租中</option>
            <option value="vacant" ${room?.status === "vacant" ? "selected" : ""}>空置</option>
            <option value="inactive" ${room?.status === "inactive" ? "selected" : ""}>停用</option>
          </select>
        </div>
        <div class="field"><label>租客姓名</label><input class="input" id="roomTenant" placeholder="可选" value="${esc(room?.tenant_name || "")}" /></div>
        <div class="field"><label>联系电话</label><input class="input" id="roomPhone" placeholder="可选" value="${esc(room?.phone || "")}" /></div>
        <div class="field"><label>默认房租</label><div class="input-affix"><span class="prefix">¥</span><input class="input has-suffix" id="roomRent" type="number" min="0" step="0.01" value="${room ? (room.rent_cents / 100).toFixed(2) : "0.00"}" /><span class="suffix">元</span></div></div>
        <div class="field"><label>默认电费单价</label><div class="input-affix"><span class="prefix">¥</span><input class="input has-suffix" id="roomElectricRate" type="number" min="0" step="0.01" value="${room ? (room.electric_rate_cents / 100).toFixed(2) : "1.00"}" /><span class="suffix">/度</span></div></div>
        <div class="field"><label>默认水费单价</label><div class="input-affix"><span class="prefix">¥</span><input class="input has-suffix" id="roomWaterRate" type="number" min="0" step="0.01" value="${room ? (room.water_rate_cents / 100).toFixed(2) : "5.00"}" /><span class="suffix">/吨</span></div></div>
        <div class="field"><label>抄表日</label><input class="input" id="roomBillingDay" type="number" min="1" max="28" value="${room?.billing_day || 19}" /><div class="field-hint">例如 19 日，则周期为 19 日至次月 18 日。</div></div>
        <div class="field">
          <label class="checkbox-inline"><input id="roomElectricAutoEnabled" type="checkbox" ${room?.electric_auto_enabled ? "checked" : ""} /> 电表每月自动增加</label>
          <div class="input-affix"><input class="input" id="roomElectricAutoIncrement" type="number" min="0" step="0.01" value="${room ? (room.electric_auto_increment_x100 / 100).toFixed(2) : "0.00"}" placeholder="0.00" /><span class="suffix">度 / 月</span></div>
          <div class="field-hint">新单本月读数 = 上期本月读数 + 此增量，并默认锁定。</div>
        </div>
        <div class="field">
          <label class="checkbox-inline"><input id="roomWaterAutoEnabled" type="checkbox" ${room?.water_auto_enabled ? "checked" : ""} /> 水表每月自动增加</label>
          <div class="input-affix"><input class="input" id="roomWaterAutoIncrement" type="number" min="0" step="0.01" value="${room ? (room.water_auto_increment_x100 / 100).toFixed(2) : "0.00"}" placeholder="0.00" /><span class="suffix">吨 / 月</span></div>
          <div class="field-hint">新单本月读数 = 上期本月读数 + 此增量，并默认锁定。</div>
        </div>
        <div class="field field--full"><label>备注</label><textarea class="textarea" id="roomNote" placeholder="可选">${esc(room?.note || "")}</textarea></div>
      </div>`,
    footer: `
      <button class="btn btn-ghost" type="button" data-cancel-room>取消</button>
      <button class="btn btn-primary" type="button" data-save-room>${editing ? "保存修改" : "创建房间"}</button>`,
  });
  el("[data-cancel-room]", modal.modal).addEventListener("click", modal.close);
  el("[data-save-room]", modal.modal).addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      const payload = {
        property_id: parentId,
        room_no: el("#roomNo", modal.modal).value.trim(),
        tenant_name: el("#roomTenant", modal.modal).value.trim(),
        phone: el("#roomPhone", modal.modal).value.trim(),
        rent: el("#roomRent", modal.modal).value,
        electric_rate: el("#roomElectricRate", modal.modal).value,
        water_rate: el("#roomWaterRate", modal.modal).value,
        billing_day: el("#roomBillingDay", modal.modal).value,
        electric_auto_enabled: el("#roomElectricAutoEnabled", modal.modal).checked,
        electric_auto_increment: el("#roomElectricAutoIncrement", modal.modal).value,
        water_auto_enabled: el("#roomWaterAutoEnabled", modal.modal).checked,
        water_auto_increment: el("#roomWaterAutoIncrement", modal.modal).value,
        status: el("#roomStatus", modal.modal).value,
        note: el("#roomNote", modal.modal).value.trim(),
      };
      const result = editing
        ? await api(`/api/rooms/${room.id}`, { method: "PUT", body: payload })
        : await api("/api/rooms", { method: "POST", body: payload });
      modal.close();
      toast(editing ? "房间资料已更新" : "房间已添加");
      await reloadBootstrap();
      go(editing ? `/rooms/${result.id}` : `/properties/${parentId}`);
    } catch (error) {
      toast(error.message, "error");
      button.disabled = false;
    }
  });
}

function openPaymentModal(bill) {
  if (!bill) return;
  const outstanding = Math.max(0, bill.outstanding_cents || bill.total_cents);
  const modal = openModal({
    title: "登记收款",
    subtitle: `${bill.property_name} · ${bill.room_no}｜单号 ${bill.receipt_no || "草稿"}`,
    size: "modal-small",
    body: `
      <div class="form-grid">
        <div class="field field--full"><label>收款金额</label><div class="input-affix"><span class="prefix">¥</span><input class="input has-suffix" id="paymentAmount" type="number" min="0.01" step="0.01" value="${(outstanding / 100).toFixed(2)}" /><span class="suffix">元</span></div><div class="field-hint">应收 ${money(bill.total_cents)}，已收 ${money(bill.paid_cents)}。</div></div>
        <div class="field"><label>收款日期</label><input class="input" id="paymentDate" type="date" value="${localDateISO()}" /></div>
        <div class="field"><label>收款方式</label><select class="select" id="paymentMethod"><option>微信</option><option>支付宝</option><option>现金</option><option>银行卡</option><option>其他</option></select></div>
        <div class="field field--full"><label>备注</label><input class="input" id="paymentNote" placeholder="可选" /></div>
      </div>`,
    footer: `<button class="btn btn-ghost" data-cancel-payment>取消</button><button class="btn btn-primary" data-save-payment>确认收款</button>`,
  });
  el("[data-cancel-payment]", modal.modal).addEventListener("click", modal.close);
  el("[data-save-payment]", modal.modal).addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      await api(`/api/bills/${bill.id}/payments`, {
        method: "POST",
        body: {
          amount: el("#paymentAmount", modal.modal).value,
          paid_at: el("#paymentDate", modal.modal).value,
          method: el("#paymentMethod", modal.modal).value,
          note: el("#paymentNote", modal.modal).value.trim(),
        },
      });
      modal.close();
      toast("收款已登记");
      await reloadBootstrap();
      renderRoute();
    } catch (error) {
      toast(error.message, "error");
      button.disabled = false;
    }
  });
}

function openVoidModal(bill) {
  if (!bill) return;
  const modal = openModal({
    title: "作废这张收据",
    subtitle: "作废后不再计入收入和总台账。已有收款记录时不能作废。",
    size: "modal-small",
    body: `<div class="field"><label>作废原因</label><textarea class="textarea" id="voidReason" placeholder="例如：房间号填错，重新开单"></textarea></div>`,
    footer: `<button class="btn btn-ghost" data-cancel-void>取消</button><button class="btn btn-danger" data-save-void>确认作废</button>`,
  });
  el("[data-cancel-void]", modal.modal).addEventListener("click", modal.close);
  el("[data-save-void]", modal.modal).addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      await api(`/api/bills/${bill.id}/void`, {
        method: "POST",
        body: { reason: el("#voidReason", modal.modal).value.trim() },
      });
      modal.close();
      toast("收据已作废");
      await reloadBootstrap();
      renderRoute();
    } catch (error) {
      toast(error.message, "error");
      button.disabled = false;
    }
  });
}

async function renderReceipts(token) {
  const [data, propertyData] = await Promise.all([
    api(`/api/bills?month=${encodeURIComponent(state.month)}`),
    api(`/api/properties?month=${encodeURIComponent(state.month)}`),
  ]);
  if (token !== state.token) return;
  state.receiptRows = data.bills;
  state.receiptProperties = propertyData.properties;
  state.selectedBillIds = new Set(
    [...state.selectedBillIds].filter((id) => data.bills.some((bill) => bill.id === id && bill.status === "confirmed")),
  );
  view.innerHTML = `
    <div class="view-content">
      <div class="page-lead">
        <div>
          <h2>${monthLabel(state.month)}的收据</h2>
          <p>草稿、未收、部分收款和已收都在这里。可以勾选已确认收据批量导出。</p>
        </div>
        <div class="page-actions">
          <button class="btn btn-secondary" data-action="export-selected-pdf" id="exportPdfButton" disabled>合并 PDF</button>
          <button class="btn btn-primary" data-action="export-selected-zip" id="exportZipButton" disabled>导出所选 PDF</button>
        </div>
      </div>
      <div class="toolbar">
        <div class="filter-tabs" id="receiptTabs">
          ${receiptFilterButton("all", "全部")}
          ${receiptFilterButton("unpaid", "未收")}
          ${receiptFilterButton("partial", "部分收款")}
          ${receiptFilterButton("paid", "已收")}
          ${receiptFilterButton("draft", "草稿")}
          ${receiptFilterButton("void", "作废")}
        </div>
        <div class="filter-row">
          <select class="select" id="receiptPropertyFilter">
            <option value="all">全部房源</option>
            ${state.receiptProperties.map((property) => `<option value="${property.id}" ${String(state.receiptProperty) === String(property.id) ? "selected" : ""}>${esc(property.name)}</option>`).join("")}
          </select>
          <button class="btn btn-ghost btn-small" data-action="select-all-bills">全选已确认</button>
          <span class="field-hint" id="selectedCount">已选 0 张</span>
        </div>
      </div>
      <div id="receiptTableWrap"></div>
    </div>`;
  drawReceiptTable();
}

function receiptFilterButton(key, label) {
  return `<button type="button" data-action="filter-receipts" data-filter="${key}" class="${state.receiptFilter === key ? "active" : ""}">${label}</button>`;
}

function filteredReceiptRows() {
  return state.receiptRows.filter((bill) => {
    if (state.receiptProperty !== "all" && String(bill.property_id) !== String(state.receiptProperty)) return false;
    if (state.receiptFilter === "all") return true;
    if (state.receiptFilter === "draft") return bill.status === "draft";
    if (state.receiptFilter === "void") return bill.status === "void";
    return bill.status === "confirmed" && bill.payment_status === state.receiptFilter;
  });
}

function drawReceiptTable() {
  const wrap = el("#receiptTableWrap");
  if (!wrap) return;
  const rows = filteredReceiptRows();
  if (!rows.length) {
    wrap.innerHTML = emptyState({
      title: "这里还没有收据",
      text: "回到房源房间，选择一个房间开收据后会出现在这里。",
      actions: `<a class="btn btn-primary" href="#/properties">去开收据</a>`,
    });
    updateReceiptSelection();
    return;
  }
  wrap.innerHTML = `
    <div class="table-card">
      <div class="table-scroll">
        <table class="data-table">
          <thead><tr><th style="width:38px"></th><th>房间 / 租客</th><th>账单周期</th><th>单号</th><th>金额</th><th>已收 / 未收</th><th>状态</th><th style="text-align:right">操作</th></tr></thead>
          <tbody>
            ${rows.map((bill) => `
              <tr>
                <td><input class="table-check" type="checkbox" data-select-bill="${bill.id}" ${state.selectedBillIds.has(bill.id) ? "checked" : ""} ${bill.status !== "confirmed" ? "disabled" : ""} /></td>
                <td><div class="cell-title">${esc(bill.property_name)} · ${esc(bill.room_no)}</div><div class="cell-sub">${esc(bill.tenant_name || "未填写租客")}</div></td>
                <td><div class="cell-title">${esc(bill.start_date)}</div><div class="cell-sub">至 ${esc(bill.end_date)}</div></td>
                <td><div class="cell-title">${esc(bill.receipt_no || "—")}</div><div class="cell-sub">${esc(bill.issue_date)}</div></td>
                <td><div class="money">${money(bill.total_cents)}</div></td>
                <td><div class="money">${money(bill.paid_cents)}</div><div class="cell-sub">未收 ${money(bill.outstanding_cents)}</div></td>
                <td>${receiptStatusControl(bill)}</td>
                <td><div class="row-actions">
                  <a class="btn btn-ghost btn-small" href="#/bills/${bill.id}">查看</a>
                  ${bill.status === "confirmed" ? `<button class="btn btn-ghost btn-small" data-action="download-pdf" data-bill-id="${bill.id}">PDF</button>` : ""}
                  ${bill.status === "confirmed" && bill.outstanding_cents > 0 ? `<button class="btn btn-ghost btn-small" data-action="payment-bill" data-bill-id="${bill.id}">收款</button>` : ""}
                </div></td>
              </tr>`).join("")}
          </tbody>
        </table>
      </div>
    </div>`;
  updateReceiptSelection();
}

function updateReceiptSelection() {
  const count = state.selectedBillIds.size;
  if (el("#selectedCount")) el("#selectedCount").textContent = `已选 ${count} 张`;
  if (el("#exportPdfButton")) el("#exportPdfButton").disabled = count === 0;
  if (el("#exportZipButton")) el("#exportZipButton").disabled = count === 0;
}

async function renderLedger(token) {
  const data = await api(`/api/ledger?month=${encodeURIComponent(state.month)}`);
  if (token !== state.token) return;
  state.ledgerData = data;
  const summary = data.summary;
  const trendMax = Math.max(1, ...data.trend.flatMap((item) => [item.billed_cents, item.cost_cents]));
  const costNote = data.properties.filter((row) => row.cost_missing).map((row) => row.property_name);
  view.innerHTML = `
    <div class="view-content">
      <div class="page-lead">
        <div>
          <h2>${monthLabel(state.month)}经营台账</h2>
          <p>计费收入按已确认收据统计，成本按房源实际录入的水电和其他经营成本统计。</p>
        </div>
        <div class="page-actions">
          <a class="btn btn-ghost" href="/api/export/ledger.csv?month=${encodeURIComponent(state.month)}">导出台账</a>
          <button class="btn btn-secondary" data-action="cost-add">录入本月支出</button>
          <a class="btn btn-primary" href="#/properties">查看房源</a>
        </div>
      </div>
      <div class="ledger-kpis">
        <div class="ledger-kpi"><span>计费收入</span><strong>${money(summary.billed_cents)}</strong><small class="${summary.billed_delta_cents >= 0 ? "profit-positive" : "profit-negative"}">${trendChip(summary.billed_delta_cents, "环比")}</small></div>
        <div class="ledger-kpi"><span>经营支出</span><strong class="money--negative">${money(-summary.cost_cents)}</strong><small class="${summary.cost_delta_cents <= 0 ? "profit-positive" : "profit-negative"}">${trendChip(summary.cost_delta_cents, "环比")}</small></div>
        <div class="ledger-kpi"><span>经营毛利</span><strong class="${summary.profit_cents >= 0 ? "profit-positive" : "profit-negative"}">${money(summary.profit_cents)}</strong><small>${trendChip(summary.profit_delta_cents, "较上月")}</small></div>
        <div class="ledger-kpi"><span>毛利率</span><strong>${summary.billed_cents ? percentText(summary.profit_cents / summary.billed_cents) : "—"}</strong><small>实收 ${money(summary.received_cents)} · 未收 ${money(summary.outstanding_cents)}</small></div>
      </div>
      ${costNote.length ? `<div class="inline-note accent" style="margin-bottom:15px">成本数据还不完整：${costNote.map(esc).join("、")}。当前盈亏为暂计值。</div>` : ""}
      <section class="section-card ledger-breakdown-card">
        <div class="section-header">
          <div><h3 class="section-title">房源收支明细</h3><p class="section-sub">房租、水电和其他支出分项显示，支出以负数记录。</p></div>
          <span class="badge badge--draft">${monthLabel(state.month)}</span>
        </div>
        ${ledgerPropertyTable(data.properties)}
      </section>
      <div class="ledger-layout">
        <div style="display:grid;gap:16px;min-width:0">
          <section class="section-card chart-card">
            <div class="section-header">
              <div><h3 class="section-title">近六个月走势</h3><p class="section-sub">计费收入与实际录入成本。</p></div>
              <div class="chart-legend"><span class="legend-key">收入</span><span class="legend-key cost">成本</span></div>
            </div>
            <div class="bar-chart">
              ${data.trend.map((item) => `
                <div class="bar-month" title="${esc(item.month)}：收入 ${money(item.billed_cents)}，成本 ${money(item.cost_cents)}">
                  <div class="bar-set">
                    <div class="bar" style="height:${pctWidth(item.billed_cents, trendMax)}%"></div>
                    <div class="bar cost" style="height:${pctWidth(item.cost_cents, trendMax)}%"></div>
                  </div>
                  <div class="bar-label">${Number(item.month.slice(5))}月</div>
                </div>`).join("")}
            </div>
          </section>
        </div>
        <aside style="display:grid;gap:16px">
          <section class="section-card">
            <div class="section-header"><div><h3 class="section-title">本月支出明细</h3><p class="section-sub">总水电费和其他支出按房源录入，不分摊到房间。</p></div><button class="link-button" data-action="cost-add">录入</button></div>
            ${data.costs.length ? `<div class="cost-mini-list">${data.costs.map((cost) => `
              <div class="cost-mini-row">
                <div><strong>${esc(cost.property_name)} · ${esc(cost.name)}</strong><small>${esc(cost.note || cost.ledger_month)}</small></div>
                <div class="cost-mini-actions"><span class="money money--negative">${money(-cost.amount_cents)}</span><button data-action="cost-edit" data-cost-id="${cost.id}">编辑</button><button data-action="cost-delete" data-cost-id="${cost.id}">删除</button></div>
              </div>`).join("")}</div>` : `<div class="field-hint">还没有录入本月成本。录入后会自动参与盈亏计算。</div>`}
          </section>
          <section class="insight-card">
            <small>盈亏提示</small>
            <h3>${summary.profit_cents >= 0 ? "本月目前是盈利的" : "本月目前为亏损"}</h3>
            <p>经营毛利为计费收入减去已录入成本。未收金额仍单独显示，不会自动算作已到账。</p>
            <div class="insight-divider"></div>
            <div class="insight-row"><span>上月毛利</span><strong>${money(data.previous_summary.profit_cents)}</strong></div>
            <div class="insight-row"><span>本月变化</span><strong class="${summary.profit_delta_cents >= 0 ? "profit-positive" : "profit-negative"}">${money(summary.profit_delta_cents)}</strong></div>
            <div class="insight-row"><span>实收比例</span><strong>${summary.billed_cents ? percentText(summary.received_cents / summary.billed_cents) : "—"}</strong></div>
          </section>
        </aside>
      </div>
      <section class="section-card" style="margin-top:16px">
        <div class="section-header">
          <div><h3 class="section-title">房间水电变化</h3><p class="section-sub">用量和费用分开比较，避免单价变化混入用电量。</p></div>
          <select class="select" id="ledgerRoomFilter">
            <option value="all">全部房源</option>
            ${data.properties.map((row) => `<option value="${row.property_id}" ${String(state.ledgerRoomProperty) === String(row.property_id) ? "selected" : ""}>${esc(row.property_name)}</option>`).join("")}
          </select>
        </div>
        <div id="ledgerRoomTable">${ledgerRoomTable(data.rooms)}</div>
      </section>
    </div>`;
}

function ledgerPropertyTable(rows) {
  if (!rows.length) return `<div class="field-hint">还没有房源。</div>`;
  return `<div class="table-scroll"><table class="data-table ledger-property-table">
    <thead><tr><th>房源</th><th class="align-right">房租</th><th class="align-right">水电收入</th><th class="align-right">水电支出</th><th class="align-right">其他收入</th><th class="align-right">其他支出</th><th class="align-right">经营毛利</th><th class="align-right">较上月</th></tr></thead>
    <tbody>${rows.map((row) => {
      const utilityIncome = row.electric_income_cents + row.water_income_cents;
      const utilityCost = row.electric_cost_cents + row.water_cost_cents;
      const otherExpenses = row.costs.filter((cost) => cost.cost_type === "other");
      const otherExpenseNames = otherExpenses.map((cost) => cost.name).filter(Boolean).join("、");
      return `
      <tr>
        <td><a class="cell-title" href="#/properties/${row.property_id}">${esc(row.property_name)}</a><div class="cell-sub">${row.billed_count} 张收据 · 计费合计 ${money(row.billed_cents)}${row.cost_missing ? " · 成本未完整" : ""}</div></td>
        <td class="align-right"><div class="money">${money(row.rent_cents)}</div><div class="cell-sub">房租收入</div></td>
        <td class="align-right"><div class="money money--positive">${money(utilityIncome)}</div><div class="cell-sub">电 ${money(row.electric_income_cents)} · 水 ${money(row.water_income_cents)}</div></td>
        <td class="align-right"><div class="money money--negative">${money(-utilityCost)}</div><div class="cell-sub">电 ${money(-row.electric_cost_cents)} · 水 ${money(-row.water_cost_cents)}</div></td>
        <td class="align-right"><div class="money">${money(row.other_income_cents)}</div><div class="cell-sub">其他计费</div></td>
        <td class="align-right"><div class="money money--negative">${money(-row.other_cost_cents)}</div><div class="cell-sub">${esc(otherExpenseNames || "无其他支出")}</div></td>
        <td class="align-right"><div class="money ${row.profit_cents >= 0 ? "money--positive" : "money--negative"}">${money(row.profit_cents)}</div><div class="cell-sub">${row.margin === null ? "毛利率 —" : `毛利率 ${percentText(row.margin)}`} · ${row.profit_status === "profit" ? "盈利" : row.profit_status === "loss" ? "亏损" : "持平"}</div></td>
        <td class="align-right">${deltaMoney(row.delta_profit_cents, row.rate_profit_cents)}</td>
      </tr>`;
    }).join("")}</tbody>
  </table></div>`;
}

function ledgerRoomTable(rows) {
  const filtered = state.ledgerRoomProperty === "all" ? rows : rows.filter((row) => String(row.property_id) === String(state.ledgerRoomProperty));
  if (!filtered.length) return `<div class="field-hint">没有可比较的房间。</div>`;
  return `<div class="table-scroll"><table class="data-table">
    <thead><tr><th>房间</th><th class="align-right">用电 / 上月</th><th class="align-right">用电变化</th><th class="align-right">电费 / 变化</th><th class="align-right">用水 / 上月</th><th class="align-right">用水变化</th><th class="align-right">水费 / 变化</th><th class="align-right">账单合计</th></tr></thead>
    <tbody>${filtered.map((row) => `
      <tr>
        <td><div class="cell-title">${esc(row.property_name)} · ${esc(row.room_no)}</div><div class="cell-sub">${esc(row.tenant_name || "未填写租客")}${row.current_bill_id ? "" : " · 本月无收据"}</div></td>
        <td class="align-right"><div class="money">${numberText(row.electric_usage, " 度")}</div><div class="cell-sub">上期 ${numberText(row.previous_electric_usage, " 度")}</div></td>
        <td class="align-right">${deltaValue(row.electric_usage_delta, row.electric_usage_rate)}</td>
        <td class="align-right"><div class="money">${money(row.electric_cents)}</div><div class="cell-sub">${deltaValue(row.electric_delta_cents, row.electric_rate)}</div></td>
        <td class="align-right"><div class="money">${numberText(row.water_usage, " 吨")}</div><div class="cell-sub">上期 ${numberText(row.previous_water_usage, " 吨")}</div></td>
        <td class="align-right">${deltaValue(row.water_usage_delta, row.water_usage_rate)}</td>
        <td class="align-right"><div class="money">${money(row.water_cents)}</div><div class="cell-sub">${deltaValue(row.water_delta_cents, row.water_rate)}</div></td>
        <td class="align-right"><div class="money">${money(row.total_cents)}</div>${row.current_bill_id ? `<a class="cell-sub" href="#/bills/${row.current_bill_id}">查看收据</a>` : ""}</td>
      </tr>`).join("")}</tbody>
  </table></div>`;
}

async function renderHelp(token) {
  if (token !== state.token) return;
  view.innerHTML = `
    <div class="view-content help-page">
      <section class="help-hero">
        <div>
          <span class="context-kicker">从第一次使用开始</span>
          <h2>五步完成每月收租</h2>
          <p>所有数据只保存在本机。建议先点“编辑房间”设置房租、水电单价和自动抄表增量，再开始每月开单。</p>
        </div>
        <div class="help-hero-actions">
          <a class="btn btn-primary" href="#/properties">进入房源房间</a>
          <a class="btn btn-secondary" href="#/ledger">查看总台账</a>
        </div>
      </section>

      <section class="help-steps">
        <article><span>01</span><strong>建立房源</strong><p>添加小区、楼栋或出租地址，再在房源下添加房间。</p></article>
        <article><span>02</span><strong>设置房间</strong><p>填写房租、水电单价、抄表日和每月自动增加量。</p></article>
        <article><span>03</span><strong>开本期收据</strong><p>选择房间，填写本月水电读数；自动模式会预填并锁定读数。</p></article>
        <article><span>04</span><strong>确认并继续</strong><p>点击确认或按 Enter，自动进入同房源下一间待处理房间。</p></article>
        <article><span>05</span><strong>登记收款与导出</strong><p>查看收款状态，导出单个 PDF，或勾选多张合并汇总。</p></article>
      </section>

      <div class="help-grid">
        <article class="help-card">
          <span class="help-card-icon">房</span>
          <h3>房间和自动抄表</h3>
          <p>在“编辑房间”中可分别启用电表、水表自动填写，并设置每月增量。</p>
          <div class="help-example">上期水表 402，月增量 2 → 新单自动填写 404</div>
          <p>自动值默认锁定；点击读数旁的“解锁”后才可修改。手动修改后的读数会成为下个月自动增加的基准。</p>
        </article>

        <article class="help-card">
          <span class="help-card-icon">单</span>
          <h3>收据填写与快捷键</h3>
          <p>只需填写本月电表、水表读数，电费、水费、合计和大写金额会自动计算。</p>
          <p>水电单价默认锁定并跳过 Tab 顺序；需要调价时点击“解锁单价”。</p>
          <div class="help-shortcuts"><kbd>Enter</kbd><span>确认当前收据并进入下一间</span></div>
        </article>

        <article class="help-card">
          <span class="help-card-icon">收</span>
          <h3>收款和 PDF</h3>
          <p>确认后默认标记已收，也可以选择未收。部分收款、多次收款和逾期状态都会自动汇总。</p>
          <p>合并 PDF 会固定按房源、房间号升序排列，不受勾选顺序影响。</p>
        </article>

        <article class="help-card">
          <span class="help-card-icon">账</span>
          <h3>总台账与支出</h3>
          <p>在总台账点击“录入本月支出”，按房源一次填写电费总成本、水费总成本和多笔其他支出。</p>
          <div class="help-example">修水管 50、清洁费 20 → 其他支出 -¥70.00</div>
          <p>房源收支会拆分显示房租、水电收支、其他收入、其他支出和经营毛利。</p>
        </article>

        <article class="help-card">
          <span class="help-card-icon">备</span>
          <h3>数据安全与备份</h3>
          <p>数据库保存在本机 <code>data/rental.db</code>，不会主动上传网络。</p>
          <p>建议每次批量确认收据后，在“系统设置”下载完整备份。恢复备份会替换当前账本。</p>
        </article>

        <article class="help-card help-card--accent">
          <span class="help-card-icon">?</span>
          <h3>遇到问题时</h3>
          <p>先检查房间状态是否为“出租中”，账单周期是否重叠，以及水电本期读数是否小于上期读数。</p>
          <p>需要复核上一间时，点击页面顶部“返回房间列表”，不会影响已经确认的收据。</p>
        </article>
      </div>
    </div>`;
}

async function renderSettings(token) {
  const [settings, propertyData] = await Promise.all([
    api("/api/settings"),
    api(`/api/properties?month=${encodeURIComponent(state.month)}`),
  ]);
  if (token !== state.token) return;
  state.bootstrap.settings = settings;
  const isEmpty = propertyData.properties.length === 0;
  view.innerHTML = `
    <div class="view-content">
      <div class="settings-grid">
        <section class="section-card settings-card">
          <h3>收据抬头</h3>
          <p>这些内容会出现在每一张导出的 PDF 收据上。</p>
          <div class="form-grid">
            <div class="field"><label>收据标题</label><input class="input" id="settingTitle" value="${esc(settings.receipt_title || "租金收据")}" /></div>
            <div class="field"><label>收款人</label><input class="input" id="settingPayee" value="${esc(settings.payee_name || "")}" /></div>
            <div class="field"><label>开票人</label><input class="input" id="settingIssuer" value="${esc(settings.issuer_name || "")}" /></div>
            <div class="field"><label>单号前缀</label><input class="input" id="settingPrefix" placeholder="可选，如 A" value="${esc(settings.receipt_prefix || "")}" /></div>
            <div class="field"><label>下一个单号</label><input class="input" id="settingNextNo" type="number" min="1" step="1" value="${esc(settings.next_receipt_no || "1")}" /></div>
            <div class="field"><label>逾期天数</label><input class="input" id="settingOverdue" type="number" min="0" step="1" value="${esc(settings.overdue_days || "7")}" /></div>
            <div class="field field--full"><label>收据备注</label><textarea class="textarea" id="settingNote">${esc(settings.receipt_note || "")}</textarea></div>
          </div>
          <div class="toggle-row">
            <div><strong>在收据上显示租客姓名</strong><span>默认关闭，保护租客信息。</span></div>
            <label class="toggle"><input id="settingShowTenant" type="checkbox" ${settings.show_tenant_on_receipt === "1" ? "checked" : ""} /><span></span></label>
          </div>
          <div class="page-actions" style="margin-top:18px"><button class="btn btn-primary" data-action="save-settings">保存设置</button></div>
        </section>

        <div style="display:grid;gap:16px">
          <section class="section-card settings-card">
            <h3>数据备份</h3>
            <p>把房源、收据、收款和台账一起保存成一个备份文件。</p>
            <div class="backup-actions">
              <a class="btn btn-secondary" href="/api/settings/backup">下载完整备份</a>
              <label class="btn btn-ghost file-button">从备份恢复<input type="file" id="restoreFile" accept=".zip,application/zip" /></label>
            </div>
            <div class="inline-note" style="margin-top:14px">数据只保存在本机的 <strong>data/rental.db</strong> 中。恢复备份会替换当前账本，请先下载一份现有备份。</div>
          </section>
          <section class="section-card settings-card">
            <h3>示例数据</h3>
            <p>${isEmpty ? "当前账本为空，可以载入截图中两组房源的结构，体验完整开单流程。" : "当前已有房源数据，不会重复载入示例。"}</p>
            <button class="btn ${isEmpty ? "btn-primary" : "btn-secondary"}" data-action="seed-demo" ${isEmpty ? "" : "disabled"}>载入示例数据</button>
          </section>
          <section class="section-card settings-card">
            <h3>关于租舍</h3>
            <p>第一版 · 本机离线运行。数据不会主动上传到网络。</p>
            <div class="cost-mini-list">
              <div class="cost-mini-row"><span>数据文件</span><strong>data/rental.db</strong></div>
              <div class="cost-mini-row"><span>访问地址</span><strong>127.0.0.1:8848</strong></div>
              <div class="cost-mini-row"><span>当前版本</span><strong>v1.0</strong></div>
            </div>
          </section>
        </div>
      </div>
    </div>`;
  el("#restoreFile").addEventListener("change", async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    const confirmed = await confirmDialog({
      title: "恢复备份",
      message: "恢复会替换当前所有房源、收据、收款和成本数据。建议先下载现有备份。确定继续吗？",
      confirmLabel: "确认恢复",
      danger: true,
    });
    if (!confirmed) {
      event.target.value = "";
      return;
    }
    try {
      toast("正在恢复备份…");
      const response = await fetch("/api/settings/restore", {
        method: "POST",
        headers: { "Content-Type": "application/zip" },
        body: file,
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.error || "恢复失败");
      }
      state.month = null;
      await reloadBootstrap();
      toast("备份已恢复");
      renderRoute();
    } catch (error) {
      toast(error.message, "error");
      event.target.value = "";
    }
  });
}

function costRecordsFor(propertyId, month) {
  return (state.ledgerData?.costs || []).filter(
    (cost) =>
      String(cost.property_id) === String(propertyId) &&
      cost.ledger_month === month,
  );
}

function otherCostRowHTML(cost = null) {
  return `
    <div class="other-cost-row" data-cost-id="${cost?.id || ""}">
      <input class="input" data-cost-name placeholder="支出名称，如修水管" value="${esc(cost?.name || "")}" />
      <div class="input-affix"><span class="prefix">-¥</span><input class="input has-suffix" data-cost-amount type="number" min="0" step="0.01" placeholder="0.00" value="${cost ? (cost.amount_cents / 100).toFixed(2) : ""}" /></div>
      <input class="input" data-cost-note placeholder="备注，可选" value="${esc(cost?.note || "")}" />
      <button class="fee-remove" type="button" data-remove-other-cost aria-label="删除这笔支出">×</button>
    </div>`;
}

function costEditorFieldsHTML(propertyId, month) {
  const costs = costRecordsFor(propertyId, month);
  const electricity = costs.find((cost) => cost.cost_type === "electricity");
  const water = costs.find((cost) => cost.cost_type === "water");
  const others = costs.filter((cost) => cost.cost_type === "other");
  return `
    <div class="cost-entry-intro">
      <div><span>本月支出</span><strong>${monthLabel(month)}</strong></div>
      <p>这里填写房东实际支付的总成本；支出在台账中显示为负数。</p>
    </div>
    <div class="form-grid cost-utility-grid">
      <div class="field">
        <label>电费总成本</label>
        <div class="input-affix"><span class="prefix">-¥</span><input class="input has-suffix" id="costElectricityAmount" data-cost-amount type="number" min="0" step="0.01" placeholder="未录入" value="${electricity ? (electricity.amount_cents / 100).toFixed(2) : ""}" /><span class="suffix">元</span></div>
      </div>
      <div class="field">
        <label>水费总成本</label>
        <div class="input-affix"><span class="prefix">-¥</span><input class="input has-suffix" id="costWaterAmount" data-cost-amount type="number" min="0" step="0.01" placeholder="未录入" value="${water ? (water.amount_cents / 100).toFixed(2) : ""}" /><span class="suffix">元</span></div>
      </div>
    </div>
    <section class="cost-other-section">
      <div class="section-label">
        <strong>其他支出</strong>
        <button class="link-button" type="button" data-add-other-cost>+ 添加一笔</button>
      </div>
      <div class="other-cost-list" id="otherCostList">
        ${others.length ? others.map((cost) => otherCostRowHTML(cost)).join("") : otherCostRowHTML()}
      </div>
    </section>
    <div class="cost-entry-total">
      <span>本月支出合计</span>
      <strong id="costEntryTotal">${money(-costs.reduce((total, cost) => total + cost.amount_cents, 0))}</strong>
    </div>`;
}

function updateCostEntryTotal(modal) {
  const total = els("[data-cost-amount]", modal).reduce(
    (sum, input) => sum + Math.max(0, toCents(input.value)),
    0,
  );
  const target = el("#costEntryTotal", modal);
  if (target) target.textContent = money(-total);
}

function openCostModal(cost = null) {
  if (!state.ledgerData?.properties?.length) {
    toast("请先创建房源", "error");
    return;
  }
  const propertyId = cost?.property_id || state.ledgerData.properties[0].property_id;
  const month = cost?.ledger_month || state.month;
  let pendingDeletes = [];
  const modal = openModal({
    title: "录入本月支出",
    subtitle: "按房源一次录入总水电费和其他支出，不会显示在租客收据上。",
    size: "modal-wide",
    body: `
      <div class="form-grid">
        <div class="field field--full"><label>房源</label><select class="select" id="costProperty">${state.ledgerData.properties.map((property) => `<option value="${property.property_id}" ${String(property.property_id) === String(propertyId) ? "selected" : ""}>${esc(property.property_name)}</option>`).join("")}</select></div>
        <div class="field"><label>归属账期</label><input class="input" id="costMonth" type="month" value="${esc(cost?.ledger_month || state.month)}" /></div>
      </div>
      <div id="costEditorFields">${costEditorFieldsHTML(propertyId, month)}</div>`,
    footer: `<button class="btn btn-ghost" data-cancel-cost>取消</button><button class="btn btn-primary" data-save-cost>保存本月支出</button>`,
  });

  const refreshFields = () => {
    pendingDeletes = [];
    el("#costEditorFields", modal.modal).innerHTML = costEditorFieldsHTML(
      el("#costProperty", modal.modal).value,
      el("#costMonth", modal.modal).value,
    );
  };
  el("#costProperty", modal.modal).addEventListener("change", refreshFields);
  el("#costMonth", modal.modal).addEventListener("change", refreshFields);
  modal.modal.addEventListener("click", (event) => {
    if (event.target.closest("[data-add-other-cost]")) {
      el("#otherCostList", modal.modal).insertAdjacentHTML("beforeend", otherCostRowHTML());
      updateCostEntryTotal(modal.modal);
    }
    const removeButton = event.target.closest("[data-remove-other-cost]");
    if (removeButton) {
      const row = removeButton.closest(".other-cost-row");
      if (row.dataset.costId) pendingDeletes.push(Number(row.dataset.costId));
      row.remove();
      updateCostEntryTotal(modal.modal);
    }
  });
  modal.modal.addEventListener("input", () => updateCostEntryTotal(modal.modal));
  el("[data-cancel-cost]", modal.modal).addEventListener("click", modal.close);
  el("[data-save-cost]", modal.modal).addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      const selectedProperty = el("#costProperty", modal.modal).value;
      const selectedMonth = el("#costMonth", modal.modal).value;
      const existingCosts = costRecordsFor(selectedProperty, selectedMonth);
      const utilities = [
        ["electricity", "#costElectricityAmount"],
        ["water", "#costWaterAmount"],
      ];
      for (const [costType, selector] of utilities) {
        const input = el(selector, modal.modal);
        if (!input.value.trim()) continue;
        const existing = existingCosts.find((item) => item.cost_type === costType);
        await api("/api/costs", {
          method: "POST",
          body: {
            id: existing?.id,
            property_id: selectedProperty,
            ledger_month: selectedMonth,
            cost_type: costType,
            name: existing?.name || "",
            amount: input.value,
            note: existing?.note || "",
          },
        });
      }
      for (const row of els(".other-cost-row", modal.modal)) {
        const name = el("[data-cost-name]", row).value.trim();
        const amount = el("[data-cost-amount]", row).value.trim();
        const note = el("[data-cost-note]", row).value.trim();
        if (!name && !amount && !note) continue;
        if (!name) throw new Error("请填写其他支出名称");
        if (!amount) throw new Error(`请填写“${name}”的支出金额`);
        await api("/api/costs", {
          method: "POST",
          body: {
            id: row.dataset.costId || undefined,
            property_id: selectedProperty,
            ledger_month: selectedMonth,
            cost_type: "other",
            name,
            amount,
            note,
          },
        });
      }
      for (const costId of pendingDeletes) {
        await api(`/api/costs/${costId}`, { method: "DELETE" });
      }
      modal.close();
      toast("本月支出已保存");
      renderRoute();
    } catch (error) {
      toast(error.message, "error");
      button.disabled = false;
    }
  });
}

async function seedDemoData() {
  try {
    await api("/api/demo/seed", { method: "POST", body: {} });
    state.month = null;
    await reloadBootstrap();
    toast("示例数据已载入");
    go("/dashboard", { replace: true });
  } catch (error) {
    toast(error.message, "error");
  }
}

async function handleViewClick(event) {
  const roomLink = event.target.closest('a[href^="#/rooms/"]');
  if (roomLink && state.currentPropertyDetail?.property?.id) {
    sessionStorage.setItem(
      `property-scroll-${state.currentPropertyDetail.property.id}`,
      String(window.scrollY),
    );
  }
  const actionButton = event.target.closest("[data-action]");
  if (!actionButton) return;
  const action = actionButton.dataset.action;
  if (
    state.editor &&
    actionButton.closest(".editor-card") &&
    !["unlock-reading", "unlock-rates"].includes(action)
  ) {
    state.editor.version += 1;
    state.editor.dirty = true;
  }
  try {
    switch (action) {
      case "refresh-route":
        renderRoute();
        break;
      case "go-properties":
        go("/properties");
        break;
      case "add-property":
        openPropertyModal();
        break;
      case "edit-property":
        openPropertyModal(state.currentPropertyDetail?.property || null);
        break;
      case "add-room":
        openRoomModal(null, Number(actionButton.dataset.propertyId || state.currentPropertyDetail?.property?.id));
        break;
      case "edit-room":
        openRoomModal(state.currentRoomDetail?.room || null);
        break;
      case "first-receipt":
        openDateModal();
        break;
      case "custom-date":
        openDateModal({ custom: true });
        break;
      case "new-receipt":
        await createNextReceipt();
        break;
      case "add-other":
        addOtherFee();
        break;
      case "remove-other":
        removeOtherFee(Number(actionButton.dataset.slot));
        break;
      case "save-bill":
        actionButton.disabled = true;
        try {
          await saveBillDraft();
          toast("草稿已保存");
        } finally {
          actionButton.disabled = false;
        }
        break;
      case "confirm-bill":
        await confirmCurrentBill(actionButton);
        break;
      case "set-payment-mode": {
        if (!state.editor) break;
        const mode = actionButton.dataset.mode === "unpaid" ? "unpaid" : "paid";
        state.editor.paymentMode = mode;
        els(".payment-mode-button").forEach((button) => {
          button.classList.toggle("active", button.dataset.mode === mode);
        });
        const hint = el("#paymentModeHint");
        if (hint) {
          hint.textContent =
            mode === "paid"
              ? "默认已收，确认后会生成一笔已收记录。"
              : "已选择未收，确认后这张收据保持未收。";
        }
        break;
      }
      case "unlock-reading": {
        if (!state.editor) break;
        const field = actionButton.dataset.field === "water" ? "water" : "electric";
        const saved = await api(`/api/bills/${state.editor.bill.id}`, {
          method: "PUT",
          body: { [`${field}_auto_locked`]: false },
        });
        state.editor.bill = saved;
        const input = el(`[data-bill-field="current_${field}"]`);
        if (input) {
          input.readOnly = false;
          input.tabIndex = 0;
          input.focus();
          input.select();
        }
        actionButton.remove();
        toast(`${field === "water" ? "水表" : "电表"}读数已解锁，本次可手动修改`);
        break;
      }
      case "unlock-rates": {
        const rateInputs = [
          el('[data-bill-field="electric_rate"]'),
          el('[data-bill-field="water_rate"]'),
        ].filter(Boolean);
        const locked = rateInputs.every((input) => input.readOnly);
        rateInputs.forEach((input) => {
          input.readOnly = !locked;
          input.tabIndex = locked ? 0 : -1;
        });
        actionButton.textContent = locked ? "锁定单价" : "解锁单价";
        if (locked) rateInputs[0]?.focus();
        break;
      }
      case "toggle-payment-status": {
        const billId = Number(actionButton.dataset.billId || state.currentBill?.id);
        if (!billId) break;
        const known =
          state.receiptRows.find((item) => item.id === billId) ||
          (state.currentBill?.id === billId ? state.currentBill : null);
        const target =
          known?.payment_status === "paid" || known?.payment_status === "partial"
            ? "unpaid"
            : "paid";
        await api(`/api/bills/${billId}/payment-status`, {
          method: "POST",
          body: { status: target },
        });
        toast(target === "paid" ? "已设为已收" : "已设为未收");
        await reloadBootstrap();
        renderRoute();
        break;
      }
      case "download-pdf": {
        const billId = actionButton.dataset.billId || state.currentBill?.id || state.editor?.bill?.id;
        if (billId) window.open(`/api/bills/${billId}/pdf`, "_blank", "noopener");
        break;
      }
      case "payment-add":
        openPaymentModal(state.currentBill);
        break;
      case "payment-bill": {
        const bill = await api(`/api/bills/${actionButton.dataset.billId}`);
        openPaymentModal(bill);
        break;
      }
      case "payment-delete": {
        const confirmed = await confirmDialog({
          title: "删除收款记录",
          message: "删除后这张收据会重新变成未收或部分收款，确定删除吗？",
          confirmLabel: "删除记录",
          danger: true,
        });
        if (confirmed) {
          await api(`/api/payments/${actionButton.dataset.paymentId}`, { method: "DELETE" });
          toast("收款记录已删除");
          renderRoute();
        }
        break;
      }
      case "void-bill":
        openVoidModal(state.currentBill);
        break;
      case "filter-receipts":
        state.receiptFilter = actionButton.dataset.filter;
        els("#receiptTabs button").forEach((button) => button.classList.toggle("active", button === actionButton));
        drawReceiptTable();
        break;
      case "select-all-bills": {
        const rows = filteredReceiptRows().filter((bill) => bill.status === "confirmed");
        const allSelected = rows.length > 0 && rows.every((bill) => state.selectedBillIds.has(bill.id));
        rows.forEach((bill) => {
          if (allSelected) state.selectedBillIds.delete(bill.id);
          else state.selectedBillIds.add(bill.id);
        });
        drawReceiptTable();
        break;
      }
      case "export-selected-zip": {
        const ids = [...state.selectedBillIds];
        if (ids.length) window.location.href = `/api/export/bills.zip?ids=${ids.join(",")}`;
        break;
      }
      case "export-selected-pdf": {
        const ids = [...state.selectedBillIds];
        if (ids.length) window.open(`/api/export/bills.pdf?ids=${ids.join(",")}`, "_blank", "noopener");
        break;
      }
      case "cost-add":
        openCostModal();
        break;
      case "cost-edit": {
        const cost = state.ledgerData?.costs?.find((item) => item.id === Number(actionButton.dataset.costId));
        openCostModal(cost || null);
        break;
      }
      case "cost-delete": {
        const confirmed = await confirmDialog({
          title: "删除成本记录",
          message: "删除后本月盈亏会立刻重新计算，确定删除吗？",
          confirmLabel: "删除",
          danger: true,
        });
        if (confirmed) {
          await api(`/api/costs/${actionButton.dataset.costId}`, { method: "DELETE" });
          toast("成本记录已删除");
          renderRoute();
        }
        break;
      }
      case "seed-demo":
        await seedDemoData();
        break;
      case "save-settings": {
        actionButton.disabled = true;
        try {
          const settings = await api("/api/settings", {
            method: "PUT",
            body: {
              receipt_title: el("#settingTitle").value.trim(),
              payee_name: el("#settingPayee").value.trim(),
              issuer_name: el("#settingIssuer").value.trim(),
              receipt_prefix: el("#settingPrefix").value.trim(),
              next_receipt_no: el("#settingNextNo").value,
              overdue_days: el("#settingOverdue").value,
              receipt_note: el("#settingNote").value.trim(),
              show_tenant_on_receipt: el("#settingShowTenant").checked ? "1" : "0",
            },
          });
          state.bootstrap.settings = settings;
          toast("设置已保存");
        } finally {
          actionButton.disabled = false;
        }
        break;
      }
      default:
        break;
    }
  } catch (error) {
    toast(error.message, "error");
  }
}

function handleViewInput(event) {
  if (!state.editor) return;
  const target = event.target;
  if (target.matches("[data-bill-field], [data-fee-field]")) {
    queueEditorSave();
    updateEditorPreview();
  }
}

function handleViewChange(event) {
  const target = event.target;
  if (state.editor && target.matches("[data-bill-field], [data-fee-field]")) {
    queueEditorSave();
    updateEditorPreview();
    return;
  }
  if (target.matches("[data-select-bill]")) {
    const id = Number(target.dataset.selectBill);
    if (target.checked) state.selectedBillIds.add(id);
    else state.selectedBillIds.delete(id);
    updateReceiptSelection();
    return;
  }
  if (target.id === "receiptPropertyFilter") {
    state.receiptProperty = target.value;
    drawReceiptTable();
    return;
  }
  if (target.id === "ledgerRoomFilter") {
    state.ledgerRoomProperty = target.value;
    const table = el("#ledgerRoomTable");
    if (table) table.innerHTML = ledgerRoomTable(state.ledgerData.rooms);
  }
}

init();
