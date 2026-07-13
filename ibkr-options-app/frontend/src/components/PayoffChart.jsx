// Pure rendering of pre-computed P&L curves -- all the math (today vs
// at-expiry valuation, breakevens, max profit/loss) lives in
// utils/optionMath.js so the parent can show the same numbers in stat
// cards that this chart draws. Colors are read from the surrounding
// .strategy-theme CSS variables (via inline style, not attributes) so the
// chart automatically follows the light/dark toggle.

export function PayoffChart({ curveToday, curveAtExpiry, activeMode, breakevens = [], currentSpot, width = 560, height = 260 }) {
  if (!curveToday || !curveAtExpiry || curveToday.length === 0) return null;

  const padding = 30;
  const spots = curveToday.map((p) => p.spot);
  const lo = Math.min(...spots);
  const hi = Math.max(...spots);
  const allPnls = [...curveToday, ...curveAtExpiry].map((p) => Math.abs(p.pnl));
  const maxPnl = Math.max(...allPnls, 1);

  const xScale = (spot) => padding + ((spot - lo) / (hi - lo || 1)) * (width - 2 * padding);
  const yScale = (pnl) => height / 2 - (pnl / maxPnl) * (height / 2 - padding);

  const pathFor = (c) => c.map((p, i) => `${i === 0 ? 'M' : 'L'} ${xScale(p.spot)} ${yScale(p.pnl)}`).join(' ');

  return (
    <svg width={width} height={height} className="payoff-chart">
      <line
        x1={padding} y1={height / 2} x2={width - padding} y2={height / 2}
        style={{ stroke: 'var(--sb-border, #9ca3af)' }} strokeDasharray="4"
      />
      {breakevens.map((be, i) => be >= lo && be <= hi && (
        <g key={i}>
          <line
            x1={xScale(be)} y1={padding} x2={xScale(be)} y2={height - padding}
            style={{ stroke: 'var(--sb-muted, #6b7280)' }} strokeDasharray="3"
          />
          <text x={xScale(be) + 3} y={padding + 10} style={{ fill: 'var(--sb-muted, #6b7280)' }} fontSize="10">
            BE ${be.toFixed(0)}
          </text>
        </g>
      ))}
      {currentSpot != null && currentSpot >= lo && currentSpot <= hi && (
        <line
          x1={xScale(currentSpot)} y1={padding} x2={xScale(currentSpot)} y2={height - padding}
          style={{ stroke: 'var(--sb-muted, #6b7280)' }} strokeDasharray="2"
        />
      )}
      <path
        d={pathFor(curveAtExpiry)} fill="none" style={{ stroke: 'var(--sb-muted, #6b7280)' }}
        strokeWidth={activeMode === 'atExpiry' ? 2.5 : 1} strokeDasharray="4 3"
      />
      <path
        d={pathFor(curveToday)} fill="none" style={{ stroke: 'var(--sb-accent, #6b2338)' }}
        strokeWidth={activeMode === 'today' ? 2.5 : 1}
      />
    </svg>
  );
}
