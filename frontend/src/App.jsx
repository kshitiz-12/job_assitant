import { useEffect, useRef, useState } from "react";
import { apiUrl } from "./api.js";
import { displayUserText, filterBits, formatDay, initials, labelSkill, monoColor } from "./format.js";

const SESSION_KEY = "job-chat-session";

export default function App() {
  const fileRef = useRef(null);
  const logRef = useRef(null);
  const sessionRef = useRef(localStorage.getItem(SESSION_KEY) || "");
  const [health, setHealth] = useState(null);
  const [healthError, setHealthError] = useState("");
  const [messages, setMessages] = useState([]);
  const [profile, setProfile] = useState(null);
  const [filters, setFilters] = useState(null);
  const [saved, setSaved] = useState([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [sidebar, setSidebar] = useState(false);

  const savedById = new Map(saved.filter((row) => row.job_id).map((row) => [row.job_id, row]));

  useEffect(() => {
    fetch(apiUrl("/api/health"))
      .then((res) => res.json())
      .then((data) => (data.ok ? setHealth(data) : setHealthError(data.error || "Dataset isn't loaded.")))
      .catch(() => setHealthError("Couldn't reach the server."));
  }, []);

  useEffect(() => {
    const existing = sessionRef.current;
    if (!existing) return;
    fetch(apiUrl(`/api/session/${existing}`))
      .then((res) => (res.ok ? res.json() : Promise.reject()))
      .then((data) => {
        setProfile(data.profile || null);
        setFilters(data.filters || null);
        setSaved(data.applications || []);
        setMessages(data.messages || []);
      })
      .catch(() => {
        rememberSession("");
      });
  }, []);

  useEffect(() => {
    const node = logRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [messages, busy]);

  function rememberSession(id) {
    sessionRef.current = id || "";
    if (sessionRef.current) localStorage.setItem(SESSION_KEY, sessionRef.current);
    else localStorage.removeItem(SESSION_KEY);
  }

  function resetChat() {
    rememberSession("");
    setMessages([]);
    setProfile(null);
    setFilters(null);
    setSaved([]);
    setDraft("");
    setSidebar(false);
  }

  async function send(text, file) {
    if (busy) return;
    const userText = file ? (text ? `Uploaded ${file.name}\n${text}` : `Uploaded ${file.name}`) : text;
    if (!userText) return;

    setMessages((current) => [
      ...current.map((message) => ({ ...message, suggestions: [] })),
      { role: "user", text: userText },
    ]);
    setDraft("");
    setBusy(true);

    const body = new FormData();
    body.append("session_id", sessionRef.current);
    body.append("message", text || "");
    if (file) body.append("file", file);

    try {
      const res = await fetch(apiUrl("/api/chat"), { method: "POST", body });
      const data = await res.json();
      if (data.session_id) rememberSession(data.session_id);
      setMessages((current) => [
        ...current,
        {
          role: "assistant",
          text: data.reply || "I didn't get a reply.",
          jobs: data.jobs || [],
          applications: data.applications || [],
          suggestions: data.suggestions || [],
          activity: data.activity || [],
        },
      ]);
      setProfile(data.profile || null);
      setFilters(data.filters || null);
      setSaved(data.saved_applications || []);
    } catch {
      setMessages((current) => [
        ...current,
        { role: "assistant", text: "I couldn't reach the server. Try that once more." },
      ]);
    } finally {
      setBusy(false);
    }
  }

  function onPickFile(event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (file) send(draft.trim(), file);
  }

  const sourceBits = Object.entries(health?.sources || {}).map(([name, count]) => `${count} ${name}`);
  const filterList = filterBits(filters);

  return (
    <div className="flex h-full bg-[#e7edf2] text-slate-900">
      {sidebar && (
        <button className="fixed inset-0 z-20 bg-slate-900/40 md:hidden" aria-label="Close panel" onClick={() => setSidebar(false)} />
      )}
      <aside className={`${sidebar ? "flex" : "hidden"} fixed inset-y-0 left-0 z-30 w-80 flex-col gap-4 overflow-auto bg-slate-900 p-5 text-stone-100 md:static md:flex`}>
        <div className="flex items-center gap-3">
          <span className="grid h-10 w-10 place-items-center rounded-xl bg-orange-700 font-serif text-lg shadow-lg shadow-orange-950/40">J</span>
          <div>
            <strong className="block font-serif text-xl leading-none">Job Chat</strong>
            <span className="text-sm text-stone-400">Dashboard</span>
          </div>
        </div>
        <p className="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-stone-300">
          {health ? `${health.jobs.toLocaleString()} live roles${sourceBits.length ? ` · ${sourceBits.join(", ")}` : ""}` : healthError || "Loading the dataset…"}
        </p>
        {profile && (
          <section>
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-stone-400">Candidate</h2>
            <div className="flex items-center gap-3">
              <span className="grid h-10 w-10 place-items-center rounded-full bg-orange-700 text-sm font-semibold">{initials(profile.name)}</span>
              <div>
                <strong className="block">{profile.name || "Name not found"}</strong>
                <span className="text-sm text-stone-400">
                  {profile.designation || "Title not found"}
                  {typeof profile.years === "number" ? ` · about ${profile.years} ${profile.years === 1 ? "year" : "years"}` : ""}
                </span>
              </div>
            </div>
            <div className="mt-3 space-y-1 text-sm text-stone-300">
              {[profile.email, profile.phone].filter(Boolean).join(" · ") && <p>{[profile.email, profile.phone].filter(Boolean).join(" · ")}</p>}
              {(profile.experience || []).map((role, index) => (
                <p key={index}>{[role.title || "Role", role.company ? `at ${role.company}` : "", role.dates ? `(${role.dates})` : ""].filter(Boolean).join(" ")}</p>
              ))}
              {(profile.education || []).map((line) => <p key={line}>{line}</p>)}
              {(profile.projects || []).map((line) => <p key={line}>{line}</p>)}
            </div>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {(profile.skills || []).slice(0, 10).map((skill) => (
                <span key={skill} className="rounded-full bg-white/10 px-2 py-0.5 text-xs">{labelSkill(skill)}</span>
              ))}
            </div>
          </section>
        )}
        {filterList.length > 0 && (
          <section>
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-stone-400">Active filters</h2>
            <p className="text-sm">{filterList.join(" · ")}</p>
          </section>
        )}
        <section className="min-h-0 flex-1">
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-stone-400">Saved postings</h2>
          {saved.length === 0 && <p className="text-sm text-stone-400">None yet. Ask the chat to keep a link.</p>}
          <ul className="space-y-2">
            {saved.map((row) => (
              <li key={row.job_id} className="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm">
                <div>{row.job_title || "Role"} · {row.company || ""}</div>
                <div className="mt-1 text-xs text-emerald-200">{row.status || "saved"} · {formatDay(row.applied_date)}</div>
                {row.source_link && <a className="text-xs text-stone-200 underline" href={row.source_link} target="_blank" rel="noreferrer">Posting</a>}
              </li>
            ))}
          </ul>
        </section>
        <p className="text-xs leading-relaxed text-stone-400">
          Listings are scraped from live Greenhouse, Lever, and Ashby boards. Company forms use a captcha, so saved rows keep the posting link.
        </p>
      </aside>

      <main className="flex min-w-0 flex-1 flex-col gap-4 p-4 md:p-5">
        <header className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <button className="grid h-9 w-9 place-items-center rounded-lg border border-slate-200 bg-white md:hidden" onClick={() => setSidebar(true)} aria-label="Show profile">
              ☰
            </button>
            <div>
              <h1 className="font-serif text-2xl leading-none">Workspace</h1>
              <p className="mt-1 text-sm text-slate-500">{profile?.name ? `Matching for ${profile.name}.` : "Upload a resume, then refine matches in the chat."}</p>
            </div>
          </div>
          <div className="flex gap-2">
            <button className="rounded-full bg-orange-700 px-4 py-2 text-sm font-semibold text-white" onClick={() => fileRef.current?.click()}>Upload resume</button>
            <button className="rounded-full border border-slate-300 bg-white px-4 py-2 text-sm" onClick={resetChat}>New chat</button>
          </div>
        </header>

        <section className="grid gap-3 sm:grid-cols-3">
          <Metric label="Roles" value={health ? health.jobs.toLocaleString() : "—"} note="Live scraped listings" delay="delay-1" />
          <Metric label="Boards" value={health ? Object.keys(health.sources || {}).length : "—"} note={sourceBits.join(" · ") || "Greenhouse, Lever, Ashby"} delay="delay-2" />
          <Metric label="Saved" value={String(saved.length)} note="Links kept, not submitted" delay="delay-3" />
        </section>

        <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-3xl border border-white/80 bg-white/80 shadow-xl shadow-slate-300/40 backdrop-blur">
          <div ref={logRef} className="flex-1 space-y-4 overflow-auto bg-[radial-gradient(circle_at_top,_#fff,_#f4f7f8_55%)] px-4 py-5 md:px-6">
            <div className="mx-auto flex w-full max-w-3xl flex-col gap-4">
              {messages.length === 0 && <Welcome onUpload={() => fileRef.current?.click()} onPrompt={(text) => send(text)} />}
              {messages.map((message, index) => (
                <Message
                  key={index}
                  message={message}
                  savedById={savedById}
                  onSend={send}
                />
              ))}
              {busy && (
                <div className="rise flex w-fit items-center gap-2 rounded-2xl rounded-bl-md border border-slate-100 bg-white px-4 py-3 text-sm text-slate-500 shadow-sm">
                  <span className="typing-dot h-1.5 w-1.5 rounded-full bg-orange-700" />
                  <span className="typing-dot h-1.5 w-1.5 rounded-full bg-orange-700" />
                  <span className="typing-dot h-1.5 w-1.5 rounded-full bg-orange-700" />
                </div>
              )}
            </div>
          </div>
          <form
            className="m-3 rounded-2xl border border-slate-200 bg-white p-2 shadow-sm"
            onSubmit={(event) => {
              event.preventDefault();
              const text = draft.trim();
              if (text) send(text);
            }}
          >
            <textarea
              className="max-h-36 w-full resize-none bg-transparent px-2 py-2 outline-none"
              rows={1}
              value={draft}
              placeholder="Ask for frontend roles, remote jobs, or a posting number"
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
            />
            <div className="flex items-center gap-2 px-1 pb-1">
              <input ref={fileRef} className="hidden" type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" onChange={onPickFile} />
              <button type="button" className="rounded-full bg-orange-700 px-4 py-2 text-sm font-semibold text-white" onClick={() => fileRef.current?.click()}>Upload resume</button>
              <span className="mr-auto hidden text-xs text-slate-500 sm:inline">PDF or DOCX · Enter to send</span>
              <button className="rounded-full bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50" disabled={busy}>Send</button>
            </div>
          </form>
        </section>
      </main>
    </div>
  );
}

function Metric({ label, value, note, delay = "" }) {
  return (
    <article className={`rise ${delay} rounded-2xl border border-white bg-white px-4 py-3 shadow-sm`}>
      <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">{label}</span>
      <strong className="mt-1 block font-serif text-3xl leading-none">{value}</strong>
      <small className="mt-2 block text-xs text-slate-500">{note}</small>
    </article>
  );
}

function Welcome({ onUpload, onPrompt }) {
  return (
    <section className="rise rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="font-serif text-3xl">Send a resume. I'll take it from there.</h2>
      <p className="mt-2 max-w-xl text-slate-600">This is a conversation, not a form. After the file is read, ask for remote roles, a skill, or a specific card.</p>
      <ol className="mt-4 grid gap-3 md:grid-cols-3">
        {[
          ["Read the resume", "PDF or DOCX. The chat shows name, contact, title, skills, experience, education, and projects."],
          ["Match the dataset", "Each card has a reason: shared skills, title, and whether the years fit."],
          ["Open the real posting", "The company form uses a captcha, so the chat keeps the live link."],
        ].map(([title, copy], index) => (
          <li key={title} className="rise rounded-xl border border-slate-200 bg-stone-50 p-3" style={{ animationDelay: `${index * 70}ms` }}>
            <span className="grid h-6 w-6 place-items-center rounded-full bg-orange-100 text-xs font-semibold text-orange-900">{index + 1}</span>
            <strong className="mt-2 block">{title}</strong>
            <span className="mt-1 block text-sm text-slate-500">{copy}</span>
          </li>
        ))}
      </ol>
      <button className="mt-4 rounded-full bg-orange-700 px-4 py-2 text-sm font-semibold text-white" onClick={onUpload}>Upload resume</button>
      <div className="mt-3">
        <button className="rounded-full border border-slate-300 bg-white px-3 py-1.5 text-sm" onClick={() => onPrompt("What can you do?")}>What can you do?</button>
      </div>
    </section>
  );
}

function Message({ message, savedById, onSend }) {
  if (message.role === "user") {
    return (
      <article className="rise max-w-lg self-end rounded-2xl rounded-br-md bg-slate-800 px-4 py-2 text-stone-100 shadow-md">
        <div className="text-xs text-stone-400">You</div>
        <p className="whitespace-pre-wrap">{displayUserText(message.text)}</p>
      </article>
    );
  }
  return (
    <article className="rise rounded-2xl rounded-bl-md border border-slate-100 bg-white px-4 py-3 shadow-sm">
      <div className="mb-1 flex justify-between gap-3 text-xs text-slate-500">
        <span>Assistant</span>
        {message.activity?.length > 0 && <span className="text-orange-800">{message.activity.join(" · ")}</span>}
      </div>
      <Rich text={message.text} />
      {message.jobs?.length > 0 && (
        <div className="mt-3 space-y-3">
          {message.jobs.map((job) => (
            <JobCard key={job.id || job.rank} job={job} saved={savedById.get(job.id)} onSend={onSend} />
          ))}
        </div>
      )}
      {message.applications?.length > 0 && (
        <div className="mt-3 space-y-2">
          {message.applications.map((row) => (
            <article key={row.job_id} className="flex items-start justify-between gap-3 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2">
              <div>
                <span className="rounded-full bg-emerald-700 px-2 py-0.5 text-[10px] font-semibold uppercase text-white">{row.status || "saved"}</span>
                <strong className="mt-1 block">{row.job_title || "Role"} at {row.company || "the company"}</strong>
                <div className="text-sm text-slate-500">{formatDay(row.applied_date)} · {row.job_id}</div>
              </div>
              {row.source_link && <a className="text-sm text-orange-800" href={row.source_link} target="_blank" rel="noreferrer">Posting</a>}
            </article>
          ))}
        </div>
      )}
      {message.suggestions?.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {message.suggestions.map((item) => (
            <button key={item} className="rounded-full border border-slate-300 bg-stone-50 px-3 py-1.5 text-sm transition hover:-translate-y-0.5 hover:border-orange-300" onClick={() => onSend(item)}>{item}</button>
          ))}
        </div>
      )}
    </article>
  );
}

function JobCard({ job, saved, onSend }) {
  return (
    <article className={`rise rounded-2xl border p-3 transition hover:-translate-y-0.5 hover:shadow-md ${saved ? "border-emerald-200 bg-emerald-50/70" : "border-slate-200 bg-stone-50"}`}>
      <div className="flex gap-3">
        <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl font-semibold text-white" style={{ background: monoColor(job.company) }}>{initials(job.company)}</span>
        <div className="min-w-0">
          <h3 className="font-semibold">{job.title || "Untitled role"}</h3>
          <p className="text-sm text-slate-500">{[job.rank ? `Job ${job.rank}` : "", job.company].filter(Boolean).join(" · ")}</p>
        </div>
        {typeof job.score === "number" && <span className="ml-auto text-sm font-semibold text-emerald-700">{job.score}%</span>}
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {job.location && <span className="rounded-full bg-stone-100 px-2 py-0.5 text-xs">{job.location}</span>}
        {job.remote && <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs text-emerald-800">Remote</span>}
        {job.experience_required && <span className="rounded-full bg-stone-100 px-2 py-0.5 text-xs">{job.experience_required}</span>}
        {(job.skills || []).slice(0, 5).map((skill) => (
          <span key={skill} className="rounded-full border border-slate-200 px-2 py-0.5 text-xs">{labelSkill(skill)}</span>
        ))}
      </div>
      {job.reason && <p className="mt-2 text-sm">{job.reason}</p>}
      {job.preview && <p className="mt-1 text-sm text-slate-500">{job.preview}</p>}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {saved ? (
          <span className="rounded-full bg-emerald-100 px-3 py-1 text-sm font-semibold text-emerald-800">
            {saved.status === "not_submitted" ? "Not submitted" : "Saved"} · {formatDay(saved.applied_date)}
          </span>
        ) : job.rank ? (
          <button
            className="rounded-full bg-orange-700 px-3 py-1.5 text-sm font-semibold text-white"
            onClick={() => onSend(job.id ? `Apply to ${job.title || "job"} (${job.id})` : `Apply to job ${job.rank}`)}
          >
            Apply
          </button>
        ) : null}
        {((saved && saved.source_link) || job.source_link) && (
          <a className="ml-auto text-sm text-slate-500" href={(saved && saved.source_link) || job.source_link} target="_blank" rel="noreferrer">
            {job.source ? `Open on ${job.source}` : "Open posting"}
          </a>
        )}
      </div>
    </article>
  );
}

function Rich({ text }) {
  const parts = String(text || "").split("\n");
  return (
    <div className="space-y-1 text-[15px] leading-relaxed">
      {parts.map((line, index) => (
        <p key={index}>{line ? <Inline text={line} /> : <br />}</p>
      ))}
    </div>
  );
}

function Inline({ text }) {
  const tokens = text.split(/(\*\*[^*]+\*\*|`[^`]+`|https?:\/\/[^\s]+)/g);
  return tokens.map((token, index) => {
    if (token.startsWith("**") && token.endsWith("**")) return <strong key={index}>{token.slice(2, -2)}</strong>;
    if (token.startsWith("`") && token.endsWith("`")) return <code key={index} className="rounded bg-slate-200/70 px-1 text-[0.85em]">{token.slice(1, -1)}</code>;
    if (token.startsWith("http")) {
      const clean = token.replace(/[).,]+$/, "");
      const tail = token.slice(clean.length);
      return <span key={index}><a className="text-orange-800 underline" href={clean} target="_blank" rel="noreferrer">{clean}</a>{tail}</span>;
    }
    return <span key={index}>{token}</span>;
  });
}
