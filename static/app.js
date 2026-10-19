const log = document.querySelector("#log");
const thread = document.createElement("div");
thread.className = "thread";
log.appendChild(thread);

const form = document.querySelector("#composer");
const messageBox = document.querySelector("#message");
const fileInput = document.querySelector("#file");
const fileChip = document.querySelector("#file-chip");
const sendButton = document.querySelector("#send");
const datasetEl = document.querySelector("#dataset");
const profileBlock = document.querySelector("#profile-block");
const profileEl = document.querySelector("#profile");
const filterBlock = document.querySelector("#filter-block");
const filtersEl = document.querySelector("#filters");
const appliedEl = document.querySelector("#applied");
const appliedEmpty = document.querySelector("#applied-empty");

const SESSION_KEY = "job-chat-session";
let sessionId = localStorage.getItem(SESSION_KEY) || "";
let busy = false;
let suggestionRow = null;

boot();

async function boot() {
  try {
    const health = await fetch("/api/health").then((res) => res.json());
    if (health.ok) {
      const bits = Object.entries(health.sources || []).map(([name, count]) => `${count} ${name}`);
      datasetEl.textContent = `${health.jobs.toLocaleString()} roles loaded` + (bits.length ? ` · ${bits.join(", ")}` : "");
    } else {
      datasetEl.textContent = health.error || "Dataset isn't loaded.";
    }
  } catch {
    datasetEl.textContent = "Couldn't reach the server.";
  }

  if (sessionId) {
    const res = await fetch(`/api/session/${sessionId}`);
    if (res.ok) {
      const data = await res.json();
      renderProfile(data.profile);
      renderFilters(data.filters);
      renderApplied(data.applications || []);
      for (const message of data.messages || []) {
        appendBubble(message.role, message.text, message);
      }
    } else {
      sessionId = "";
      localStorage.removeItem(SESSION_KEY);
    }
  }
  if (!thread.children.length) {
    appendBubble("assistant", introText(), { suggestions: ["What can you do?"] });
  }
  scrollDown();
}

function introText() {
  return [
    "Hey. Send a PDF or DOCX resume and I'll read it back to you — name, contact, designation, skills, experience, education, and projects.",
    "",
    "After that, talk normally. \"Show only remote roles\", \"jobs needing React\", \"apply to job 3\", \"show my applied jobs\".",
  ].join("\n");
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = messageBox.value.trim();
  const file = fileInput.files[0];
  if (!text && !file) return;
  send(text, file);
});

messageBox.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

fileInput.addEventListener("change", () => {
  const file = fileInput.files[0];
  if (!file) {
    fileChip.hidden = true;
    fileChip.innerHTML = "";
    return;
  }
  fileChip.hidden = false;
  fileChip.innerHTML = "";
  const name = document.createElement("span");
  name.textContent = file.name;
  const clear = document.createElement("button");
  clear.type = "button";
  clear.textContent = "Remove";
  clear.addEventListener("click", () => {
    fileInput.value = "";
    fileChip.hidden = true;
    fileChip.innerHTML = "";
  });
  fileChip.append(name, clear);
});

log.addEventListener("dragover", (event) => {
  event.preventDefault();
  log.classList.add("drag");
});
log.addEventListener("dragleave", () => log.classList.remove("drag"));
log.addEventListener("drop", (event) => {
  event.preventDefault();
  log.classList.remove("drag");
  const file = event.dataTransfer.files && event.dataTransfer.files[0];
  if (!file) return;
  const transfer = new DataTransfer();
  transfer.items.add(file);
  fileInput.files = transfer.files;
  fileInput.dispatchEvent(new Event("change"));
});

document.querySelector("#new-chat").addEventListener("click", () => {
  sessionId = "";
  localStorage.removeItem(SESSION_KEY);
  thread.innerHTML = "";
  suggestionRow = null;
  renderProfile(null);
  renderFilters(null);
  renderApplied([]);
  appendBubble("assistant", introText(), { suggestions: ["What can you do?"] });
});

async function send(text, file) {
  if (busy) return;
  const chosen = file || fileInput.files[0] || null;
  const userText = chosen
    ? (text ? `Uploaded ${chosen.name}\n${text}` : `Uploaded ${chosen.name}`)
    : text;
  if (!userText) return;

  clearSuggestions();
  appendBubble("user", userText);
  messageBox.value = "";
  fileInput.value = "";
  fileChip.hidden = true;
  fileChip.innerHTML = "";
  const typing = showTyping();
  busy = true;
  sendButton.disabled = true;

  const body = new FormData();
  body.append("session_id", sessionId);
  body.append("message", text || "");
  if (chosen) body.append("file", chosen);

  try {
    const res = await fetch("/api/chat", { method: "POST", body });
    const data = await res.json();
    typing.remove();
    if (data.session_id) {
      sessionId = data.session_id;
      localStorage.setItem(SESSION_KEY, sessionId);
    }
    appendBubble("assistant", data.reply || "I didn't get a reply.", data);
    renderProfile(data.profile);
    renderFilters(data.filters);
    renderApplied(data.saved_applications || []);
  } catch {
    typing.remove();
    appendBubble("assistant", "I couldn't reach the server. Try that once more.");
  } finally {
    busy = false;
    sendButton.disabled = false;
    messageBox.focus();
  }
}

function appendBubble(role, text, extra = {}) {
  const bubble = document.createElement("article");
  bubble.className = `bubble ${role}`;
  const meta = document.createElement("div");
  meta.className = "meta";
  const who = document.createElement("span");
  who.textContent = role === "user" ? "You" : "Assistant";
  meta.append(who);
  if (extra.activity && extra.activity.length && role === "assistant") {
    const activity = document.createElement("span");
    activity.className = "activity";
    activity.textContent = extra.activity.join(" · ");
    meta.append(activity);
  }
  bubble.append(meta);

  const body = document.createElement("div");
  body.className = "reply";
  body.innerHTML = formatText(text || "");
  bubble.append(body);

  if (extra.jobs && extra.jobs.length) {
    bubble.append(renderCards(extra.jobs));
  }
  if (extra.applications && extra.applications.length) {
    bubble.append(renderAppList(extra.applications));
  }
  if (extra.suggestions && extra.suggestions.length) {
    clearSuggestions();
    suggestionRow = renderSuggestions(extra.suggestions);
    bubble.append(suggestionRow);
  }
  thread.append(bubble);
  scrollDown();
}

function renderCards(jobs) {
  const wrap = document.createElement("div");
  wrap.className = "cards";
  for (const job of jobs) {
    const card = document.createElement("article");
    card.className = "card";

    const top = document.createElement("div");
    top.className = "card-top";
    const rank = document.createElement("span");
    rank.className = "rank";
    rank.textContent = job.rank || "·";
    const titles = document.createElement("div");
    const heading = document.createElement("h3");
    heading.textContent = job.title || "Untitled role";
    const company = document.createElement("p");
    company.className = "company";
    company.textContent = job.company || "";
    titles.append(heading, company);
    top.append(rank, titles);
    if (typeof job.score === "number") {
      const score = document.createElement("span");
      score.className = "score";
      score.textContent = `${job.score}%`;
      top.append(score);
    }
    card.append(top);

    const facts = document.createElement("div");
    facts.className = "facts";
    addPill(facts, job.location);
    if (job.remote) addPill(facts, "Remote", "remote");
    addPill(facts, job.experience_required);
    const skills = (job.skills || []).slice(0, 5).map(labelSkill);
    if (skills.length) addPill(facts, skills.join(", "));
    card.append(facts);

    if (job.reason) {
      const reason = document.createElement("p");
      reason.className = "reason";
      reason.textContent = job.reason;
      card.append(reason);
    }
    if (job.preview) {
      const preview = document.createElement("p");
      preview.className = "preview";
      preview.textContent = job.preview;
      card.append(preview);
    }

    const actions = document.createElement("div");
    actions.className = "card-actions";
    if (job.rank) {
      const apply = document.createElement("button");
      apply.type = "button";
      apply.className = "texty";
      apply.textContent = `Apply to job ${job.rank}`;
      // The button just types the sentence. Applying still goes through the chat.
      apply.addEventListener("click", () => send(`Apply to job ${job.rank}`));
      actions.append(apply);
    }
    if (job.source_link) {
      const link = document.createElement("a");
      link.href = job.source_link;
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = job.source ? `View on ${job.source}` : "View posting";
      actions.append(link);
    }
    card.append(actions);
    wrap.append(card);
  }
  return wrap;
}

function renderAppList(rows) {
  const list = document.createElement("ul");
  list.className = "apps";
  for (const row of rows) {
    const item = document.createElement("li");
    const title = document.createElement("strong");
    title.textContent = `${row.job_title || "Role"} · ${row.company || ""}`;
    const detail = document.createElement("div");
    detail.textContent = `${formatDay(row.applied_date)} · ${row.status || "applied"} · ${row.job_id || ""}`;
    item.append(title, detail);
    list.append(item);
  }
  return list;
}

function renderSuggestions(items) {
  const row = document.createElement("div");
  row.className = "suggestions";
  for (const item of items) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = item;
    button.addEventListener("click", () => send(item));
    row.append(button);
  }
  return row;
}

function clearSuggestions() {
  if (suggestionRow) suggestionRow.remove();
  suggestionRow = null;
}

function renderProfile(profile) {
  profileEl.innerHTML = "";
  if (!profile) {
    profileBlock.hidden = true;
    return;
  }
  profileBlock.hidden = false;
  const rows = [
    ["Name", profile.name],
    ["Contact", [profile.email, profile.phone, ...(profile.links || [])].filter(Boolean).join(" · ")],
    ["Designation", profile.designation],
    ["Experience", yearsText(profile)],
    ["Skills", (profile.skills || []).slice(0, 12).map(labelSkill).join(", ")],
    ["Education", (profile.education || []).join("; ")],
    ["Projects", (profile.projects || []).join("; ")],
  ];
  for (const [label, value] of rows) {
    const line = document.createElement("p");
    const name = document.createElement("span");
    name.className = "label";
    name.textContent = `${label}: `;
    line.append(name, document.createTextNode(value || "Not found"));
    profileEl.append(line);
  }
}

function renderFilters(filters) {
  if (!filters) {
    filterBlock.hidden = true;
    return;
  }
  const bits = [];
  if (filters.remote === true) bits.push("Remote only");
  if (filters.remote === false) bits.push("On-site only");
  if (filters.skills && filters.skills.length) bits.push(filters.skills.map(labelSkill).join(", "));
  if (filters.location) bits.push(filters.location);
  if (filters.level) bits.push(filters.level);
  filterBlock.hidden = bits.length === 0;
  filtersEl.textContent = bits.join(" · ");
}

function renderApplied(rows) {
  appliedEl.innerHTML = "";
  appliedEmpty.hidden = rows.length > 0;
  for (const row of rows) {
    const item = document.createElement("li");
    const title = document.createElement("div");
    title.textContent = `${row.job_title || "Role"} · ${row.company || ""}`;
    const detail = document.createElement("div");
    detail.className = "status";
    detail.textContent = `${row.status || "applied"} · ${formatDay(row.applied_date)}`;
    item.append(title, detail);
    appliedEl.append(item);
  }
}

function showTyping() {
  const bubble = document.createElement("article");
  bubble.className = "bubble assistant";
  bubble.innerHTML = '<div class="typing" aria-label="Assistant is writing"><i></i><i></i><i></i></div>';
  thread.append(bubble);
  scrollDown();
  return bubble;
}

function addPill(parent, text, className) {
  if (!text) return;
  const pill = document.createElement("span");
  pill.className = "pill" + (className ? ` ${className}` : "");
  pill.textContent = text;
  parent.append(pill);
}

function formatText(text) {
  let html = escapeHtml(text);
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html.replace(/https?:\/\/[^\s<]+/g, (url) => {
    const clean = url.replace(/[).,]+$/, "");
    const tail = url.slice(clean.length);
    return `<a href="${clean}" target="_blank" rel="noopener">${clean}</a>${tail}`;
  });
  return html.replace(/\n/g, "<br>");
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function labelSkill(name) {
  if (!name) return "";
  const key = String(name).toLowerCase();
  const known = {
    javascript: "JavaScript",
    typescript: "TypeScript",
    "node.js": "Node.js",
    postgresql: "PostgreSQL",
    mysql: "MySQL",
    mongodb: "MongoDB",
    graphql: "GraphQL",
    aws: "AWS",
    gcp: "GCP",
    css: "CSS",
    html: "HTML",
    sql: "SQL",
    php: "PHP",
    ios: "iOS",
    "c++": "C++",
    "c#": "C#",
    ".net": ".NET",
    go: "Go",
    nlp: "NLP",
    llm: "LLM",
    "ui/ux": "UI/UX",
    "ci/cd": "CI/CD",
    rest: "REST",
    grpc: "gRPC",
    "next.js": "Next.js",
    dynamodb: "DynamoDB",
    "react native": "React Native",
    "machine learning": "Machine Learning",
    "github actions": "GitHub Actions",
    "power bi": "Power BI",
  };
  if (known[key]) return known[key];
  if (name !== key) return name;
  return name.replace(/(^|[\s/])(\w)/g, (_, gap, letter) => gap + letter.toUpperCase());
}

function yearsText(profile) {
  const roles = (profile.experience || []).map((role) => {
    let bit = role.title || "Role";
    if (role.company) bit += ` at ${role.company}`;
    if (role.dates) bit += ` (${role.dates})`;
    return bit;
  });
  const years = profile.years;
  const yearBit = typeof years === "number" ? `about ${years} ${years === 1 ? "year" : "years"}` : "";
  if (yearBit && roles.length) return `${yearBit} — ${roles.join("; ")}`;
  return yearBit || roles.join("; ");
}

function formatDay(iso) {
  if (!iso) return "";
  const [year, month, day] = iso.split("-").map(Number);
  if (!year || !month || !day) return iso;
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
}

function scrollDown() {
  log.scrollTop = log.scrollHeight;
}
