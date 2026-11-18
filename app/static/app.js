"use strict";
const $ = (id) => document.getElementById(id);
const node = (tag, text, cls) => {
  const n = document.createElement(tag);
  if (text !== undefined) n.textContent = text;
  if (cls) n.className = cls;
  return n;
};
async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(path, {
      ...options,
      headers: { "Content-Type": "application/json", ...options.headers },
    });
  } catch {
    throw {
      message: "Сеть недоступна. Проверьте состояние перед повторной записью.",
      network: true,
    };
  }
  let data;
  try {
    data = await response.json();
  } catch {
    throw { message: "Сервер вернул неожиданный ответ.", network: true };
  }
  if (!response.ok) throw { ...data, status: response.status };
  return data;
}
function message(target, error) {
  target.className = "error";
  target.textContent = error.message || "Не удалось выполнить запрос.";
  if (error.field_errors)
    target.textContent +=
      " " +
      Object.entries(error.field_errors)
        .map(
          ([k, v]) =>
            `${{ name: "Название", country_code: "Страна", offer_id: "Оффер", domain_id: "Домен", group_id: "Группа", traffic_source_id: "Источник" }[k] || k}: ${v}`,
        )
        .join("; ");
  if (error.operation_id)
    target.textContent += ` Операция: ${error.operation_id}.`;
  if (error.campaign_id)
    target.textContent += ` Кампания: ${error.campaign_id}.`;
}
function picker(host, id, endpoint, onSelect, unavailable = []) {
  host.classList.add("picker");
  const input = node("input");
  input.id = id;
  input.autocomplete = "off";
  input.setAttribute("role", "combobox");
  input.setAttribute("aria-autocomplete", "list");
  input.setAttribute("aria-expanded", "false");
  input.setAttribute("aria-controls", id + "-results");
  const list = node("ul", undefined, "results");
  list.id = id + "-results";
  list.setAttribute("role", "listbox");
  list.hidden = true;
  const status = node("p", "", "picker-status");
  status.setAttribute("role", "status");
  const retry = node("button", "Повторить поиск", "secondary");
  retry.type = "button";
  retry.hidden = true;
  host.append(input, list, status, retry);
  let seq = 0,
    timer,
    rows = [],
    cursor = -1;
  function close() {
    seq++;
    list.hidden = true;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
  }
  function choose(index) {
    const row = rows[index];
    if (!row || unavailable.includes(row.id)) return;
    input.value = `${row.id} · ${row.name}`;
    close();
    status.textContent = "Выбрано";
    onSelect(row);
  }
  async function search() {
    const current = ++seq;
    status.textContent = "Поиск…";
    retry.hidden = true;
    try {
      const data = await api(
        endpoint + "?q=" + encodeURIComponent(input.value),
      );
      if (current !== seq) return;
      rows = data.items;
      cursor = -1;
      list.replaceChildren();
      rows.forEach((row, i) => {
        const li = node(
          "li",
          `${row.id} · ${row.name}${unavailable.includes(row.id) ? " — Уже в потоке" : ""}`,
        );
        li.id = `${id}-option-${i}`;
        li.setAttribute("role", "option");
        li.setAttribute("aria-selected", "false");
        li.setAttribute("aria-disabled", String(unavailable.includes(row.id)));
        li.addEventListener("mousedown", (e) => e.preventDefault());
        li.addEventListener("click", () => choose(i));
        list.append(li);
      });
      list.hidden = !rows.length;
      input.setAttribute("aria-expanded", String(!!rows.length));
      status.textContent = rows.length
        ? `Найдено: ${rows.length}. Выберите результат.`
        : "Ничего не найдено";
    } catch (e) {
      if (current !== seq) return;
      status.textContent = e.message;
      retry.hidden = false;
      list.hidden = true;
      input.setAttribute("aria-expanded", "false");
    }
  }
  input.addEventListener("input", () => {
    close();
    rows = [];
    cursor = -1;
    list.replaceChildren();
    status.textContent = "Поиск…";
    onSelect(null);
    clearTimeout(timer);
    timer = setTimeout(search, 200);
  });
  input.addEventListener("focus", () => {
    if (!input.value) search();
  });
  input.addEventListener("blur", close);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      close();
      return;
    }
    if (list.hidden) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      cursor =
        (cursor + (e.key === "ArrowDown" ? 1 : -1) + rows.length) % rows.length;
      [...list.children].forEach((li, i) =>
        li.setAttribute("aria-selected", String(i === cursor)),
      );
      input.setAttribute("aria-activedescendant", list.children[cursor].id);
      list.children[cursor].scrollIntoView({ block: "nearest" });
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (cursor >= 0) choose(cursor);
    }
  });
  retry.addEventListener("click", search);
  return {
    input,
    set(row) {
      input.value = `${row.id} · ${row.name}`;
      onSelect(row);
    },
  };
}
let country = null,
  offer = null,
  busy = false,
  saved = null;
try {
  saved = JSON.parse(sessionStorage.getItem("creation-attempt"));
  if (!saved?.payload || !saved?.key) saved = null;
} catch {
  saved = null;
}
const countryPicker = picker(
  $("country-picker"),
  "country",
  "/api/countries",
  (row) => {
    country = row;
    validate();
  },
);
const offerPicker = picker($("offer-picker"), "offer", "/api/offers", (row) => {
  offer = row;
  validate();
});
picker($("campaign-picker"), "campaign-query", "/api/campaigns", (row) => {
  if (row) location.href = `/campaigns/${row.id}/edit`;
});
function validate() {
  $("route-country").textContent =
    `${country?.name || "Выберите страну"} → Google`;
  $("route-offer").textContent =
    `Все остальные → ${offer ? `${offer.name} (${offer.id})` : "Выберите оффер"}`;
  $("create-button").disabled =
    busy ||
    !!saved ||
    !country ||
    !offer ||
    !$("name").value.trim() ||
    !["domain_id", "group_id", "traffic_source_id"].every((id) => $(id).value);
}
function freezeAttempt() {
  $("create-form")
    .querySelectorAll("input,select")
    .forEach((n) => (n.disabled = busy || !!saved));
  $("resume-button").hidden = !saved;
  $("resume-button").disabled = busy;
  validate();
}
$("create-form").addEventListener("input", validate);
$("create-form").addEventListener("change", validate);
async function loadConfig() {
  $("config-error").textContent = "";
  $("retry-config").hidden = true;
  try {
    const config = await api("/api/configuration");
    for (const [field, group] of [
      ["domain_id", "domains"],
      ["group_id", "groups"],
      ["traffic_source_id", "sources"],
    ]) {
      const select = $(field);
      select.replaceChildren(new Option("Выберите значение", ""));
      config[group].forEach((row) =>
        select.add(new Option(`${row.id} · ${row.name}`, row.id)),
      );
      select.value = saved?.payload[field] || config.defaults[field] || "";
    }
    validate();
  } catch (e) {
    message($("config-error"), e);
    $("retry-config").hidden = false;
  }
}
$("retry-config").addEventListener("click", loadConfig);
if (saved) {
  $("name").value = saved.payload.name;
  countryPicker.set(
    saved.country || {
      id: saved.payload.country_code,
      name: saved.payload.country_code,
    },
  );
  offerPicker.set(saved.offer || { id: saved.payload.offer_id, name: "" });
  $("create-message").textContent =
    "Восстановлена незавершённая попытка. Нажмите «Проверить и продолжить».";
  freezeAttempt();
}
async function createCampaign() {
  if (busy) return;
  if (!saved) {
    const payload = {
      name: $("name").value.trim(),
      country_code: country.id,
      offer_id: offer.id,
    };
    ["domain_id", "group_id", "traffic_source_id"].forEach(
      (id) => (payload[id] = Number($(id).value)),
    );
    saved = { payload, key: crypto.randomUUID(), country, offer };
    try {
      sessionStorage.setItem("creation-attempt", JSON.stringify(saved));
    } catch {
      saved = null;
      message($("create-message"), {
        message:
          "Разрешите sessionStorage для безопасного восстановления операции.",
      });
      return;
    }
  }
  busy = true;
  freezeAttempt();
  $("create-button").textContent = "Создаём…";
  $("create-message").textContent = "";
  try {
    const result = await api("/api/campaigns", {
      method: "POST",
      headers: { "Idempotency-Key": saved.key },
      body: JSON.stringify(saved.payload),
    });
    sessionStorage.removeItem("creation-attempt");
    saved = null;
    location.href = `/campaigns/${result.campaign_id}/edit`;
  } catch (e) {
    message($("create-message"), e);
    // Validation happens before external writes. Allow correcting input with a new key.
    if (e.status === 422 && (!e.stage || e.stage === "pending")) {
      sessionStorage.removeItem("creation-attempt");
      saved = null;
    }
  } finally {
    busy = false;
    $("create-button").textContent = "Создать кампанию";
    freezeAttempt();
  }
}
$("create-form").addEventListener("submit", (e) => {
  e.preventDefault();
  createCampaign();
});
$("resume-button").addEventListener("click", createCampaign);
$("open-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const id = Number($("campaign-id").value);
  if (Number.isInteger(id) && id > 0) location.href = `/campaigns/${id}/edit`;
});
const cid = Number(document.body.dataset.campaignId);
let editorVersion = 0;
let writing = false;
async function loadCampaign() {
  if (writing) return;
  const version = ++editorVersion;
  $("editor-message").textContent = "Загрузка…";
  try {
    const data = await api(`/api/campaigns/${cid}`);
    if (version !== editorVersion) return;
    renderCampaign(data);
    $("editor-message").textContent = "Данные обновлены";
    $("editor-message").className = "success";
  } catch (e) {
    if (version === editorVersion) message($("editor-message"), e);
  }
}
$("refresh").addEventListener("click", loadCampaign);
function renderCampaign(data, focusId) {
  $("campaign-title").textContent = `${data.name} · ${data.id}`;
  $("campaign-meta").replaceChildren();
  for (const [label, key] of [
    ["Домен", "domain"],
    ["Группа", "group"],
    ["Источник", "traffic_source"],
  ])
    $("campaign-meta").append(
      node("span", `${label}: ${data[key].name || data[key].id || "Не задан"}`),
    );
  $("campaign-meta").append(
    node(
      "span",
      data.rotation === "position"
        ? "Ротация по позиции"
        : `Ротация: ${data.rotation}. Порядок карточек не задаёт обход.`,
    ),
  );
  $("streams").replaceChildren();
  if (!data.streams.length)
    $("streams").append(node("p", "В кампании пока нет потоков."));
  for (const stream of data.streams) {
    const card = node("article", undefined, "stream");
    card.id = `stream-${stream.id}`;
    const head = node("div", undefined, "stream-head");
    head.append(
      node("h2", `${stream.name || "Поток"} · ${stream.id}`),
      node("span", `${stream.type} · позиция ${stream.position}`, "badge"),
    );
    card.append(head);
    card.append(node("p", stream.filters_summary));
    if (stream.state !== "active")
      card.append(node("p", `Выключен / состояние: ${stream.state}`, "notice"));
    if (data.rotation !== "position")
      card.append(node("p", `Вес потока: ${stream.weight ?? "—"}`));
    card.append(node("p", `Назначение: ${stream.destination_label}`));
    const status = node("p");
    status.setAttribute("role", "status");
    if (stream.offers.length) {
      const table = node("table", undefined, "offers");
      const thead = node("thead");
      const hr = node("tr");
      ["Оффер", "Состояние", "Доля внутри потока", "Действие"].forEach((t) =>
        hr.append(node("th", t)),
      );
      thead.append(hr);
      table.append(thead);
      const tbody = node("tbody");
      for (const row of stream.offers) {
        const tr = node("tr");
        tr.append(node("td", `${row.id} · ${row.name}`));
        const state = node(
          "td",
          row.state === "active" ? "Активен" : String(row.state),
        );
        state.dataset.label = "Состояние";
        const share = node("td", `${row.share ?? "—"}%`, "share");
        share.dataset.label = "Доля";
        tr.append(state, share);
        const action = node("td");
        if (stream.editable) {
          const remove = node("button", "Убрать из потока", "danger");
          remove.disabled = stream.offers.length === 1;
          remove.addEventListener("click", () =>
            mutate(stream, row.id, true, card, status),
          );
          action.append(remove);
        }
        tr.append(action);
        tbody.append(tr);
      }
      table.append(tbody);
      card.append(table);
      if (stream.editable)
        card.append(
          node(
            "p",
            `Сумма долей: ${stream.offers.reduce((sum, o) => sum + Number(o.share), 0)}%`,
            "muted",
          ),
        );
    }
    if (stream.editable) {
      if (stream.offers.length === 1)
        card.append(
          node(
            "p",
            "Последний активный оффер нельзя убрать по временному правилу.",
            "muted",
          ),
        );
      const toggle = node("button", "Добавить оффер", "secondary");
      toggle.id = `add-${stream.id}`;
      const form = node("div", undefined, "add-form");
      form.hidden = true;
      const label = node("label", "Найти оффер по ID или названию");
      label.htmlFor = `offer-${stream.id}`;
      const host = node("div");
      const add = node("button", "Добавить");
      add.disabled = true;
      let selected = null;
      form.append(label, host);
      const control = picker(
        host,
        `offer-${stream.id}`,
        "/api/offers",
        (row) => {
          selected = row;
          add.disabled = !row;
        },
        stream.offers.map((o) => o.id),
      );
      add.addEventListener("click", () => {
        if (selected) mutate(stream, selected.id, false, card, status);
      });
      form.append(add);
      toggle.addEventListener("click", () => {
        form.hidden = !form.hidden;
        if (!form.hidden) control.input.focus();
      });
      card.append(toggle, form);
    } else card.append(node("p", stream.readonly_reason, "muted"));
    card.append(status);
    $("streams").append(card);
  }
  if (focusId) $(focusId)?.focus();
}
async function mutate(stream, oid, remove, card, status) {
  if (writing) return;
  writing = true;
  $("refresh").disabled = true;
  const version = ++editorVersion;
  card.querySelectorAll("button,input").forEach((n) => (n.disabled = true));
  status.textContent = "Сохраняем…";
  const url = `/api/campaigns/${cid}/streams/${stream.id}/offers`;
  try {
    const data = await api(
      remove ? `${url}/${oid}` : url,
      remove
        ? { method: "DELETE", headers: { "If-Match": `"${stream.revision}"` } }
        : {
            method: "POST",
            body: JSON.stringify({ offer_id: oid, revision: stream.revision }),
          },
    );
    if (version !== editorVersion) return;
    renderCampaign(data, `add-${stream.id}`);
    $("editor-message").className = "success";
    $("editor-message").textContent = "Изменения подтверждены Keitaro.";
  } catch (e) {
    if (version !== editorVersion) return;
    message(status, e);
    const check = node(
      "button",
      e.status === 409 ? "Обновить" : "Проверить состояние",
      "secondary",
    );
    check.addEventListener("click", loadCampaign);
    status.append(document.createTextNode(" "), check);
    check.focus();
  } finally {
    writing = false;
    $("refresh").disabled = false;
  }
}
loadConfig();
if (cid) loadCampaign();
