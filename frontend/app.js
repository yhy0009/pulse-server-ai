"use strict";

const $ = (selector) => document.querySelector(selector);
const base = (window.APP_CONFIG?.API_BASE_URL || "").replace(/\/$/, "");
const state = { records: [], summary: null, health: null, conversations: [], historyTotal: 0, conversationId: null, messages: [], page: 0, editing: null, busy: false, dataBusy: false };
const welcome = $("#chat-welcome").cloneNode(true);
const dateFormatter = new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
const shortDate = (value) => dateFormatter.format(new Date(value));
const number = (value, digits = 2) => Number(value).toLocaleString("ko-KR", { minimumFractionDigits: digits, maximumFractionDigits: digits });
let toastTimer;

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function toast(message) {
  clearTimeout(toastTimer);
  $("#toast").textContent = message;
  $("#toast").hidden = false;
  toastTimer = setTimeout(() => { $("#toast").hidden = true; }, 5000);
}

async function api(path, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 80000);
  try {
    const response = await fetch(base + path, {
      ...options, signal: controller.signal,
      headers: { ...(options.body ? { "Content-Type": "application/json" } : {}), ...options.headers },
    });
    if (response.status === 204) return null;
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : `요청을 처리하지 못했습니다. (${response.status})`);
    return body;
  } catch (error) {
    if (error.name === "AbortError") throw new Error("서버 연결이 지연되고 있습니다. 잠시 후 다시 연결해 주세요. 채팅을 전송했다면 대화 기록에서 저장 여부를 먼저 확인해 주세요.");
    if (error instanceof TypeError) throw new Error("API 서버에 연결할 수 없습니다. 서버 주소와 CORS 설정을 확인해 주세요.");
    throw error;
  } finally { clearTimeout(timer); }
}

async function allRecords() {
  const records = [];
  let offset = 0;
  while (true) {
    const page = await api(`/api/data?limit=2000&offset=${offset}`);
    records.push(...page.items);
    offset += page.items.length;
    if (offset >= page.total || !page.items.length) return records;
  }
}

function renderHealth() {
  const demo = state.health.ai_provider !== "openai";
  const firestore = state.health.storage === "firestore";
  $("#connection").className = "connection connected";
  $("#connection span").textContent = demo ? "로컬 데모 연결됨" : "GPT API 사용 모드";
  $("#mode-banner").textContent = demo
    ? "합성 데이터 · 로컬 데모입니다. 통계 기반 예시 답변을 제공하며, GPT API와 Firestore는 연결되지 않았습니다."
    : firestore
      ? "합성 데이터 · Firestore와 GPT API를 사용합니다. 마지막 관측 시각을 기준으로 답변합니다."
      : "합성 데이터 · 실제 GPT API와 로컬 DB(SQLite)를 사용합니다. Firestore는 아직 연결되지 않았습니다.";
  $("#chat-provider").textContent = demo ? "통계 기반 예시 답변 · GPT 미연결" : `GPT API · ${state.health.ai_model || "설정된 모델"}`;
  $("#chat-footer").textContent = demo ? "로컬 데모의 예시 답변이며 GPT가 생성하지 않습니다." : "AI 답변의 수치와 해석을 원본 데이터와 함께 확인하세요.";
  $("#chat-input").disabled = false;
  $("#send-button").disabled = false;
}

async function refreshData() {
  const [records, summary] = await Promise.all([allRecords(), api("/api/data/summary")]);
  state.records = records;
  state.summary = summary;
  renderSummary();
  renderChart();
  renderTable();
}

function renderSummary() {
  const summary = state.summary;
  $("#nav-count").textContent = summary.count.toLocaleString();
  $("#record-count").replaceChildren(document.createTextNode(summary.count.toLocaleString()), element("span", "", "개"));
  const timestamps = new Set(state.records.map((row) => row.date)).size;
  $("#record-period").textContent = `${timestamps.toLocaleString()}개 시점 · CPU + 메모리`;
  $("#chat-context").textContent = `demo-01 · 관측값 ${summary.count.toLocaleString()}개`;
  for (const metric of ["cpu", "memory"]) {
    const info = summary.metrics[metric];
    $(`#${metric}-value`).replaceChildren(document.createTextNode(info ? number(info.latest) : "—"), element("span", "", "%"));
    $(`#${metric}-detail`).textContent = info ? `전체 평균 ${number(info.average)}% · 최고 ${number(info.max)}%` : "저장된 데이터가 없습니다";
    $(`#${metric}-track`).style.width = `${info?.latest || 0}%`;
  }
  $("#last-observed").textContent = summary.period ? `마지막 관측 ${shortDate(summary.period.end)} KST` : "관측 데이터 없음";
  if (!state.editing) $("#data-date").value = summary.period ? new Date(new Date(summary.period.end).getTime() + 3600000 + 9 * 3600000).toISOString().slice(0, 16) : new Date(Date.now() + 9 * 3600000).toISOString().slice(0, 16);
  const observations = $("#observations");
  observations.replaceChildren();
  for (const [metric, label, symbol] of [["cpu", "CPU", "↗"], ["memory", "메모리", "≋"]]) {
    const info = summary.metrics[metric];
    if (!info) continue;
    const row = element("div", "observation");
    row.append(element("span", "observation-icon", symbol));
    const body = element("div");
    body.append(element("h3", "", `${label} 최고 ${number(info.max)}% · ${shortDate(info.max_at)} KST`));
    const trend = info.change_pp === null ? "직전 24시간과 비교할 데이터가 부족합니다." : `최근 24시간 평균 ${number(info.recent_24h_average)}%, 직전 대비 ${info.change_pp >= 0 ? "+" : ""}${number(info.change_pp)}%p (${info.trend}).`;
    body.append(element("p", "", `기준 ${info.threshold}% 이상 관측 ${info.threshold_count}개. ${trend}`));
    row.append(body);
    observations.append(row);
  }
  if (!observations.children.length) observations.append(element("p", "muted", "데이터를 추가하면 요약과 추세가 표시됩니다."));
}

function svgNode(tag, attributes, text) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
  if (text !== undefined) node.textContent = text;
  return node;
}

function renderChart() {
  const target = $("#metrics-chart");
  target.replaceChildren();
  if (!state.records.length) {
    target.append(element("div", "empty-chart", "표시할 데이터가 없습니다. 관측값을 추가해 주세요."));
    $("#chart-period").textContent = "관측 데이터 없음";
    return;
  }
  const last = Math.max(...state.records.map((row) => new Date(row.date).getTime()));
  const range = $("#chart-range").value;
  const rows = state.records.filter((row) => range === "all" || new Date(row.date).getTime() >= last - (Number(range) - 1) * 3600000).sort((a, b) => new Date(a.date) - new Date(b.date));
  const first = new Date(rows[0].date).getTime();
  $("#chart-period").textContent = `${shortDate(new Date(first))} — ${shortDate(new Date(last))} KST`;
  const width = Math.max(360, target.clientWidth), height = target.clientHeight || 244;
  const plot = { left: 32, top: 15, right: width - 12, bottom: height - 29 };
  const x = (stamp) => plot.left + (stamp - first) / Math.max(1, last - first) * (plot.right - plot.left);
  const y = (value) => plot.bottom - value / 100 * (plot.bottom - plot.top);
  const svg = svgNode("svg", { viewBox: `0 0 ${width} ${height}`, "aria-hidden": "true" });
  for (const value of [0, 25, 50, 75, 100]) {
    svg.append(svgNode("line", { x1: plot.left, x2: plot.right, y1: y(value), y2: y(value), stroke: "#2c3740", "stroke-width": 0.7, "stroke-dasharray": "3 5" }));
    svg.append(svgNode("text", { x: plot.left - 10, y: y(value) + 3, fill: "#82909b", "font-family": "monospace", "font-size": 8, "text-anchor": "end" }, value));
  }
  svg.append(svgNode("line", { x1: plot.left, x2: plot.right, y1: y(85), y2: y(85), stroke: "#b2a581", "stroke-width": 0.8, "stroke-dasharray": "5 5", opacity: .65 }));
  const tickFormatter = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Seoul", ...(range === "24" ? { hour: "2-digit", minute: "2-digit", hourCycle: "h23" } : { month: "2-digit", day: "2-digit" }) });
  for (let index = 0; index < 5; index++) {
    const stamp = first + (last - first) * index / 4;
    svg.append(svgNode("text", { x: x(stamp), y: height - 7, fill: "#82909b", "font-family": "monospace", "font-size": 8, "text-anchor": index === 0 ? "start" : index === 4 ? "end" : "middle" }, tickFormatter.format(new Date(stamp))));
  }
  for (const [metric, color] of [["memory", "#9eaff6"], ["cpu", "#a2e4c3"]]) {
    const selected = rows.filter((row) => row.metric === metric);
    if (!selected.length) continue;
    const coordinates = selected.map((row) => `${x(new Date(row.date))},${y(row.value)}`);
    const fill = `${x(new Date(selected[0].date))},${plot.bottom} ${coordinates.join(" ")} ${x(new Date(selected.at(-1).date))},${plot.bottom}`;
    svg.append(svgNode("polygon", { points: fill, fill: color, opacity: .035 }));
    svg.append(svgNode("polyline", { points: coordinates.join(" "), fill: "none", stroke: color, "stroke-width": 1.7, "stroke-linejoin": "round", "stroke-linecap": "round" }));
    for (const row of selected) {
      const dot = svgNode("circle", { cx: x(new Date(row.date)), cy: y(row.value), r: selected.length === 1 ? 3 : 4, fill: color, opacity: selected.length === 1 ? 1 : 0, "pointer-events": "all" });
      dot.append(svgNode("title", {}, `${metric === "cpu" ? "CPU" : "메모리"} ${number(row.value)}% · ${shortDate(row.date)} KST`));
      svg.append(dot);
    }
  }
  target.append(svg);
  target.setAttribute("aria-label", `CPU와 메모리 사용률. ${shortDate(new Date(first))}부터 ${shortDate(new Date(last))} KST까지. 수치 요약은 아래 데이터에서 확인한 것 영역에 표시됩니다.`);
}

function renderTable() {
  const filter = $("#table-metric").value;
  const rows = state.records.filter((row) => filter === "all" || row.metric === filter);
  const pages = Math.max(1, Math.ceil(rows.length / 12));
  state.page = Math.min(state.page, pages - 1);
  $("#table-count").textContent = rows.length.toLocaleString();
  const body = $("#data-rows");
  body.replaceChildren();
  for (const row of rows.slice(state.page * 12, state.page * 12 + 12)) {
    const tr = element("tr");
    tr.append(element("td", "date", shortDate(row.date)));
    const metricCell = element("td");
    metricCell.append(element("span", `metric-badge ${row.metric}`, row.metric === "cpu" ? "CPU" : "MEM"));
    tr.append(metricCell, element("td", "value", `${number(row.value)}%`));
    const memo = element("td", "memo", row.memo || "—");
    memo.title = row.memo;
    tr.append(memo);
    const actionsCell = element("td");
    const actions = element("div", "row-actions");
    for (const [action, label] of [["edit", "수정"], ["delete", "삭제"]]) {
      const button = element("button", `text-button ${action}`, label);
      button.dataset.action = action;
      button.dataset.id = row.id;
      button.disabled = state.dataBusy;
      button.setAttribute("aria-label", `${shortDate(row.date)} ${row.metric} ${label}`);
      actions.append(button);
    }
    actionsCell.append(actions); tr.append(actionsCell); body.append(tr);
  }
  if (!rows.length) { const tr = element("tr"), td = element("td", "muted", "저장된 관측값이 없습니다."); td.colSpan = 5; tr.append(td); body.append(tr); }
  $("#page-label").textContent = `${state.page + 1} / ${pages} 페이지 · 총 ${rows.length.toLocaleString()}개`;
  $("#previous-page").disabled = state.page === 0;
  $("#next-page").disabled = state.page >= pages - 1;
}

function setView(name) {
  document.querySelectorAll(".view").forEach((view) => { view.hidden = view.id !== `view-${name}`; });
  document.querySelectorAll(".nav-button").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === name);
    if (button.dataset.view === name) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current");
  });
  if (name === "history") refreshHistory().catch((error) => toast(error.message));
  if (name === "overview") requestAnimationFrame(renderChart);
}

function renderMessages() {
  const container = $("#messages");
  container.replaceChildren();
  if (!state.messages.length) container.append(welcome.cloneNode(true));
  for (const message of state.messages) {
    const node = element("div", `message ${message.role}`);
    node.append(element("span", "message-label", message.role === "user" ? "YOU" : "PULSE"));
    node.append(document.createTextNode(message.content));
    container.append(node);
  }
  container.scrollTop = container.scrollHeight;
  $("#save-copy").disabled = !state.messages.length || state.busy;
}

function setChatBusy(busy) {
  state.busy = busy;
  $("#chat-input").disabled = busy || !state.health;
  $("#send-button").disabled = busy || !state.health;
  $("#new-chat").disabled = busy;
  $("#chat-loading").hidden = !busy;
  $("#save-copy").disabled = busy || !state.messages.length;
  document.querySelectorAll("[data-question], [data-history-action]").forEach((button) => { button.disabled = busy; });
}

async function sendQuestion(question) {
  if (state.busy || !state.health || !question.trim()) return;
  $("#chat-error").hidden = true;
  const previous = state.messages;
  const user = { role: "user", content: question.trim(), created_at: new Date().toISOString() };
  state.messages = [...previous, user];
  renderMessages();
  $("#chat-input").value = "";
  setChatBusy(true);
  const slow = setTimeout(() => { $("#chat-error").textContent = "첫 요청은 서버 시작으로 지연될 수 있습니다. 연결을 기다리는 중입니다."; $("#chat-error").hidden = false; }, 8000);
  try {
    const result = await api("/api/chat", { method: "POST", body: JSON.stringify({ message: user.content, conversation_id: state.conversationId }) });
    state.conversationId = result.conversation_id;
    state.messages = [...previous, user, result.message];
    renderMessages();
    $("#chat-error").hidden = true;
    refreshHistory().catch((error) => toast(`대화는 저장되었지만 목록 갱신에 실패했습니다. ${error.message}`));
  } catch (error) {
    state.messages = previous;
    renderMessages();
    $("#chat-input").value = question;
    $("#chat-error").textContent = error.message;
    $("#chat-error").hidden = false;
  } finally { clearTimeout(slow); setChatBusy(false); $("#chat-input").focus(); }
}

async function refreshHistory(more = false) {
  const offset = more ? state.conversations.length : 0;
  const response = await api(`/api/conversations?limit=50&offset=${offset}`);
  state.conversations = more ? [...state.conversations, ...response.items] : response.items;
  state.historyTotal = response.total;
  renderHistory();
}

function renderHistory() {
  $("#history-count").textContent = `저장된 대화 ${state.historyTotal}개`;
  const target = $("#history-list"); target.replaceChildren();
  if (!state.conversations.length) target.append(element("div", "history-empty", "아직 저장된 대화가 없습니다.\n질문을 보내면 대화가 자동으로 저장됩니다."));
  for (const conversation of state.conversations) {
    const card = element("article", "history-card");
    card.append(element("span", "history-symbol", "◷"));
    const body = element("div", "history-body");
    body.append(element("h3", "", conversation.title));
    body.append(element("p", "", `${shortDate(conversation.updated_at)} KST · 메시지 ${conversation.message_count}개 · ${conversation.provider === "demo-rules" ? "로컬 데모" : conversation.provider === "openai" ? "GPT API" : "저장한 사본"}`));
    const actions = element("div", "history-actions");
    for (const [action, label] of [["load", "불러오기"], ["delete", "삭제"]]) {
      const button = element("button", action === "load" ? "button secondary small" : "text-button delete", label);
      button.dataset.historyAction = action; button.dataset.id = conversation.id; button.disabled = state.busy;
      button.setAttribute("aria-label", `${conversation.title} ${label}`);
      actions.append(button);
    }
    card.append(body, actions); target.append(card);
  }
  $("#more-history").hidden = state.conversations.length >= state.historyTotal;
}

async function confirmDelete(description) {
  const dialog = $("#confirm-dialog");
  $("#confirm-description").textContent = description;
  dialog.returnValue = "cancel";
  dialog.showModal();
  return new Promise((resolve) => { dialog.addEventListener("close", () => resolve(dialog.returnValue === "confirm"), { once: true }); });
}

function resetDataForm() {
  state.editing = null; $("#data-form").reset();
  $("#data-form-title").textContent = "관측값 추가";
  $("#data-submit").textContent = "관측값 추가";
  $("#cancel-edit").hidden = true;
  if (state.summary) renderSummary();
}

function setDataBusy(busy) {
  state.dataBusy = busy;
  $("#data-form").querySelectorAll("input,select,button").forEach((node) => { node.disabled = busy; });
  document.querySelectorAll("#data-rows button").forEach((node) => { node.disabled = busy; });
}

async function init() {
  $("#global-error").hidden = true;
  $("#retry-button").disabled = true;
  const slow = setTimeout(() => { $("#mode-banner").textContent = "서버를 시작하는 중일 수 있습니다. 첫 연결에는 시간이 걸릴 수 있으니 잠시 기다려 주세요."; }, 8000);
  try {
    state.health = await api("/api/health");
    await refreshData();
    renderHealth();
    await refreshHistory();
  } catch (error) {
    $("#connection").className = "connection failed";
    $("#connection span").textContent = "연결 확인 필요";
    $("#global-error-text").textContent = error.message;
    $("#global-error").hidden = false;
    $("#mode-banner").textContent = "연결 상태를 확인해 주세요. 아래에서 다시 연결할 수 있습니다.";
  } finally { clearTimeout(slow); $("#retry-button").disabled = false; }
}

$("#docs-link").href = base + "/docs";
document.querySelectorAll(".nav-button").forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
$("#retry-button").addEventListener("click", init);
$("#chart-range").addEventListener("change", renderChart);
$("#table-metric").addEventListener("change", () => { state.page = 0; renderTable(); });
$("#previous-page").addEventListener("click", () => { state.page--; renderTable(); });
$("#next-page").addEventListener("click", () => { state.page++; renderTable(); });
$("#cancel-edit").addEventListener("click", resetDataForm);
$("#more-history").addEventListener("click", async () => { $("#more-history").disabled = true; try { await refreshHistory(true); } catch (error) { toast(error.message); } finally { $("#more-history").disabled = false; } });
$("#messages").addEventListener("click", (event) => { const button = event.target.closest("[data-question]"); if (button) sendQuestion(button.dataset.question); });
$("#chat-form").addEventListener("submit", (event) => { event.preventDefault(); sendQuestion($("#chat-input").value); });
$("#chat-input").addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); sendQuestion(event.target.value); } });
$("#new-chat").addEventListener("click", () => { if (state.busy) return; state.conversationId = null; state.messages = []; renderMessages(); $("#chat-error").hidden = true; $("#chat-input").value = ""; $("#chat-input").focus(); });

$("#data-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.dataBusy) return;
  const date = $("#data-date").value;
  const payload = { date: `${date}:00+09:00`, metric: $("#data-metric").value, value: Number($("#data-value").value), memo: $("#data-memo").value, host: "demo-01" };
  setDataBusy(true);
  let saved = false;
  try {
    await api(state.editing ? `/api/data/${state.editing}` : "/api/data", { method: state.editing ? "PUT" : "POST", body: JSON.stringify(payload) });
    saved = true;
    toast(state.editing ? "관측값을 수정했습니다." : "관측값을 추가했습니다.");
    resetDataForm(); state.page = 0;
    await refreshData();
  } catch (error) { toast(`${saved ? "저장 후 화면 갱신에 실패했습니다. " : ""}${error.message}`); }
  finally { setDataBusy(false); }
});

$("#data-rows").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-action]");
  if (!button || state.dataBusy) return;
  const row = state.records.find((item) => item.id === button.dataset.id);
  if (!row) return;
  if (button.dataset.action === "edit") {
    state.editing = row.id;
    $("#data-metric").value = row.metric; $("#data-date").value = row.date.slice(0, 16);
    $("#data-value").value = row.value; $("#data-memo").value = row.memo;
    $("#data-form-title").textContent = "관측값 수정"; $("#data-submit").textContent = "수정 저장"; $("#cancel-edit").hidden = false;
    $("#data-value").focus(); $("#data-form").scrollIntoView({ block: "center", behavior: "smooth" });
    return;
  }
  if (!await confirmDelete(`${shortDate(row.date)} KST의 ${row.metric.toUpperCase()} ${number(row.value)}% 관측값을 삭제합니다.`)) return;
  setDataBusy(true);
  let deleted = false;
  try {
    await api(`/api/data/${row.id}`, { method: "DELETE" }); deleted = true;
    if (state.editing === row.id) resetDataForm();
    await refreshData(); toast("관측값을 삭제하고 요약을 갱신했습니다.");
  } catch (error) { toast(`${deleted ? "삭제 후 화면 갱신에 실패했습니다. " : ""}${error.message}`); }
  finally { setDataBusy(false); }
});

$("#history-list").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-history-action]");
  if (!button || state.busy) return;
  const id = button.dataset.id;
  if (button.dataset.historyAction === "load") {
    setChatBusy(true);
    try {
      const conversation = await api(`/api/conversations/${id}`);
      state.conversationId = id; state.messages = conversation.messages; renderMessages();
      $("#chat-error").hidden = true; toast("이전 대화를 불러왔습니다. 이어서 질문해 보세요.");
      if (window.innerWidth <= 1050) $(".chat-panel").scrollIntoView({ block: "start", behavior: "smooth" });
    } catch (error) { toast(error.message); }
    finally { setChatBusy(false); }
  } else if (await confirmDelete("저장된 대화와 그 안의 메시지를 삭제합니다.")) {
    setChatBusy(true);
    try {
      await api(`/api/conversations/${id}`, { method: "DELETE" });
      if (state.conversationId === id) { state.conversationId = null; state.messages = []; renderMessages(); }
      await refreshHistory(); toast("대화 기록을 삭제했습니다.");
    } catch (error) { toast(error.message); }
    finally { setChatBusy(false); }
  }
});

$("#save-copy").addEventListener("click", async () => {
  if (state.busy || !state.messages.length) return;
  setChatBusy(true);
  try {
    await api("/api/conversations", { method: "POST", body: JSON.stringify({ title: `${state.messages[0].content.slice(0, 50)} (사본)`, messages: state.messages }) });
    await refreshHistory(); toast("현재 대화의 사본을 저장했습니다.");
  } catch (error) { toast(error.message); }
  finally { setChatBusy(false); }
});

$("#export-button").addEventListener("click", () => {
  const fields = ["date", "metric", "value", "memo", "host"];
  const cell = (value) => { const text = String(value ?? ""); return `"${(/^[\s]*[=+@-]/.test(text) ? "'" + text : text).replaceAll('"', '""')}"`; };
  const csv = "\uFEFF" + [fields.join(","), ...state.records.map((row) => fields.map((field) => cell(row[field])).join(","))].join("\r\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8;" }));
  const link = element("a"); link.href = url; link.download = "pulse-synthetic-metrics.csv"; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  toast(`${state.records.length}개 합성 관측값을 CSV로 내보냈습니다.`);
});

let resizeTimer;
window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => { if (state.summary && !$("#view-overview").hidden) renderChart(); }, 150); });
init();
