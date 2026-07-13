export function GreeksBadge({ delta, gamma, theta, vega, impliedVolatility }) {
  return (
    <span className="greeks-badge">
      Δ {delta ?? '--'} · Γ {gamma ?? '--'} · Θ {theta ?? '--'} · V {vega ?? '--'} · IV {impliedVolatility ?? '--'}%
    </span>
  );
}
