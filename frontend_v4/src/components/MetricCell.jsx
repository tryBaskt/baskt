export const METRIC_EXPLANATIONS = {
  return: "The total percentage gain or loss over the selected period.",
  cagr: "The compounded annual growth rate: the constant yearly return that would produce the same result.",
  volatility: "How widely returns fluctuate, annualized. Higher values indicate less predictable performance.",
  direction: "Net market direction after leverage. Positive is net long; negative is net short.",
  alpha: "Return above or below what market exposure would predict. Positive alpha indicates outperformance.",
  beta: "Sensitivity to broad market moves. A beta of 1 moves with the market; above 1 is more reactive.",
  sharpe: "Risk-adjusted return per unit of volatility. Higher values indicate more return for the risk taken.",
  drawdown: "The largest percentage decline from a portfolio peak to a subsequent trough.",
  drawdownDuration: "How long the maximum drawdown lasted before the portfolio recovered from it.",
};

export default function MetricCell({ description, children }) {
  return (
    <div
      className="metric-tooltip"
      data-metric-tooltip={description}
      tabIndex={0}
      aria-description={description}
    >
      {children}
    </div>
  );
}
