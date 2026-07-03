export default function MetricCard({ label, value, detail, tone = "" }) {
  return (
    <section className={`metric-card${tone ? ` metric-card--${tone}` : ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {detail ? <small>{detail}</small> : null}
    </section>
  );
}
