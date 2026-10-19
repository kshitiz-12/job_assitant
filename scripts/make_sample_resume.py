"""Build the sample resume used to try the chat. Alex Rivera is fictional."""

from __future__ import annotations

from pathlib import Path

from docx import Document

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "samples"

LINES = [
    "Alex Rivera",
    "Software Engineer",
    "alex.rivera@example.com | (415) 555-0134 | San Francisco",
    "https://linkedin.com/in/alexrivera",
    "",
    "Summary",
    "Software engineer with 3 years of experience building web applications in React, TypeScript, Node.js, and PostgreSQL.",
    "",
    "Experience",
    "Software Engineer",
    "Northwind Labs",
    "Apr 2025 - Present",
    "Built internal dashboards in React and TypeScript.",
    "Designed Node.js APIs backed by PostgreSQL.",
    "",
    "Junior Developer",
    "Harbor Systems",
    "Oct 2023 - Mar 2025",
    "Shipped REST endpoints in JavaScript and Python.",
    "",
    "Education",
    "B.S. Computer Science, State University, 2022",
    "",
    "Skills",
    "React, TypeScript, JavaScript, Node.js, PostgreSQL, Python, Git, AWS",
    "",
    "Projects",
    "Trailhead - Hiking log built with React and Node.js",
    "Budget board - TypeScript expense tracker",
]


def build_pdf(lines: list[str]) -> bytes:
    wrapped: list[str] = []
    for line in lines:
        while len(line) > 90:
            wrapped.append(line[:90])
            line = line[90:]
        wrapped.append(line)
    ops = ["BT", "/F1 11 Tf"]
    for index, line in enumerate(wrapped[:48]):
        y = 760 - index * 15
        if y < 48:
            break
        safe = line.encode("latin-1", "replace").decode("latin-1")
        safe = safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        ops.append(f"1 0 0 1 54 {y} Tm ({safe}) Tj")
    ops.append("ET")
    stream = ("\n".join(ops) + "\n").encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"endstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode("ascii"))
        output.extend(obj)
        output.extend(b"\nendobj\n")
    xref = len(output)
    count = len(objects) + 1
    output.extend(f"xref\n0 {count}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer\n<< /Size {count} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii")
    )
    return bytes(output)


def build_docx(path: Path) -> None:
    document = Document()
    for line in LINES:
        document.add_paragraph(line)
    document.save(path)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    (OUT / "alex_rivera_resume.pdf").write_bytes(build_pdf(LINES))
    build_docx(OUT / "alex_rivera_resume.docx")
    print(f"wrote samples in {OUT}")


if __name__ == "__main__":
    main()
