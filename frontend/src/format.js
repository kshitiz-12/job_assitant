const KNOWN = {
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

const MONO = ["#1f6f54", "#8a4b2f", "#2f4f6f", "#6f3d55", "#3f5b3a", "#6a5428"];

export function labelSkill(name) {
  if (!name) return "";
  const key = String(name).toLowerCase();
  if (KNOWN[key]) return KNOWN[key];
  if (name !== key) return name;
  return name.replace(/(^|[\s/])(\w)/g, (_, gap, letter) => gap + letter.toUpperCase());
}

export function initials(name) {
  const parts = String(name || "?").trim().split(/\s+/).slice(0, 2);
  return parts.map((part) => part[0] || "").join("").toUpperCase() || "?";
}

export function monoColor(name) {
  let hash = 0;
  for (const char of String(name || "")) hash = (hash + char.charCodeAt(0)) % 997;
  return MONO[hash % MONO.length];
}

export function formatDay(iso) {
  if (!iso) return "";
  const [year, month, day] = iso.split("-").map(Number);
  if (!year || !month || !day) return iso;
  return new Date(Date.UTC(year, month - 1, day)).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}

export function displayUserText(text) {
  return String(text || "").replace(/\s+\((?:gh|lv|ab)_[^)]+\)$/i, "");
}

export function filterBits(filters) {
  if (!filters) return [];
  const bits = [];
  if (filters.remote === true) bits.push("Remote only");
  if (filters.remote === false) bits.push("On-site only");
  if (filters.skills?.length) bits.push(filters.skills.map(labelSkill).join(", "));
  if (filters.location) bits.push(filters.location);
  if (filters.level) bits.push(filters.level);
  if (filters.track) {
    bits.push(filters.track === "fullstack" ? "Full stack" : filters.track[0].toUpperCase() + filters.track.slice(1));
  }
  return bits;
}
