"use strict";

/* ==========================================================================
   Config & small utilities
   ========================================================================== */
const API_BASE = "/api";

const state = {
  categories: [],
  expenses: [],
  summary: null,
  editingExpenseId: null,
  editingCategoryId: null,
  filters: { category_id: "", start_date: "", end_date: "", search: "", sort: "date_desc" },
};

let categoryChart = null;
let trendChart = null;
let confirmCallback = null;

const fmtCurrency = (n) =>
  new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 }).format(n || 0);

const fmtDate = (isoDate) => {
  const d = new Date(isoDate + "T00:00:00");
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
};

const fmtDateShort = (isoDate) => {
  const d = new Date(isoDate + "T00:00:00");
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
};

function todayISO() {
  const d = new Date();
  return d.toISOString().split("T")[0];
}

function showToast(message, type = "") {
  const toast = document.getElementById("toast");
  toast.textContent = message;
  toast.className = "toast show" + (type ? " " + type : "");
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => toast.classList.remove("show"), 3000);
}

function askConfirm(message, onConfirm) {
  document.getElementById("confirmMessage").textContent = message;
  document.getElementById("confirmModal").classList.remove("hidden");
  confirmCallback = onConfirm;
}

/** Re-runs Lucide's icon replacement over any newly injected [data-lucide] elements. */
function refreshIcons() {
  if (window.lucide) lucide.createIcons();
}

/** #RRGGBB -> "r, g, b" so chart fills can use rgba() with the theme's accent color. */
function hexToRgbTriplet(hex) {
  const clean = hex.replace("#", "");
  const r = parseInt(clean.substring(0, 2), 16);
  const g = parseInt(clean.substring(2, 4), 16);
  const b = parseInt(clean.substring(4, 6), 16);
  return `${r}, ${g}, ${b}`;
}

/* ==========================================================================
   API layer
   ========================================================================== */
const api = {
  async request(path, options = {}) {
    const res = await fetch(API_BASE + path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    let data = null;
    try { data = await res.json(); } catch (_) { /* no body */ }
    if (!res.ok) {
      const message = (data && data.error) || `Request failed (${res.status})`;
      throw new Error(message);
    }
    return data;
  },
  get(path) { return this.request(path); },
  post(path, body) { return this.request(path, { method: "POST", body: JSON.stringify(body) }); },
  put(path, body) { return this.request(path, { method: "PUT", body: JSON.stringify(body) }); },
  del(path) { return this.request(path, { method: "DELETE" }); },
};

/* ==========================================================================
   Navigation
   ========================================================================== */
function switchView(viewName) {
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  document.getElementById(`view-${viewName}`).classList.add("active");

  document.querySelectorAll(".nav-item, .mobile-nav-item").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.view === viewName);
  });

  if (viewName === "expenses") loadExpenses();
  if (viewName === "add" && state.editingExpenseId === null) resetExpenseForm();
}

function setupNavigation() {
  document.querySelectorAll("[data-view]").forEach((btn) => {
    btn.addEventListener("click", () => switchView(btn.dataset.view));
  });
}

/* ==========================================================================
   Theme
   ========================================================================== */
function setupTheme() {
  const saved = localStorage.getItem("theme") || "light";
  applyTheme(saved);
  document.getElementById("themeToggle").addEventListener("click", () => {
    const current = document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
    applyTheme(current === "dark" ? "light" : "dark");
  });
}

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem("theme", theme);
  document.getElementById("themeIcon").setAttribute("data-lucide", theme === "dark" ? "sun" : "moon");
  document.getElementById("themeLabel").textContent = theme === "dark" ? "Light mode" : "Dark mode";
  refreshIcons();
  if (categoryChart) refreshDashboard();
}

/* ==========================================================================
   Categories
   ========================================================================== */
async function loadCategories() {
  state.categories = await api.get("/categories");
  populateCategorySelects();
  renderCategoryGrid();
  refreshIcons();
}

function populateCategorySelects() {
  const filterSelect = document.getElementById("filterCategory");
  const formSelect = document.getElementById("categorySelect");

  const filterCurrent = filterSelect.value;
  filterSelect.innerHTML = '<option value="">All Categories</option>' +
    state.categories.map((c) => `<option value="${c.id}">${c.icon} ${c.name}</option>`).join("");
  filterSelect.value = filterCurrent;

  formSelect.innerHTML = state.categories.map((c) => `<option value="${c.id}">${c.icon} ${c.name}</option>`).join("");
}

function renderCategoryGrid() {
  const grid = document.getElementById("categoryGrid");
  if (state.categories.length === 0) {
    grid.innerHTML = `<div class="empty-state"><i data-lucide="tags"></i><p>No categories yet. Add your first one.</p></div>`;
    refreshIcons();
    return;
  }

  grid.innerHTML = state.categories.map((c) => {
    const budgetPct = c.monthly_budget > 0 ? Math.min(100, Math.round((c.total_spent / c.monthly_budget) * 100)) : null;
    return `
    <div class="category-card">
      <div class="category-card-top">
        <div class="category-card-icon" style="background:${c.color}22;color:${c.color}">${c.icon}</div>
        <div class="category-card-name">${escapeHtml(c.name)}</div>
        <div class="category-card-actions">
          <button class="icon-btn" data-edit-category="${c.id}" title="Edit"><i data-lucide="pencil"></i></button>
          <button class="icon-btn danger" data-delete-category="${c.id}" title="Delete"><i data-lucide="trash-2"></i></button>
        </div>
      </div>
      <div class="category-stat-row"><span>Total spent</span><span>${fmtCurrency(c.total_spent)}</span></div>
      <div class="category-stat-row"><span>Transactions</span><span>${c.expense_count}</span></div>
      ${c.monthly_budget > 0 ? `
        <div class="category-stat-row"><span>Monthly budget</span><span>${fmtCurrency(c.monthly_budget)}</span></div>
        <div class="budget-bar-bg"><div class="budget-bar-fill" style="width:${budgetPct}%;background:${budgetPct >= 100 ? "var(--danger)" : c.color}"></div></div>
      ` : ""}
    </div>`;
  }).join("");

  grid.querySelectorAll("[data-edit-category]").forEach((btn) =>
    btn.addEventListener("click", () => openCategoryForm(Number(btn.dataset.editCategory))));
  grid.querySelectorAll("[data-delete-category]").forEach((btn) =>
    btn.addEventListener("click", () => deleteCategory(Number(btn.dataset.deleteCategory))));
}

function openCategoryForm(categoryId = null) {
  const card = document.getElementById("categoryFormCard");
  card.classList.remove("hidden");
  state.editingCategoryId = categoryId;

  if (categoryId) {
    const cat = state.categories.find((c) => c.id === categoryId);
    document.getElementById("categoryFormTitle").textContent = "Edit category";
    document.getElementById("categoryId").value = cat.id;
    document.getElementById("categoryNameInput").value = cat.name;
    document.getElementById("categoryIconInput").value = cat.icon;
    document.getElementById("categoryColorInput").value = cat.color;
    document.getElementById("categoryBudgetInput").value = cat.monthly_budget || "";
  } else {
    document.getElementById("categoryFormTitle").textContent = "New category";
    document.getElementById("categoryForm").reset();
    document.getElementById("categoryId").value = "";
    document.getElementById("categoryColorInput").value = "#9C7A2E";
  }
  card.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function deleteCategory(categoryId) {
  askConfirm("Delete this category? This only works if no expenses use it.", async () => {
    try {
      await api.del(`/categories/${categoryId}`);
      showToast("Category deleted", "success");
      await loadCategories();
    } catch (e) {
      showToast(e.message, "error");
    }
  });
}

function setupCategoryForm() {
  document.getElementById("addCategoryBtn").addEventListener("click", () => openCategoryForm());
  document.getElementById("cancelCategoryBtn").addEventListener("click", () => {
    document.getElementById("categoryFormCard").classList.add("hidden");
  });

  document.getElementById("categoryForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const payload = {
      name: document.getElementById("categoryNameInput").value.trim(),
      icon: document.getElementById("categoryIconInput").value.trim() || "📦",
      color: document.getElementById("categoryColorInput").value,
      monthly_budget: parseFloat(document.getElementById("categoryBudgetInput").value) || 0,
    };
    try {
      if (state.editingCategoryId) {
        await api.put(`/categories/${state.editingCategoryId}`, payload);
        showToast("Category updated", "success");
      } else {
        await api.post("/categories", payload);
        showToast("Category created", "success");
      }
      document.getElementById("categoryFormCard").classList.add("hidden");
      await loadCategories();
      await refreshDashboard();
    } catch (e) {
      showToast(e.message, "error");
    }
  });
}

/* ==========================================================================
   Expenses — list rendering
   ========================================================================== */
function expenseRowHTML(e) {
  return `
    <div class="expense-row" data-id="${e.id}">
      <div class="expense-icon" style="background:${e.category_color}22;color:${e.category_color}">${e.category_icon}</div>
      <div class="expense-info">
        <div class="expense-desc">${escapeHtml(e.description) || e.category_name}</div>
        <div class="expense-meta">${e.category_name} · ${fmtDate(e.date)} · ${e.payment_method}</div>
      </div>
      <div class="expense-amount">${fmtCurrency(e.amount)}</div>
      <div class="expense-actions">
        <button class="icon-btn" data-edit="${e.id}" title="Edit"><i data-lucide="pencil"></i></button>
        <button class="icon-btn danger" data-delete="${e.id}" title="Delete"><i data-lucide="trash-2"></i></button>
      </div>
    </div>`;
}

function attachRowHandlers(container) {
  container.querySelectorAll("[data-edit]").forEach((btn) =>
    btn.addEventListener("click", () => editExpense(Number(btn.dataset.edit))));
  container.querySelectorAll("[data-delete]").forEach((btn) =>
    btn.addEventListener("click", () => deleteExpense(Number(btn.dataset.delete))));
}

async function loadExpenses() {
  const params = new URLSearchParams();
  Object.entries(state.filters).forEach(([k, v]) => { if (v) params.set(k, v); });

  const expenses = await api.get(`/expenses?${params.toString()}`);
  state.expenses = expenses;

  const list = document.getElementById("fullExpenseList");
  const emptyState = document.getElementById("emptyState");
  document.getElementById("expenseCountSub").textContent =
    `${expenses.length} expense${expenses.length === 1 ? "" : "s"}`;

  if (expenses.length === 0) {
    list.innerHTML = "";
    emptyState.classList.remove("hidden");
  } else {
    emptyState.classList.add("hidden");
    list.innerHTML = expenses.map(expenseRowHTML).join("");
    attachRowHandlers(list);
    refreshIcons();
  }
}

function setupFilters() {
  const debounced = debounce(() => { state.filters.search = document.getElementById("searchInput").value; loadExpenses(); }, 300);
  document.getElementById("searchInput").addEventListener("input", debounced);

  document.getElementById("filterCategory").addEventListener("change", (e) => {
    state.filters.category_id = e.target.value; loadExpenses();
  });
  document.getElementById("filterStart").addEventListener("change", (e) => {
    state.filters.start_date = e.target.value; loadExpenses();
  });
  document.getElementById("filterEnd").addEventListener("change", (e) => {
    state.filters.end_date = e.target.value; loadExpenses();
  });
  document.getElementById("sortSelect").addEventListener("change", (e) => {
    state.filters.sort = e.target.value; loadExpenses();
  });
  document.getElementById("clearFiltersBtn").addEventListener("click", () => {
    state.filters = { category_id: "", start_date: "", end_date: "", search: "", sort: "date_desc" };
    document.getElementById("searchInput").value = "";
    document.getElementById("filterCategory").value = "";
    document.getElementById("filterStart").value = "";
    document.getElementById("filterEnd").value = "";
    document.getElementById("sortSelect").value = "date_desc";
    loadExpenses();
  });
}

function debounce(fn, delay) {
  let timer;
  return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), delay); };
}

/* ==========================================================================
   Expense form (add / edit)
   ========================================================================== */
function resetExpenseForm() {
  state.editingExpenseId = null;
  document.getElementById("expenseForm").reset();
  document.getElementById("expenseId").value = "";
  document.getElementById("dateInput").value = todayISO();
  document.getElementById("addFormTitle").textContent = "Add expense";
  document.getElementById("submitExpenseBtn").textContent = "Save expense";
  document.getElementById("aiTextInput").value = "";
  document.getElementById("aiStatusMsg").textContent = "";
}

function editExpense(id) {
  const expense = state.expenses.find((e) => e.id === id) ||
    (state.summary && state.summary.recent_expenses.find((e) => e.id === id));
  if (!expense) return;

  state.editingExpenseId = id;
  document.getElementById("expenseId").value = id;
  document.getElementById("amountInput").value = expense.amount;
  document.getElementById("categorySelect").value = expense.category_id;
  document.getElementById("dateInput").value = expense.date;
  document.getElementById("paymentSelect").value = expense.payment_method;
  document.getElementById("descriptionInput").value = expense.description || "";
  document.getElementById("notesInput").value = expense.notes || "";
  document.getElementById("addFormTitle").textContent = "Edit expense";
  document.getElementById("submitExpenseBtn").textContent = "Update expense";

  switchView("add");
}

async function deleteExpense(id) {
  askConfirm("Delete this expense? This cannot be undone.", async () => {
    try {
      await api.del(`/expenses/${id}`);
      showToast("Expense deleted", "success");
      await loadExpenses();
      await refreshDashboard();
      await loadCategories();
    } catch (e) {
      showToast(e.message, "error");
    }
  });
}

function setupExpenseForm() {
  document.getElementById("expenseForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const payload = {
      amount: parseFloat(document.getElementById("amountInput").value),
      category_id: parseInt(document.getElementById("categorySelect").value, 10),
      date: document.getElementById("dateInput").value,
      payment_method: document.getElementById("paymentSelect").value,
      description: document.getElementById("descriptionInput").value.trim(),
      notes: document.getElementById("notesInput").value.trim(),
    };

    try {
      if (state.editingExpenseId) {
        await api.put(`/expenses/${state.editingExpenseId}`, payload);
        showToast("Expense updated", "success");
      } else {
        await api.post("/expenses", payload);
        showToast("Expense added", "success");
      }
      resetExpenseForm();
      await refreshDashboard();
      await loadCategories();
      if (document.getElementById("view-expenses").classList.contains("active")) await loadExpenses();
      switchView("dashboard");
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  document.getElementById("cancelEditBtn").addEventListener("click", () => {
    resetExpenseForm();
    switchView("dashboard");
  });

  document.getElementById("quickAddBtn").addEventListener("click", () => switchView("add"));
}

/* ==========================================================================
   AI — natural language quick add
   ========================================================================== */
function setupAIParse() {
  const btn = document.getElementById("aiParseBtn");
  const input = document.getElementById("aiTextInput");
  const status = document.getElementById("aiStatusMsg");

  async function run() {
    const text = input.value.trim();
    if (!text) return;
    btn.disabled = true;
    btn.textContent = "Parsing...";
    status.className = "ai-status";
    status.textContent = "Asking Gemini to read your expense...";

    try {
      const parsed = await api.post("/ai/parse", { text });
      document.getElementById("amountInput").value = parsed.amount || "";
      if (parsed.category_id) document.getElementById("categorySelect").value = parsed.category_id;
      document.getElementById("dateInput").value = parsed.date || todayISO();
      document.getElementById("paymentSelect").value = parsed.payment_method || "Cash";
      document.getElementById("descriptionInput").value = parsed.description || "";

      status.className = "ai-status success";
      status.innerHTML = `<i data-lucide="check"></i> Parsed — review the details below, then save.`;
      refreshIcons();
    } catch (e) {
      status.className = "ai-status error";
      status.innerHTML = `<i data-lucide="triangle-alert"></i> ${escapeHtml(e.message)}`;
      refreshIcons();
    } finally {
      btn.disabled = false;
      btn.textContent = "Parse";
    }
  }

  btn.addEventListener("click", run);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); run(); } });
}

/* ==========================================================================
   AI — insights
   ========================================================================== */
function setupAIInsights() {
  document.getElementById("generateInsightsBtn").addEventListener("click", async () => {
    const container = document.getElementById("insightsContent");
    container.innerHTML = `<div class="insights-loading">⏳ Analyzing your spending with Gemini...</div>`;
    try {
      const data = await api.get("/ai/insights?days=30");
      if (!data.insights || data.insights.length === 0) {
        container.innerHTML = `<div class="empty-state"><i data-lucide="bot"></i><p>No insights available yet.</p></div>`;
        refreshIcons();
        return;
      }
      container.innerHTML = data.insights.map((text) =>
        `<div class="insight-item"><i data-lucide="sparkle"></i><span>${escapeHtml(text)}</span></div>`
      ).join("");
      refreshIcons();
    } catch (e) {
      container.innerHTML = `<div class="empty-state"><i data-lucide="triangle-alert"></i><p>${escapeHtml(e.message)}</p></div>`;
      refreshIcons();
    }
  });
}

/* ==========================================================================
   Dashboard
   ========================================================================== */
async function refreshDashboard() {
  const summary = await api.get("/summary");
  state.summary = summary;

  document.getElementById("statTotal").textContent = fmtCurrency(summary.total_spent);
  document.getElementById("statThisMonth").textContent = fmtCurrency(summary.total_this_month);
  document.getElementById("statLastMonth").textContent = fmtCurrency(summary.total_last_month);

  const changeEl = document.getElementById("statChange");
  if (summary.change_percent === null) {
    changeEl.textContent = "No data for last month";
    changeEl.className = "stat-sub";
  } else {
    const up = summary.change_percent >= 0;
    changeEl.innerHTML = `<i data-lucide="${up ? "trending-up" : "trending-down"}"></i> ${Math.abs(summary.change_percent)}% vs last month`;
    changeEl.className = "stat-sub " + (up ? "positive" : "negative");
    refreshIcons();
  }

  const top = summary.by_category[0];
  document.getElementById("statTopCategory").textContent = top ? `${top.icon} ${top.name}` : "—";
  document.getElementById("statTopCategoryAmount").textContent = top ? fmtCurrency(top.spent) + " this month" : "No spending yet";

  renderCategoryChart(summary.by_category);
  renderTrendChart(summary.daily_trend);
  renderRecentExpenses(summary.recent_expenses);
  renderBudgetProgress(summary.by_category);
}

function renderRecentExpenses(expenses) {
  const container = document.getElementById("recentExpensesList");
  if (expenses.length === 0) {
    container.innerHTML = `<div class="empty-state"><i data-lucide="inbox"></i><p>No expenses yet. Add your first one!</p></div>`;
    refreshIcons();
    return;
  }
  container.innerHTML = expenses.map(expenseRowHTML).join("");
  attachRowHandlers(container);
  refreshIcons();
}

function renderBudgetProgress(byCategory) {
  const container = document.getElementById("budgetProgressList");
  const budgeted = byCategory.filter((c) => c.monthly_budget > 0);

  if (budgeted.length === 0) {
    container.innerHTML = `<div class="empty-state"><i data-lucide="target"></i><p>Set monthly budgets in "Categories &amp; Budgets" to track progress here.</p></div>`;
    refreshIcons();
    return;
  }

  container.innerHTML = budgeted.map((c) => {
    const pct = Math.min(100, c.budget_percent_used || 0);
    const over = c.budget_percent_used > 100;
    return `
      <div class="budget-item">
        <div class="budget-item-header">
          <span class="name">${c.icon} ${c.name}</span>
          <span class="amounts">${fmtCurrency(c.spent)} / ${fmtCurrency(c.monthly_budget)}</span>
        </div>
        <div class="budget-bar-bg">
          <div class="budget-bar-fill" style="width:${pct}%; background:${over ? "var(--danger)" : c.color}"></div>
        </div>
        ${over ? `<div class="budget-warning"><i data-lucide="triangle-alert"></i> Over budget by ${fmtCurrency(c.spent - c.monthly_budget)}</div>` : ""}
      </div>`;
  }).join("");
  refreshIcons();
}

function getChartTextColor() {
  return getComputedStyle(document.documentElement).getPropertyValue("--text").trim();
}

function renderCategoryChart(byCategory) {
  const ctx = document.getElementById("categoryChart");
  const data = byCategory.filter((c) => c.spent > 0);

  if (categoryChart) categoryChart.destroy();

  if (data.length === 0) {
    ctx.getContext("2d").clearRect(0, 0, ctx.width, ctx.height);
    return;
  }

  categoryChart = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels: data.map((c) => c.name),
      datasets: [{
        data: data.map((c) => c.spent),
        backgroundColor: data.map((c) => c.color),
        borderWidth: 2,
        borderColor: getComputedStyle(document.documentElement).getPropertyValue("--surface").trim(),
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { position: "bottom", labels: { color: getChartTextColor(), font: { size: 11 }, boxWidth: 10, padding: 12 } },
        tooltip: { callbacks: { label: (item) => ` ${item.label}: ${fmtCurrency(item.raw)}` } },
      },
      cutout: "65%",
    },
  });
}

function renderTrendChart(dailyTrend) {
  const ctx = document.getElementById("trendChart");
  if (trendChart) trendChart.destroy();

  const gridColor = getComputedStyle(document.documentElement).getPropertyValue("--border").trim();
  const textColor = getChartTextColor();
  const accentHex = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim();
  const accentRgb = hexToRgbTriplet(accentHex);

  trendChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: dailyTrend.map((d) => fmtDateShort(d.date)),
      datasets: [{
        label: "Spent",
        data: dailyTrend.map((d) => d.total),
        borderColor: accentHex,
        backgroundColor: `rgba(${accentRgb}, 0.14)`,
        fill: true, tension: 0.35, pointRadius: 0, borderWidth: 2,
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (item) => ` ${fmtCurrency(item.raw)}` } },
      },
      scales: {
        x: { ticks: { color: textColor, maxTicksLimit: 6, font: { size: 10 } }, grid: { display: false } },
        y: { ticks: { color: textColor, font: { size: 10 } }, grid: { color: gridColor } },
      },
    },
  });
}

/* ==========================================================================
   Misc: export, confirm modal, escaping
   ========================================================================== */
function setupExport() {
  document.getElementById("exportCsvBtn").addEventListener("click", () => {
    window.location.href = API_BASE + "/export/csv";
  });
}

function setupConfirmModal() {
  document.getElementById("confirmCancelBtn").addEventListener("click", () => {
    document.getElementById("confirmModal").classList.add("hidden");
    confirmCallback = null;
  });
  document.getElementById("confirmOkBtn").addEventListener("click", () => {
    document.getElementById("confirmModal").classList.add("hidden");
    if (confirmCallback) confirmCallback();
    confirmCallback = null;
  });
}

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

/* ==========================================================================
   Init
   ========================================================================== */
async function init() {
  document.getElementById("todayDate").textContent = new Date().toLocaleDateString("en-IN", {
    weekday: "long", day: "numeric", month: "long", year: "numeric",
  });
  document.getElementById("dateInput").value = todayISO();

  setupTheme();
  setupNavigation();
  setupFilters();
  setupExpenseForm();
  setupCategoryForm();
  setupAIParse();
  setupAIInsights();
  setupExport();
  setupConfirmModal();

  refreshIcons();

  try {
    await loadCategories();
    await refreshDashboard();
  } catch (e) {
    showToast("Could not connect to the backend. Is app.py running?", "error");
  }
}

document.addEventListener("DOMContentLoaded", init);
