import { Fragment, useId, useState, type FormEvent, type ReactNode } from "react";
import { useParams, useSearchParams } from "react-router";

import { saveBlob } from "../api/client";
import { useAiEngine, useDocumentTitle, useStyleRewrite, useUploads } from "../api/hooks";
import type { StyleBlock, StylePersona, StyleReport, StyleRewrite } from "../api/types";
import { Ring } from "../components/Ring";
import { notify } from "../components/toast";
import { Badge, Card } from "../components/ui";
import { DOCX_TYPE, INLINE_MARKDOWN, docxBytes, toPlainText } from "../lib/exports";
import { STYLE_SAMPLE } from "./styleSample";

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
  /** Where the value sits on the ring, 0 to 1. */
  scale: (v: number) => number;
  format: (v: number) => string;
  better: "higher" | "lower";
};

const METRICS: Metric[] = [
  {
    label: "Sentence-length variation",
    explain: "Standard deviation of sentence lengths divided by their mean. Higher means short and long sentences mix.",
    value: (r) => r.sentence_length_cv,
    scale: (v) => v,
    format: (v) => v.toFixed(2),
    better: "higher",
  },
  {
    label: "Vocabulary diversity",
    explain: "Share of distinct words, averaged over 50-word windows (0 to 1).",
    value: (r) => r.vocabulary_mattr,
    scale: (v) => v,
    format: (v) => v.toFixed(2),
    better: "higher",
  },
  {
    label: "Stock phrases per 1,000 words",
    explain: "Templated wording such as \"In today's rapidly evolving…\" or \"delve into\". The ring is full at 50.",
    value: (r) => r.stock_phrases_per_1000_words,
    scale: (v) => v / 50,
    format: (v) => v.toFixed(1),
    better: "lower",
  },
];

/** **bold**, `code` and http(s) links; everything else is text (never HTML). */
function Inline({ text }: { text: string }) {
  const out: ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(INLINE_MARKDOWN)) {
    if (m.index > last) out.push(text.slice(last, m.index));
    if (m[1] !== undefined) out.push(<strong key={m.index}>{m[1]}</strong>);
    else if (m[2] !== undefined) out.push(<code key={m.index}>{m[2]}</code>);
    else
      out.push(
        <a key={m.index} href={m[4]} target="_blank" rel="noreferrer noopener">
          {m[3]}
        </a>,
      );
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return <>{out}</>;
}

/** The document as formatted Markdown, with sentences that carry stock phrases (or run past 40
 *  words) highlighted. Headings, lists, quotes and code keep their structure. */
export function FormattedDocument({ report }: { report: StyleReport }) {
  const flagged = new Set(report.flagged);
  const prose = (b: StyleBlock) =>
    report.sentence_list.slice(b.first_sentence, b.first_sentence + b.sentence_count).map((s, k) => {
      const index = b.first_sentence + k;
      const body = <Inline text={s.text} />;
      return (
        <Fragment key={index}>
          {k > 0 && " "}
          {flagged.has(index) ? (
            <mark title={s.phrases.length ? `Stock phrases: ${s.phrases.join(", ")}` : `${s.words} words`}>{body}</mark>
          ) : (
            body
          )}
        </Fragment>
      );
    });
  const isOrdered = (b: StyleBlock) => /^\s*\d/.test(b.prefix);
  const out: ReactNode[] = [];
  const blocks = report.blocks;
  for (let i = 0; i < blocks.length; i++) {
    const b = blocks[i];
    if (!b) continue;
    if (b.kind === "item") {
      const ordered = isOrdered(b);
      const items: StyleBlock[] = [];
      let j = i;
      for (; j < blocks.length; j++) {
        const c = blocks[j];
        const next = blocks[j + 1];
        if (c?.kind === "item" && isOrdered(c) === ordered) items.push(c);
        else if (!(c?.kind === "blank" && next?.kind === "item" && isOrdered(next) === ordered)) break;
      }
      const List = ordered ? "ol" : "ul";
      out.push(
        <List key={i} start={ordered ? Number.parseInt(b.prefix, 10) || 1 : undefined}>
          {items.map((item, k) => (
            <li key={k}>{prose(item)}</li>
          ))}
        </List>,
      );
      i = j - 1;
    } else if (b.kind === "heading") {
      const level = Math.min(Math.max(b.prefix.split("#").length - 1, 1) + 2, 6);
      const Heading = `h${level}` as "h3";
      out.push(
        <Heading key={i}>
          <Inline text={b.text} />
        </Heading>,
      );
    } else if (b.kind === "paragraph") {
      out.push(<p key={i}>{prose(b)}</p>);
    } else if (b.kind === "quote") {
      out.push(
        <blockquote key={i}>
          <Inline text={b.text.replace(/^\s*>\s?/, "")} />
        </blockquote>,
      );
    } else if (b.kind === "verbatim") {
      out.push(<pre key={i}>{b.text}</pre>);
    }
  }
  return <div className="md-doc">{out}</div>;
}

function SentenceBars({ report, label }: { report: StyleReport; label: string }) {
  const lengths = report.sentence_list.slice(0, 200).map((s) => s.words);
  const width = Math.max(lengths.length * 8, 8);
  return (
    <figure className="rhythm">
      <svg
        viewBox={`0 0 ${width} 64`}
        preserveAspectRatio="none"
        role="img"
        aria-label={`${label}: ${report.sentences} sentences, ${report.shortest_sentence} to ${report.longest_sentence} words`}
      >
        {lengths.map((n, i) => {
          const h = Math.max(2, (Math.min(n, 50) / 50) * 62);
          const tone = n <= 8 ? "short" : n <= 20 ? "medium" : "long";
          return <rect key={i} className={`bar-${tone}`} x={i * 8 + 1} y={64 - h} width={6} height={h} rx={1.5} />;
        })}
      </svg>
      <figcaption className="small muted">
        {label}: {report.sentences} sentences, mean {report.mean_sentence_words} words
      </figcaption>
    </figure>
  );
}

type View = "after" | "before" | "changes" | "source";

function Results({ result }: { result: StyleRewrite }) {
  const [view, setView] = useState<View>("after");
  const lock = result.fact_lock;
  const complete = lock.preserved === lock.total;
  const plain = () => toPlainText(result.after.blocks);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(plain());
      notify("success", "Rewritten text copied.");
    } catch {
      notify("error", "The browser did not allow copying. Use Download .txt instead.");
    }
  };
  const accepted = result.changes.filter((c) => c.accepted);
  const rejected = result.changes.filter((c) => !c.accepted);
  const views: [View, string][] = [
    ["after", "Rewritten"],
    ["before", "Original"],
    ["changes", `Changes (${accepted.length})`],
    ["source", "Markdown"],
  ];

  const sb = result.score_before;
  const sa = result.score_after;
  return (
    <>
      <Card title="Style score" className="score-card">
        <div className="score-layout">
          <Ring
            value={sa.total / 100}
            previous={sb.total / 100}
            tone={sa.total >= sb.total ? "success" : "warning"}
            center={`${sa.total.toFixed(0)}`}
            label={`Style score: ${sb.total.toFixed(1)} before, ${sa.total.toFixed(1)} after, out of 100`}
            size={156}
          />
          <div className="stack">
            <p className="metric score-values" data-testid="style-score">
              {sb.total.toFixed(1)} <span aria-hidden="true">→</span>
              <span className="visually-hidden"> to </span> {sa.total.toFixed(1)}
              <span className="small muted"> / 100</span>
            </p>
            <ul className="score-parts">
              {(
                [
                  ["Rhythm", "rhythm", "30%", "sentence-length variation, full at 0.60"],
                  ["Plain wording", "plain", "30%", "no stock phrases; zero at 20 per 1,000 words"],
                  ["Vocabulary", "vocabulary", "20%", "diversity, from 0.50 to 0.90"],
                  ["Facts kept", "facts", "20%", "share of facts preserved"],
                ] as const
              ).map(([name, key, weight, help]) => (
                <li key={key}>
                  <span className="score-part-name">
                    {name} <span className="muted small">({weight})</span>
                  </span>
                  <span className="score-bar" aria-hidden="true">
                    <span style={{ width: `${Math.round(sa[key] * 100)}%` }} />
                  </span>
                  <span className="small">
                    {Math.round(sb[key] * 100)}% → {Math.round(sa[key] * 100)}%
                  </span>
                  <span className="visually-hidden">: {help}</span>
                </li>
              ))}
            </ul>
            <p className="small muted">
              A weighted sum of the measurements below, with the formula shown. It describes the text; it is not an
              AI-detector result and not a probability of who or what wrote it.
            </p>
          </div>
        </div>
      </Card>
      <p className="small" data-testid="engine-used">
        <span className={`badge ${result.engine.kind === "model" ? "badge-success" : "badge-neutral"}`}>
          {result.engine.kind === "model" ? "Language model" : "Built-in rules"}
        </span>{" "}
        <span className="muted">{result.engine.note}</span>
      </p>
      <section className="bento" aria-label="Measurements before and after">
        {METRICS.map((m) => {
          const before = m.value(result.before);
          const after = m.value(result.after);
          const improved = m.better === "higher" ? after > before : after < before;
          const tone = before === after ? "primary" : improved ? "success" : "warning";
          return (
            <Card key={m.label} title={m.label} className="span-3 metric-card">
              <div className="metric-ring">
                <Ring
                  value={m.scale(after)}
                  previous={m.scale(before)}
                  tone={tone}
                  center={m.format(after)}
                  label={`${m.label}: ${m.format(before)} before, ${m.format(after)} after`}
                />
                <p className="metric">
                  {m.format(before)} <span aria-hidden="true">→</span>
                  <span className="visually-hidden"> to </span> {m.format(after)}
                </p>
              </div>
              <p className="small muted">{m.explain}</p>
              {before !== after && (
                <p className={`small ${improved ? "text-success" : "text-warning"}`}>
                  {improved ? "Improved" : "Changed"} ({m.better} is plainer prose)
                </p>
              )}
            </Card>
          );
        })}
        <Card title="Facts preserved" className="span-3 metric-card">
          <div className="metric-ring">
            <Ring
              value={lock.total ? lock.preserved / lock.total : 1}
              tone={complete ? "success" : "danger"}
              center={lock.total ? `${Math.round((100 * lock.preserved) / lock.total)}%` : "–"}
              label={`Facts preserved: ${lock.preserved} of ${lock.total}`}
            />
            <p className="metric" data-testid="fact-lock">
              {lock.preserved} / {lock.total}
            </p>
          </div>
          <p className="small muted">Numbers, dates, percentages, quotes, citations and links, compared exactly.</p>
          {lock.missing.length > 0 && <p className="small text-warning">Missing: {lock.missing.join(", ")}</p>}
        </Card>
      </section>
      <p className="small muted">
        {result.changed_sentences} sentence change(s) in {result.passes} pass(es)
        {result.rejected_changes > 0 && `; ${result.rejected_changes} change(s) rejected because they would have altered a fact`}.
        These are measurements of the text, not a prediction of who or what wrote it.
      </p>

      <Card title="Sentence rhythm" className="rhythm-card">
        <p className="small muted">
          One bar per sentence, in order. <span className="legend legend-short">8 words or fewer</span>{" "}
          <span className="legend legend-medium">9 to 20</span> <span className="legend legend-long">over 20</span>
        </p>
        <div className="grid-2">
          <SentenceBars report={result.before} label="Original" />
          <SentenceBars report={result.after} label="Rewritten" />
        </div>
      </Card>

      <Card
        title={`Document · ${result.source} · ${PERSONAS.find((p) => p.value === result.persona)?.label}`}
        actions={
          <div className="row wrap">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => saveBlob(new Blob([result.rewritten], { type: "text/markdown" }), "rewritten.md")}
            >
              Download .md
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => saveBlob(new Blob([plain()], { type: "text/plain" }), "rewritten.txt")}
            >
              Download .txt
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => saveBlob(new Blob([docxBytes(result.after.blocks)], { type: DOCX_TYPE }), "rewritten.docx")}
            >
              Download .docx
            </button>
            <button type="button" className="btn btn-secondary" onClick={copy}>
              Copy text
            </button>
          </div>
        }
      >
        <div className="tabs" role="tablist" aria-label="Document views">
          {views.map(([name, label]) => (
            <button
              key={name}
              role="tab"
              type="button"
              aria-selected={view === name}
              className={view === name ? "tab active" : "tab"}
              onClick={() => setView(name)}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="style-view" data-testid="style-view">
          {view === "after" && <FormattedDocument report={result.after} />}
          {view === "before" && <FormattedDocument report={result.before} />}
          {view === "source" && <pre className="style-source">{result.rewritten}</pre>}
          {view === "changes" && (
            <ol className="change-list">
              {[...accepted, ...rejected].map((c, i) => (
                <li key={i} className={c.accepted ? "" : "change-rejected"}>
                  <div className="row wrap">
                    {c.rules.map((r) => (
                      <Badge key={r} tone="info">
                        {r}
                      </Badge>
                    ))}
                    {!c.accepted && <Badge tone="warning">kept the original: would have changed a fact</Badge>}
                  </div>
                  <p>
                    <span className="visually-hidden">Before: </span>
                    <del>{c.before}</del>
                  </p>
                  <p>
                    <span className="visually-hidden">After: </span>
                    <ins>{c.after}</ins>
                  </p>
                </li>
              ))}
              {result.changes.length === 0 && <li className="muted">No sentence needed a change.</li>}
            </ol>
          )}
        </div>
      </Card>
    </>
  );
}

/** Measures prose style and rewrites it in a chosen voice without touching facts or Markdown
 *  structure (backend/app/services/style.py). Nothing is stored. */
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
  const [engineChoice, setEngineChoice] = useState<"auto" | "rules">("auto");
  const engine = useAiEngine(workspaceId);
  const ids = useId();

  const ready = mode === "text" ? text.trim().length > 0 : uploadId !== "";
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const source = mode === "text" ? { text } : { upload_id: uploadId };
    rewrite.mutate({ ...source, persona, ...(engineChoice === "rules" ? { engine: "rules" as const } : {}) });
  };

  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <h1>Style studio</h1>
          <p className="muted">
            Measure sentence rhythm, vocabulary and templated phrasing, then rewrite in a chosen voice. Headings,
            lists and quotes keep their place, and every number, date, quote and citation stays exactly as it was.
          </p>
        </div>
      </div>

      <Card title="Text">
        <form onSubmit={submit} className="stack">
          <div className="row wrap">
            <div className="versions" role="group" aria-label="Source">
              <button type="button" aria-pressed={mode === "text"} onClick={() => setMode("text")}>
                Paste text
              </button>
              <button type="button" aria-pressed={mode === "upload"} onClick={() => setMode("upload")}>
                Workspace document
              </button>
            </div>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => {
                setMode("text");
                setText(STYLE_SAMPLE);
              }}
            >
              Load synthetic sample
            </button>
          </div>
          {mode === "text" ? (
            <div className="field">
              <label htmlFor={`${ids}-text`}>Text to measure and rewrite</label>
              <textarea
                id={`${ids}-text`}
                rows={12}
                maxLength={MAX_CHARS}
                value={text}
                onChange={(e) => setText(e.target.value)}
                aria-describedby={`${ids}-count`}
                placeholder="Paste a report, article or Markdown draft (public or synthetic material only)."
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
          <label className="field">
            <span>Rewrite with</span>
            <select value={engineChoice} onChange={(e) => setEngineChoice(e.target.value as "auto" | "rules")}>
              <option value="auto">
                {engine.data?.live ? `Language model: ${engine.data.label} (checked by the fact lock)` : "Built-in rules (no model configured)"}
              </option>
              <option value="rules">Built-in rules only (deterministic, no model call)</option>
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
