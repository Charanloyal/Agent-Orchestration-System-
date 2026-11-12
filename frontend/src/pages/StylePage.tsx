import { useId, useState, type FormEvent } from "react";
import { useParams, useSearchParams } from "react-router";

import { saveBlob } from "../api/client";
import { useDocumentTitle, useStyleRewrite, useUploads } from "../api/hooks";
import type { StylePersona, StyleReport, StyleRewrite } from "../api/types";
import { Card } from "../components/ui";

const PERSONAS: { value: StylePersona; label: string; hint: string }[] = [
  { value: "journalist", label: "Journalist", hint: "Active, concrete, varied sentence length" },
  { value: "academic", label: "Academic", hint: "Keeps formal transitions; splits only very long sentences" },
  { value: "executive", label: "Executive brief", hint: "Short and direct; removes filler" },
  { value: "technical", label: "Technical", hint: "Precise; keeps technical terms" },
];
const MAX_CHARS = 50_000;

type Metric = {
  label: string;
  explain: string;
  value: (r: StyleReport) => number;
  format: (v: number) => string;
  better: "higher" | "lower";
};

const METRICS: Metric[] = [
  {
    label: "Sentence-length variation",
    explain: "Standard deviation of sentence lengths divided by their mean. Higher means short and long sentences mix.",
    value: (r) => r.sentence_length_cv,
    format: (v) => v.toFixed(2),
    better: "higher",
  },
  {
    label: "Vocabulary diversity",
    explain: "Moving-average type-token ratio over 50-word windows (0 to 1).",
    value: (r) => r.vocabulary_mattr,
    format: (v) => v.toFixed(2),
    better: "higher",
  },
  {
    label: "Stock phrases per 1,000 words",
    explain: "Boilerplate wording such as \"it is important to note\" or \"delve into\".",
    value: (r) => r.stock_phrases_per_1000_words,
    format: (v) => v.toFixed(1),
    better: "lower",
  },
];

function Highlighted({ report }: { report: StyleReport }) {
  const flagged = new Set(report.flagged);
  return (
    <div className="style-text">
      {report.sentence_list.map((s, i) =>
        flagged.has(i) ? (
          <mark key={i} title={s.phrases.length ? `Stock phrases: ${s.phrases.join(", ")}` : `${s.words} words`}>
            {s.text}{" "}
          </mark>
        ) : (
          <span key={i}>{s.text} </span>
        ),
      )}
    </div>
  );
}

function Results({ result }: { result: StyleRewrite }) {
  const lock = result.fact_lock;
  return (
    <>
      <section className="style-metrics" aria-label="Measurements before and after">
        {METRICS.map((m) => {
          const before = m.value(result.before);
          const after = m.value(result.after);
          const improved = m.better === "higher" ? after > before : after < before;
          return (
            <Card key={m.label} title={m.label}>
              <p className="metric">
                {m.format(before)} <span aria-hidden="true">→</span>
                <span className="visually-hidden"> to </span> {m.format(after)}
              </p>
              <p className="small muted">{m.explain}</p>
              {before !== after && (
                <p className={`small ${improved ? "text-success" : "text-warning"}`}>
                  {improved ? "Improved" : "Changed"} ({m.better} is plainer prose)
                </p>
              )}
            </Card>
          );
        })}
        <Card title="Facts preserved">
          <p className="metric" data-testid="fact-lock">
            {lock.preserved} / {lock.total}
          </p>
          <p className="small muted">Numbers, dates, percentages, quotes, citations and links, compared exactly.</p>
          {lock.missing.length > 0 && <p className="small text-warning">Missing: {lock.missing.join(", ")}</p>}
        </Card>
      </section>
      <p className="small muted">
        {result.changed_sentences} sentence change(s) in {result.passes} pass(es)
        {result.rejected_changes > 0 && `; ${result.rejected_changes} change(s) rejected because they would have altered a fact`}.
        These are measurements of the text, not a prediction of who or what wrote it.
      </p>
      <div className="style-compare">
        <Card title={`Original · ${result.source}`}>
          <Highlighted report={result.before} />
        </Card>
        <Card
          title={`Rewritten · ${PERSONAS.find((p) => p.value === result.persona)?.label}`}
          actions={
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => saveBlob(new Blob([result.rewritten], { type: "text/markdown" }), "rewritten.md")}
            >
              Download .md
            </button>
          }
        >
          <Highlighted report={result.after} />
        </Card>
      </div>
    </>
  );
}

/** Measures prose style and rewrites it in a chosen voice without touching facts
 *  (backend/app/services/style.py). Nothing is stored. */
export function StylePage() {
  useDocumentTitle("Style studio");
  const { workspaceId = "" } = useParams();
  const [params] = useSearchParams();
  const uploads = useUploads(workspaceId);
  const rewrite = useStyleRewrite(workspaceId);
  const [mode, setMode] = useState<"text" | "upload">(params.get("upload") ? "upload" : "text");
  const [text, setText] = useState("");
  const [uploadId, setUploadId] = useState(params.get("upload") ?? "");
  const [persona, setPersona] = useState<StylePersona>("journalist");
  const ids = useId();

  const ready = mode === "text" ? text.trim().length > 0 : uploadId !== "";
  const submit = (event: FormEvent) => {
    event.preventDefault();
    rewrite.mutate(mode === "text" ? { text, persona } : { upload_id: uploadId, persona });
  };

  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <h1>Style studio</h1>
          <p className="muted">
            Measure sentence rhythm, vocabulary and boilerplate, then rewrite in a chosen voice. Every
            number, date, quote and citation stays exactly as it was.
          </p>
        </div>
      </div>

      <Card title="Text">
        <form onSubmit={submit} className="stack">
          <div className="versions" role="group" aria-label="Source">
            <button type="button" aria-pressed={mode === "text"} onClick={() => setMode("text")}>
              Paste text
            </button>
            <button type="button" aria-pressed={mode === "upload"} onClick={() => setMode("upload")}>
              Workspace document
            </button>
          </div>
          {mode === "text" ? (
            <div className="field">
              <label htmlFor={`${ids}-text`}>Text to measure and rewrite</label>
              <textarea
                id={`${ids}-text`}
                rows={10}
                maxLength={MAX_CHARS}
                value={text}
                onChange={(e) => setText(e.target.value)}
                aria-describedby={`${ids}-count`}
                placeholder="Paste a report, article or draft (public or synthetic material only)."
              />
              <span id={`${ids}-count`} className="small muted">
                {text.length.toLocaleString()} / {MAX_CHARS.toLocaleString()} characters
              </span>
            </div>
          ) : (
            <label className="field">
              <span>Document</span>
              <select value={uploadId} onChange={(e) => setUploadId(e.target.value)}>
                <option value="">Choose a document…</option>
                {uploads.data?.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.title ?? u.filename}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="field">
            <span>Voice</span>
            <select value={persona} onChange={(e) => setPersona(e.target.value as StylePersona)}>
              {PERSONAS.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}: {p.hint}
                </option>
              ))}
            </select>
          </label>
          <div className="row end">
            <button type="submit" className="btn btn-primary" disabled={!ready || rewrite.isPending}>
              {rewrite.isPending ? "Working…" : "Measure and rewrite"}
            </button>
          </div>
        </form>
      </Card>

      {rewrite.data && <Results result={rewrite.data} />}
    </div>
  );
}
