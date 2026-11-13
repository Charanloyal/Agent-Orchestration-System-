import type { StyleBlock } from "../api/types";

/** Exports of a rewritten Markdown document, built from its blocks (no dependencies). */

export const INLINE_MARKDOWN = /\*\*([^*]+)\*\*|`([^`]+)`|\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g;

/** Markdown inline marks removed: **bold** -> bold, `code` -> code, [text](url) -> text (url). */
export function plainInline(text: string): string {
  return text.replace(INLINE_MARKDOWN, (_m, bold?: string, code?: string, label?: string, url?: string) =>
    bold ?? code ?? `${label} (${url})`,
  );
}

function itemMarker(prefix: string): string {
  const trimmed = prefix.trim();
  return /^\d/.test(trimmed) ? `${trimmed} ` : "• ";
}

export function toPlainText(blocks: StyleBlock[]): string {
  return blocks
    .map((b) => {
      switch (b.kind) {
        case "heading":
        case "paragraph":
          return plainInline(b.text);
        case "item":
          return " ".repeat(b.prefix.length - b.prefix.trimStart().length) + itemMarker(b.prefix) + plainInline(b.text);
        case "quote":
          return b.text.replace(/^\s*>\s?/, "");
        case "blank":
          return "";
        default:
          return b.text;
      }
    })
    .join("\n");
}

const xml = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const MONO = '<w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/>';

function run(text: string, props = ""): string {
  return `<w:r>${props ? `<w:rPr>${props}</w:rPr>` : ""}<w:t xml:space="preserve">${xml(text)}</w:t></w:r>`;
}

/** Runs for a line, with **bold** and `code` kept as formatting. */
function runs(text: string, base = ""): string {
  let out = "";
  let last = 0;
  for (const m of text.matchAll(INLINE_MARKDOWN)) {
    if (m.index > last) out += run(text.slice(last, m.index), base);
    if (m[1] !== undefined) out += run(m[1], `${base}<w:b/>`);
    else if (m[2] !== undefined) out += run(m[2], base + MONO);
    else out += run(`${m[3]} (${m[4]})`, base);
    last = m.index + m[0].length;
  }
  if (last < text.length) out += run(text.slice(last), base);
  return out;
}

const para = (content: string, props = "") => `<w:p>${props ? `<w:pPr>${props}</w:pPr>` : ""}${content}</w:p>`;
const HEADING_SIZES = [40, 32, 28, 26, 24, 24];

export function toDocumentXml(blocks: StyleBlock[]): string {
  const body = blocks
    .filter((b) => b.kind !== "blank")
    .map((b) => {
      switch (b.kind) {
        case "heading": {
          const level = Math.min(Math.max(b.prefix.split("#").length - 1, 1), 6);
          return para(runs(b.text, `<w:b/><w:sz w:val="${HEADING_SIZES[level - 1]}"/>`), '<w:spacing w:before="240"/>');
        }
        case "item":
          return para(run(itemMarker(b.prefix)) + runs(b.text), '<w:ind w:left="360" w:hanging="360"/>');
        case "quote":
          return para(runs(b.text.replace(/^\s*>\s?/, ""), "<w:i/>"), '<w:ind w:left="720"/>');
        case "verbatim":
          return b.text
            .split("\n")
            .map((line) => para(run(line, MONO)))
            .join("");
        default:
          return para(runs(b.text));
      }
    })
    .join("");
  return (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' +
    body +
    "<w:sectPr/></w:body></w:document>"
  );
}

const CRC_TABLE = Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});

export function crc32(data: Uint8Array): number {
  let c = 0xffffffff;
  for (const byte of data) c = (CRC_TABLE[(c ^ byte) & 0xff] ?? 0) ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

/** A ZIP archive with stored (uncompressed) entries: enough for a .docx package. */
export function zip(files: { name: string; data: string }[]): Uint8Array<ArrayBuffer> {
  const encoder = new TextEncoder();
  const parts: Uint8Array[] = [];
  const central: Uint8Array[] = [];
  let offset = 0;
  for (const file of files) {
    const name = encoder.encode(file.name);
    const data = encoder.encode(file.data);
    const crc = crc32(data);
    const local = new DataView(new ArrayBuffer(30));
    local.setUint32(0, 0x04034b50, true);
    local.setUint16(4, 20, true);
    local.setUint16(12, 0x21, true); // date 1980-01-01, time 00:00
    local.setUint32(14, crc, true);
    local.setUint32(18, data.length, true);
    local.setUint32(22, data.length, true);
    local.setUint16(26, name.length, true);
    const header = new DataView(new ArrayBuffer(46));
    header.setUint32(0, 0x02014b50, true);
    header.setUint16(4, 20, true);
    header.setUint16(6, 20, true);
    header.setUint16(14, 0x21, true);
    header.setUint32(16, crc, true);
    header.setUint32(20, data.length, true);
    header.setUint32(24, data.length, true);
    header.setUint16(28, name.length, true);
    header.setUint32(42, offset, true);
    parts.push(new Uint8Array(local.buffer), name, data);
    central.push(new Uint8Array(header.buffer), name);
    offset += 30 + name.length + data.length;
  }
  const centralSize = central.reduce((n, c) => n + c.length, 0);
  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054b50, true);
  end.setUint16(8, files.length, true);
  end.setUint16(10, files.length, true);
  end.setUint32(12, centralSize, true);
  end.setUint32(16, offset, true);
  const all = [...parts, ...central, new Uint8Array(end.buffer)];
  const out = new Uint8Array(all.reduce((n, p) => n + p.length, 0));
  let at = 0;
  for (const p of all) {
    out.set(p, at);
    at += p.length;
  }
  return out;
}

export const DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

export function docxBytes(blocks: StyleBlock[]): Uint8Array<ArrayBuffer> {
  return zip([
    {
      name: "[Content_Types].xml",
      data:
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
        '<Default Extension="xml" ContentType="application/xml"/>' +
        '<Override PartName="/word/document.xml" ' +
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
    },
    {
      name: "_rels/.rels",
      data:
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
        '<Relationship Id="rId1" ' +
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" ' +
        'Target="word/document.xml"/></Relationships>',
    },
    { name: "word/document.xml", data: toDocumentXml(blocks) },
  ]);
}
