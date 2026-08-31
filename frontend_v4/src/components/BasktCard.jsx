import { formatDate } from "../lib/format";

export default function BasktCard({ baskt, badge = "Baskt", onOpen }) {
  const visibility = baskt?.visibility === "PRIVATE" ? "PRIVATE" : "PUBLIC";

  return (
    <button
      className="baskt-card"
      type="button"
      onClick={() => onOpen?.(baskt.portfolio_id)}
    >
      <span className="baskt-card-badges">
        <span className="baskt-badge">{badge}</span>
        <span className={`visibility-pill ${visibility.toLowerCase()}`}>
          {visibility === "PRIVATE" ? "Private" : "Public"}
        </span>
      </span>
      <h3>{baskt.portfolio_name}</h3>
      <span className="baskt-card-owner">
        By {baskt.portfolio_owner_display_name || "Baskt member"}
      </span>
      <p>{baskt.description || "No description yet."}</p>
      <div className="baskt-meta">
        <span>Created <strong>{formatDate(baskt.created_at)}</strong></span>
        <span>Updated <strong>{formatDate(baskt.updated_at)}</strong></span>
      </div>
    </button>
  );
}
