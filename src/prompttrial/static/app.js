"use strict";
const $ = (id) => document.getElementById(id);
let report = null;
let jobId = null;
let working = false;
let localModel = null;
function node(tag, text, className) {
  const n = document.createElement(tag);
  if (text !== undefined) n.textContent = text;
  if (className) n.className = className;
  return n;
}
async function api(path, options) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Некорректные параметры запроса.");
  return data;
}
function error(message) { $("error").textContent = message; $("error").hidden = false; }
function providerNote() {
  $("provider-note").textContent = $("provider").value === "replay"
    ? "Демо проверяет работу инструмента на записанных ответах. Это не оценка качества модели."
    : "Модель: " + localModel + ". Прогон может занять несколько минут. Запросы идут на локальный сервер.";
}
function renderCases() {
  $("cases").replaceChildren();
  if (!report) return;
  let visible = 0;
  report.results.forEach((result, index) => {
    if ($("failed-only").checked && result.passed) return;
    visible++;
    const card = node("details", undefined, "case" + (result.passed ? "" : " fail"));
    const summary = node("summary");
    summary.append(node("span", result.passed ? "✓" : "×"), node("span", result.case_id), node("small", "#" + (index + 1) + " · " + result.latency_ms.toFixed(1) + " ms"));
    const body = node("div", undefined, "case-body");
    for (const [label, value] of [["Задание", result.task], ["Входные данные", result.input], ["Ожидалось", typeof result.expected === "string" ? result.expected : JSON.stringify(result.expected, null, 2)], ["Ответ", result.output || "(нет ответа)"]]) {
      body.append(node("h4", label), node("pre", value));
    }
    body.append(node("p", result.reason + (result.error ? " · " + result.error : "")));
    card.append(summary, body);
    $("cases").append(card);
  });
  if (!visible) $("cases").append(node("p", "Нет ошибок в выбранном запуске.", "hint"));
}
function renderReport(data) {
  report = data;
  $("report").hidden = false;
  $("empty").hidden = true;
  $("mode-badge").textContent = data.provider === "replay" ? "REPLAY DEMO · NO INFERENCE" : "LOCAL MODEL";
  $("report-title").textContent = data.prompt === "strict" ? "Strict prompt" : "Basic prompt";
  $("report-subtitle").textContent = data.model + " · " + new Date(data.created_at).toLocaleString("ru-RU");
  $("scope").textContent = data.provider === "replay"
    ? "Результаты записанных ответов: четыре ошибки включены специально. Цифры ниже не описывают качество или скорость LLM."
    : "Авторский набор регрессионных заданий. Точные проверки не оценивают общее качество модели и смысловую правильность свободных ответов.";
  $("export-json").href = "/api/runs/" + data.id + "/export?format=json";
  $("export-md").href = "/api/runs/" + data.id + "/export?format=markdown";
  $("metrics").replaceChildren();
  const s = data.summary;
  for (const [value, label] of [[(s.pass_rate * 100).toFixed(1) + "%", "Проверок пройдено"], [s.passed + "/" + s.total, "Успешных ответов"], [data.provider === "replay" ? "—" : s.latency_p95_ms.toFixed(0) + " ms", "p95 без ошибок API"], [s.provider_errors, "Ошибок провайдера"]]) {
    const card = node("div", undefined, "metric");
    card.append(node("strong", String(value)), node("span", label));
    $("metrics").append(card);
  }
  $("categories").replaceChildren();
  for (const [name, value] of Object.entries(s.categories)) {
    const row = node("div", undefined, "category");
    const bar = node("div", undefined, "bar");
    const fill = node("i"); fill.style.width = value.pass_rate * 100 + "%"; bar.append(fill);
    row.append(node("span", name), bar, node("span", value.passed + "/" + value.total));
    $("categories").append(row);
  }
  $("metadata").replaceChildren();
  for (const [label, value] of [["Run ID", data.id], ["Suite SHA-256", data.suite_hash], ["Prompt SHA-256", data.prompt_hash], ["Повторов", data.repetitions], ["Входных токенов", s.input_tokens ?? "неизвестно"], ["Выходных токенов", s.output_tokens ?? "неизвестно"]]) $("metadata").append(node("p", label + ": " + value));
  renderCases();
}
async function history() {
  const runs = await api("/api/runs");
  $("history").replaceChildren();
  for (const select of [$("baseline"), $("candidate")]) {
    const old = select.value;
    select.replaceChildren(node("option", "Выберите запуск")); select.firstChild.value = "";
    for (const run of runs) {
      const option = node("option", run.prompt + " / " + run.provider + " / " + run.id.slice(0, 6)); option.value = run.id; select.append(option);
    }
    if (runs.some((r) => r.id === old)) select.value = old;
  }
  if (!runs.length) $("history").append(node("p", "Здесь появятся ваши запуски.", "hint"));
  for (const run of runs.slice(0, 12)) {
    const button = node("button", undefined, "history-item"); button.type = "button";
    const label = node("span", run.prompt + " / " + run.provider); label.append(node("small", new Date(run.created_at).toLocaleString("ru-RU")));
    button.append(label, node("b", run.summary.passed + "/" + run.summary.total));
    button.addEventListener("click", async () => { try { renderReport(await api("/api/runs/" + run.id)); } catch (e) { error(e.message); } });
    $("history").append(button);
  }
  return runs;
}
async function followJob(id) {
  working = true; jobId = id; $("run").disabled = true; $("cancel").hidden = false;
  $("status").textContent = "Проверка выполняется…";
  try {
    while (true) {
      const job = await api("/api/jobs/" + id);
      if (job.status === "completed") {
        renderReport(await api("/api/runs/" + job.report_id));
        await history(); $("status").textContent = "Проверка завершена"; break;
      }
      if (job.status === "cancelled") { $("status").textContent = "Запуск остановлен"; break; }
      if (job.status === "failed") throw new Error("Запуск завершился ошибкой: " + job.error);
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
  } catch (e) { error(e.message); $("status").textContent = "Проверьте соединение с сервисом"; }
  finally { working = false; jobId = null; $("run").disabled = false; $("cancel").hidden = true; }
}
$("run-form").addEventListener("submit", async (event) => {
  event.preventDefault(); if (working) return;
  $("error").hidden = true; $("run").disabled = true;
  try {
    const job = await api("/api/jobs", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({provider:$("provider").value, prompt:$("prompt").value, repetitions:Number($("repetitions").value)})});
    await followJob(job.id);
  } catch (e) { error(e.message); $("run").disabled = false; }
});
$("cancel").addEventListener("click", async () => {
  if (!jobId) return;
  try { await api("/api/jobs/" + jobId + "/cancel", {method:"POST"}); } catch (e) { error(e.message); }
});
$("compare-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if ($("baseline").value === $("candidate").value) { $("comparison").textContent = "Выберите два разных запуска."; return; }
  try {
    const data = await api("/api/compare?baseline=" + encodeURIComponent($("baseline").value) + "&candidate=" + encodeURIComponent($("candidate").value));
    $("comparison").textContent = "Изменение доли пройденных проверок: " + (data.pass_rate_delta * 100).toFixed(1) + " п.п.\nУхудшения: " + (data.regressions.join(", ") || "нет") + "\nУлучшения: " + (data.improvements.join(", ") || "нет") + "\nЭто наблюдение по выбранным запускам, а не проверка статистической значимости.";
  } catch (e) { $("comparison").textContent = e.message; }
});
$("failed-only").addEventListener("change", renderCases);
$("provider").addEventListener("change", providerNote);
async function initialize() {
  try {
    const config = await api("/api/config"); localModel = config.local_model;
    $("provider").querySelector('option[value="local"]').disabled = !localModel;
    $("case-count").textContent = config.cases + " задания";
    const runs = await history();
    if (runs.length) renderReport(await api("/api/runs/" + runs[0].id));
    if (config.active_job?.status === "running") await followJob(config.active_job.id);
  } catch (e) { error(e.message); }
}
initialize();
