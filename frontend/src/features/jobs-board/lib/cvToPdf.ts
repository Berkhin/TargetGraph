// Turns the (Markdown) tailored-CV text into an A4 PDF. The CV is authored as
// Markdown, so we render a light subset — headings, bullet lists, horizontal
// rules — rather than dumping raw "##" / "**" markers. Inline emphasis markers
// are stripped (jsPDF can't mix styles mid-line without manual layout), keeping
// the output clean and the text selectable. The PDF can be downloaded
// (downloadCvPdf) or returned as base64 for an email attachment (cvPdfBase64).

import type { jsPDF as JsPDFDoc } from "jspdf";

const MARGIN = 48; // pt
const FONT = "helvetica";

type Block =
  | { kind: "h1" | "h2" | "h3" | "p"; text: string }
  | { kind: "bullet"; text: string }
  | { kind: "rule" }
  | { kind: "space" };

// Strip inline Markdown emphasis/code markers so they don't show up literally.
function stripInline(text: string): string {
  return text
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/\*(.+?)\*/g, "$1")
    .replace(/__(.+?)__/g, "$1")
    .replace(/`(.+?)`/g, "$1")
    .trim();
}

function parse(markdown: string): Block[] {
  const blocks: Block[] = [];
  for (const raw of markdown.replace(/\r\n/g, "\n").split("\n")) {
    const line = raw.trimEnd();
    if (!line.trim()) {
      blocks.push({ kind: "space" });
    } else if (/^#{3,}\s+/.test(line)) {
      blocks.push({ kind: "h3", text: stripInline(line.replace(/^#{3,}\s+/, "")) });
    } else if (/^##\s+/.test(line)) {
      blocks.push({ kind: "h2", text: stripInline(line.replace(/^##\s+/, "")) });
    } else if (/^#\s+/.test(line)) {
      blocks.push({ kind: "h1", text: stripInline(line.replace(/^#\s+/, "")) });
    } else if (/^(-{3,}|\*{3,}|_{3,})$/.test(line.trim())) {
      blocks.push({ kind: "rule" });
    } else if (/^\s*[-*•]\s+/.test(line)) {
      blocks.push({
        kind: "bullet",
        text: stripInline(line.replace(/^\s*[-*•]\s+/, "")),
      });
    } else {
      blocks.push({ kind: "p", text: stripInline(line) });
    }
  }
  return blocks;
}

// Slugify the company/title into a safe-ish file name.
export function cvFileName(parts: string[]): string {
  const base = parts
    .join("-")
    .replace(/[^\p{L}\p{N}]+/gu, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 80);
  return `${base || "tailored-cv"}.pdf`;
}

/**
 * Render the CV markdown into a jsPDF document (no I/O / download).
 *
 * jsPDF is imported dynamically so its (~350 KB) bundle is fetched only when the
 * user actually exports a PDF, keeping it out of the main app chunk. Shared by
 * {@link downloadCvPdf} and {@link cvPdfBase64}.
 */
async function buildCvPdf(markdown: string): Promise<JsPDFDoc> {
  const { jsPDF } = await import("jspdf");
  const doc = new jsPDF({ unit: "pt", format: "a4" });
  const pageW = doc.internal.pageSize.getWidth();
  const pageH = doc.internal.pageSize.getHeight();
  const maxW = pageW - MARGIN * 2;
  let y = MARGIN;

  // Advance to a new page if the next `space` pt would overflow the bottom margin.
  const ensure = (space: number) => {
    if (y + space > pageH - MARGIN) {
      doc.addPage();
      y = MARGIN;
    }
  };

  const writeWrapped = (
    text: string,
    size: number,
    style: "normal" | "bold",
    indent = 0,
  ) => {
    doc.setFont(FONT, style);
    doc.setFontSize(size);
    const lineH = size * 1.35;
    const lines = doc.splitTextToSize(text, maxW - indent) as string[];
    for (const ln of lines) {
      ensure(lineH);
      doc.text(ln, MARGIN + indent, y);
      y += lineH;
    }
  };

  for (const block of parse(markdown)) {
    switch (block.kind) {
      case "space":
        y += 6;
        break;
      case "rule":
        ensure(12);
        doc.setDrawColor(180);
        doc.line(MARGIN, y, pageW - MARGIN, y);
        y += 12;
        break;
      case "h1":
        y += 4;
        writeWrapped(block.text, 18, "bold");
        y += 2;
        break;
      case "h2":
        y += 3;
        writeWrapped(block.text, 14, "bold");
        y += 2;
        break;
      case "h3":
        writeWrapped(block.text, 12, "bold");
        break;
      case "bullet":
        // Draw the marker, then the (wrapped) text indented past it.
        doc.setFont(FONT, "normal");
        doc.setFontSize(11);
        ensure(11 * 1.35);
        doc.text("•", MARGIN + 6, y);
        writeWrapped(block.text, 11, "normal", 18);
        break;
      case "p":
        writeWrapped(block.text, 11, "normal");
        break;
    }
  }

  return doc;
}

/**
 * Build a PDF from the CV markdown and trigger a browser download.
 *
 * @param markdown  the (possibly user-edited) CV text
 * @param nameParts pieces used to build the filename, e.g. [company, jobTitle]
 */
export async function downloadCvPdf(
  markdown: string,
  nameParts: string[],
): Promise<void> {
  const doc = await buildCvPdf(markdown);
  doc.save(cvFileName(nameParts));
}

/**
 * Build the CV PDF and return its raw bytes as a base64 string (no data-URI
 * prefix) — ready to ship to the backend as an email attachment.
 */
export async function cvPdfBase64(markdown: string): Promise<string> {
  const doc = await buildCvPdf(markdown);
  // datauristring -> "data:application/pdf;...;base64,<DATA>"; take the payload.
  return doc.output("datauristring").split(";base64,").pop() ?? "";
}
