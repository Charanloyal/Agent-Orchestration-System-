import { describe, expect, it } from "vitest";

import type { StyleBlock } from "../api/types";
import { crc32, docxBytes, toDocumentXml, toPlainText, zip } from "./exports";

const b = (kind: StyleBlock["kind"], prefix: string, text: string): StyleBlock => ({
  kind,
  prefix,
  text,
  first_sentence: 0,
  sentence_count: 0,
});

const DOC = [
  b("heading", "## ", "Results & **plans**"),
  b("blank", "", ""),
  b("paragraph", "", "Revenue rose 12% [1]. See [the report](https://example.org/r)."),
  b("item", "- ", "Deploying <three> clusters."),
  b("item", "2. ", "Second step."),
  b("quote", "", '> "Quoted," she said.'),
  b("verbatim", "", "```\nx = 1\n```"),
];

describe("exports", () => {
  it("plain text drops Markdown marks but keeps lines, numbering and quotes", () => {
    expect(toPlainText(DOC).split("\n")).toEqual([
      "Results & plans",
      "",
      "Revenue rose 12% [1]. See the report (https://example.org/r).",
      "• Deploying <three> clusters.",
      "2. Second step.",
      '"Quoted," she said.',
      "```",
      "x = 1",
      "```",
    ]);
  });

  it("Word XML escapes text and keeps headings bold and items marked", () => {
    const xml = toDocumentXml(DOC);
    expect(xml).toContain('<w:t xml:space="preserve">Results &amp; </w:t>');
    expect(xml).toContain("<w:b/><w:sz w:val=\"32\"/>");
    expect(xml).toContain("Deploying &lt;three&gt; clusters.");
    expect(xml).not.toContain("<three>");
    expect(xml).toContain('<w:t xml:space="preserve">2. </w:t>');
  });

  it("CRC-32 matches the standard check value", () => {
    expect(crc32(new TextEncoder().encode("123456789"))).toBe(0xcbf43926);
  });

  it("the ZIP has a local header per file and an end record that counts them", () => {
    const bytes = zip([
      { name: "a.txt", data: "hello" },
      { name: "b.txt", data: "world" },
    ]);
    const view = new DataView(bytes.buffer);
    expect(view.getUint32(0, true)).toBe(0x04034b50);
    const end = bytes.length - 22;
    expect(view.getUint32(end, true)).toBe(0x06054b50);
    expect(view.getUint16(end + 10, true)).toBe(2);
    expect(view.getUint32(14, true)).toBe(crc32(new TextEncoder().encode("hello")));
  });

  it("a .docx package holds the three required parts", () => {
    const text = new TextDecoder().decode(docxBytes(DOC));
    for (const part of ["[Content_Types].xml", "_rels/.rels", "word/document.xml"]) {
      expect(text).toContain(part);
    }
  });
});
