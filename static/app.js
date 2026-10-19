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
const side = document.querySelector("#side");
const topNote = document.querySelector("#top-note");
const dropHint = document.querySelector("#drop-hint");
const statRoles = document.querySelector("#stat-roles");
const statBoards = document.querySelector("#stat-boards");
const statBoardNames = document.querySelector("#stat-board-names");
const statSaved = document.querySelector("#stat-saved");

const SESSION_KEY = "job-chat-session";
const MONO = ["#1f6f54", "#8a4b2f", "#2f4f6f", "#6f3d55", "#3f5b3a", "#6a5428"];

let sessionId = localStorage.getItem(SESSION_KEY) || "";
let busy = false;
let suggestionRow = null;
// job id -> saved row, so a card can show "Applied" after a later turn or a refresh
let appliedById = new Map();

boot();

async function boot() {
  try {
    const health = await fetch("/api/health").then((res) => res.json());
    if (health.ok) {
      const bits = Object.entries(health.sources || {}).map(([name, count]) => `${count} ${name}`);
      datasetEl.textContent = `${health.jobs.toLocaleString()} live roles` + (bits.length ? ` · ${bits.join(", ")}` : "");
      if (statRoles) statRoles.textContent = health.jobs.toLocaleString();
      const sourceCount = Object.keys(health.sources || {}).length;
      if (statBoards) statBoards.textContent = String(sourceCount || "—");
      if (statBoardNames) statBoardNames.textContent = bits.join(" · ") || "Greenhouse, Lever, Ashby";
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
  if (!thread.querySelector(".bubble")) showWelcome();
  scrollDown();
}

function showWelcome() {
  const panel = document.createElement("section");
  panel.className = "welcome";
  panel.innerHTML = `
    <h2>Send a resume. I'll take it from there.</h2>
    <p class="lead">This is a conversation, not a form. After I read the file, ask for remote roles, a skill, or a specific card.</p>
    <ol class="steps">
      <li><span class="step-no">1</span><strong>Read the resume</strong><span>PDF or DOCX. I show the name, contact, title, skills, experience, education, and projects.</span></li>
      <li><span class="step-no">2</span><strong>Match the dataset</strong><span>Each card has a reason: shared skills, title, and whether the years fit.</span></li>
      <li><span class="step-no">3</span><strong>Open the real posting</strong><span>The company form uses a captcha, so the chat keeps the live link. It does not mark you as submitted.</span></li>
    </ol>
  `;
  const upload = document.createElement("button");
  upload.type = "button";
  upload.className = "upload-btn";
  upload.textContent = "Upload resume";
  upload.addEventListener("click", openResumePicker);
  const prompts = renderSuggestions(["What can you do?"]);
  panel.append(upload, prompts);
  suggestionRow = prompts;
  thread.append(panel);
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

messageBox.addEventListener("input", () => {
  messageBox.style.height = "auto";
  messageBox.style.height = Math.min(messageBox.scrollHeight, 140) + "px";
});

function openResumePicker() {
  fileInput.click();
}

document.querySelector("#upload-resume").addEventListener("click", openResumePicker);
document.querySelector("#upload-inline").addEventListener("click", openResumePicker);

fileInput.addEventListener("change", () => {
  const file = fileInput.files[0];
  if (!file) return;
  const note = messageBox.value.trim();
  send(note, file);
});

for (const target of [log, form]) {
  target.addEventListener("dragover", (event) => {
    event.preventDefault();
    dropHint.hidden = false;
  });
  target.addEventListener("dragleave", (event) => {
    if (event.currentTarget.contains(event.relatedTarget)) return;
    dropHint.hidden = true;
  });
  target.addEventListener("drop", (event) => {
    event.preventDefault();
    dropHint.hidden = true;
    const file = event.dataTransfer.files && event.dataTransfer.files[0];
    if (!file) return;
    const transfer = new DataTransfer();
    transfer.items.add(file);
    fileInput.files = transfer.files;
    fileInput.dispatchEvent(new Event("change"));
  });
}

document.querySelector("#new-chat").addEventListener("click", () => {
  sessionId = "";
  localStorage.removeItem(SESSION_KEY);
  thread.replaceChildren();
  suggestionRow = null;
  appliedById = new Map();
  renderProfile(null);
  renderFilters(null);
  renderApplied([]);
  showWelcome();
  side.classList.remove("open");
});

document.querySelector("#panel-toggle").addEventListener("click", () => {
  side.classList.toggle("open");
});

async function send(text, file) {
  if (busy) return;
  const chosen = file || fileInput.files[0] || null;
  const userText = chosen
    ? (text ? `Uploaded ${chosen.name}\n${text}` : `Uploaded ${chosen.name}`)
    : text;
  if (!userText) return;

  thread.querySelector(".welcome")?.remove();
  clearSuggestions();
  appendBubble("user", userText);
  messageBox.value = "";
  messageBox.style.height = "auto";
  fileInput.value = "";
  fileChip.hidden = true;
  fileChip.replaceChildren();
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
    if (data.profile && data.profile.name) {
      topNote.textContent = `Matching for ${data.profile.name}.`;
    }
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

  if (role === "user") {
    const meta = document.createElement("div");
    meta.className = "who-line";
    meta.textContent = "You";
    const body = document.createElement("div");
    // The id in parentheses is for the agent. The person just needs the role name.
    body.textContent = String(text || "").replace(/\s+\((?:gh|lv|ab)_[^)]+\)$/i, "");
    bubble.append(meta, body);
  } else {
    const card = document.createElement("div");
    card.className = "reply-card";
    const meta = document.createElement("div");
    meta.className = "who-line";
    const who = document.createElement("span");
    who.textContent = "Assistant";
    meta.append(who);
    if (extra.activity && extra.activity.length) {
      const activity = document.createElement("span");
      activity.className = "activity";
      activity.textContent = extra.activity.join(" · ");
      meta.append(activity);
    }
    const body = document.createElement("div");
    body.className = "reply";
    body.innerHTML = formatText(text || "");
    card.append(meta, body);
    if (extra.jobs && extra.jobs.length) card.append(renderCards(extra.jobs));
    if (extra.applications && extra.applications.length) card.append(renderReceipts(extra.applications));
    if (extra.suggestions && extra.suggestions.length) {
      clearSuggestions();
      suggestionRow = renderSuggestions(extra.suggestions);
      card.append(suggestionRow);
    }
    bubble.append(card);
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
    card.dataset.jobId = job.id || "";
    card._job = job;

    const top = document.createElement("div");
    top.className = "card-top";
    const mono = document.createElement("span");
    mono.className = "mono";
    mono.style.background = MONO[hashName(job.company) % MONO.length];
    mono.textContent = initials(job.company);
    const titles = document.createElement("div");
    const heading = document.createElement("h3");
    heading.textContent = job.title || "Untitled role";
    const company = document.createElement("p");
    company.className = "company";
    company.textContent = [job.rank ? `Job ${job.rank}` : "", job.company || ""].filter(Boolean).join(" · ");
    titles.append(heading, company);
    top.append(mono, titles);
    if (typeof job.score === "number") {
      const meter = document.createElement("div");
      meter.className = "meter";
      meter.style.setProperty("--p", String(Math.max(0, Math.min(100, job.score))));
      meter.title = "Match score";
      const value = document.createElement("span");
      value.textContent = String(job.score);
      meter.append(value);
      top.append(meter);
    }
    card.append(top);

    const facts = document.createElement("div");
    facts.className = "facts";
    addPill(facts, job.location);
    if (job.remote) addPill(facts, "Remote", "remote");
    addPill(facts, job.experience_required);
    for (const skill of (job.skills || []).slice(0, 5)) addPill(facts, labelSkill(skill), "skill");
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
    card.append(actions);
    paintApplyState(card, appliedById.get(job.id), job);
    wrap.append(card);
  }
  return wrap;
}

function paintApplyState(card, saved, job) {
  const actions = card.querySelector(".card-actions");
  if (!actions) return;
  actions.replaceChildren();
  const posting = job || {};
  const rank = posting.rank;
  if (saved) {
    card.classList.add("is-applied");
    const pill = document.createElement("span");
    pill.className = "saved-pill";
    const label = saved.status === "not_submitted" ? "Not submitted" : "Applied";
    pill.textContent = `${label} · ${formatDay(saved.applied_date)}`;
    actions.append(pill);
  } else if (rank) {
    card.classList.remove("is-applied");
    const apply = document.createElement("button");
    apply.type = "button";
    apply.className = "apply";
    apply.textContent = "Apply";
    // Rank numbers belong to the latest list, so an older card sends its own id.
    // The orchestrator still writes the row; the button does not call the API itself.
    apply.addEventListener("click", () => {
      const label = posting.title ? `${posting.title}` : `job ${rank}`;
      send(posting.id ? `Apply to ${label} (${posting.id})` : `Apply to job ${rank}`);
    });
    actions.append(apply);
  }
  const linkHref = (saved && saved.source_link) || posting.source_link;
  if (linkHref) {
    const link = document.createElement("a");
    link.href = linkHref;
    link.target = "_blank";
    link.rel = "noopener";
    link.textContent = posting.source ? `Open on ${posting.source}` : "Open posting";
    actions.append(link);
  }
}

function renderReceipts(rows) {
  const list = document.createElement("div");
  list.className = "apps";
  for (const row of rows) {
    const item = document.createElement("article");
    item.className = "receipt";
    const copy = document.createElement("div");
    const badge = document.createElement("span");
    badge.className = "badge";
    badge.textContent = row.status || "applied";
    const title = document.createElement("strong");
    title.textContent = `${row.job_title || "Role"} at ${row.company || "the company"}`;
    const detail = document.createElement("div");
    detail.className = "meta-line";
    detail.textContent = `${formatDay(row.applied_date)} · job id ${row.job_id || ""}`;
    copy.append(badge, title, detail);
    item.append(copy);
    if (row.source_link) {
      const link = document.createElement("a");
      link.href = row.source_link;
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = "Posting";
      item.append(link);
    }
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
  profileEl.replaceChildren();
  if (!profile) {
    profileBlock.hidden = true;
    topNote.textContent = "Drop a resume, then talk through the matches.";
    return;
  }
  profileBlock.hidden = false;
  const who = document.createElement("div");
  who.className = "who";
  const avatar = document.createElement("span");
  avatar.className = "avatar";
  avatar.textContent = initials(profile.name || "?");
  const names = document.createElement("div");
  const name = document.createElement("strong");
  name.textContent = profile.name || "Name not found";
  const title = document.createElement("span");
  const years = typeof profile.years === "number" ? ` · about ${profile.years} ${profile.years === 1 ? "year" : "years"}` : "";
  title.textContent = (profile.designation || "Title not found") + years;
  names.append(name, title);
  who.append(avatar, names);
  profileEl.append(who);

  const contact = [profile.email, profile.phone].filter(Boolean).join(" · ");
  if (contact) addSideLine(contact);
  for (const role of profile.experience || []) {
    let bit = role.title || "Role";
    if (role.company) bit += ` at ${role.company}`;
    if (role.dates) bit += ` (${role.dates})`;
    addSideLine(bit);
  }
  for (const school of profile.education || []) addSideLine(school);
  for (const project of profile.projects || []) addSideLine(project);

  const skills = (profile.skills || []).slice(0, 10).map(labelSkill);
  if (skills.length) {
    const chips = document.createElement("div");
    chips.className = "chips";
    for (const skill of skills) {
      const chip = document.createElement("span");
      chip.className = "chip";
      chip.textContent = skill;
      chips.append(chip);
    }
    profileEl.append(chips);
  }
  if (profile.name) topNote.textContent = `Matching for ${profile.name}.`;
}

function addSideLine(text) {
  const line = document.createElement("p");
  line.className = "side-line";
  line.textContent = text;
  profileEl.append(line);
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
  if (filters.track) bits.push(filters.track === "fullstack" ? "Full stack" : filters.track.charAt(0).toUpperCase() + filters.track.slice(1));
  filterBlock.hidden = bits.length === 0;
  filtersEl.textContent = bits.join(" · ");
}

function renderApplied(rows) {
  appliedById = new Map();
  for (const row of rows || []) {
    if (row.job_id) appliedById.set(row.job_id, row);
  }
  appliedEl.replaceChildren();
  appliedEmpty.hidden = rows.length > 0;
  if (statSaved) statSaved.textContent = String(rows.length);
  for (const row of rows) {
    const item = document.createElement("li");
    const title = document.createElement("div");
    title.className = "role";
    title.textContent = `${row.job_title || "Role"} · ${row.company || ""}`;
    const detail = document.createElement("div");
    detail.className = "status";
    detail.textContent = `${row.status || "applied"} · ${formatDay(row.applied_date)}`;
    item.append(title, detail);
    if (row.source_link) {
      const link = document.createElement("a");
      link.href = row.source_link;
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = "Posting";
      link.style.color = "#f3eee4";
      link.style.fontSize = "0.78rem";
      item.append(link);
    }
    appliedEl.append(item);
  }
  // Cards already on screen should flip to Applied without waiting for a refresh.
  for (const card of thread.querySelectorAll(".card[data-job-id]")) {
    const saved = appliedById.get(card.dataset.jobId);
    if (!saved) continue;
    const existing = card._job || {};
    paintApplyState(card, saved, existing);
  }
}

function showTyping() {
  const bubble = document.createElement("article");
  bubble.className = "bubble assistant";
  const card = document.createElement("div");
  card.className = "reply-card";
  card.innerHTML = '<div class="typing" aria-label="Assistant is writing"><i></i><i></i><i></i></div>';
  bubble.append(card);
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

function initials(name) {
  const parts = String(name || "?").trim().split(/\s+/).slice(0, 2);
  return parts.map((part) => part[0] || "").join("").toUpperCase() || "?";
}

function hashName(name) {
  let hash = 0;
  for (const char of String(name || "")) hash = (hash + char.charCodeAt(0)) % 997;
  return hash;
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
