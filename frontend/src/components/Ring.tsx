/** A radial gauge: the outer arc is the current value, the optional inner arc a comparison
 *  (for example the value before a rewrite). Values are fractions from 0 to 1; the caller
 *  supplies the text, so the gauge never invents a number. */
export function Ring({
  value,
  previous,
  tone = "primary",
  center,
  label,
  size = 112,
}: {
  value: number;
  previous?: number;
  tone?: "primary" | "success" | "warning" | "danger";
  center: string;
  label: string;
  size?: number;
}) {
  const clamp = (v: number) => Math.max(0, Math.min(1, Number.isFinite(v) ? v : 0));
  const outer = 50;
  const inner = 38;
  const arc = (r: number, v: number) => {
    const length = 2 * Math.PI * r;
    return { strokeDasharray: `${clamp(v) * length} ${length}` };
  };
  return (
    <svg className={`ring ring-${tone}`} width={size} height={size} viewBox="0 0 120 120" role="img" aria-label={label}>
      <circle className="ring-track" cx="60" cy="60" r={outer} />
      <circle className="ring-value" cx="60" cy="60" r={outer} style={arc(outer, value)} />
      {previous !== undefined && (
        <>
          <circle className="ring-track thin" cx="60" cy="60" r={inner} />
          <circle className="ring-previous" cx="60" cy="60" r={inner} style={arc(inner, previous)} />
        </>
      )}
      <text x="60" y="60" className="ring-center" textAnchor="middle" dominantBaseline="central" aria-hidden="true">
        {center}
      </text>
    </svg>
  );
}
