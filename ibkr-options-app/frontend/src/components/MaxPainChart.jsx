// Bar chart of total option-writer pain per strike. Same hand-rolled SVG
// convention as PayoffChart.jsx (no charting library) so it inherits the
// light/dark theme via the surrounding .strategy-theme CSS variables.
export function MaxPainChart({ painTable, maxPain, spot, width = 640, height = 260 }) {
  if (!painTable || painTable.length === 0) return null;

  const padding = 36;
  const strikes = painTable.map((p) => p.strike);
  const lo = Math.min(...strikes);
  const hi = Math.max(...strikes);
  const maxVal = Math.max(...painTable.map((p) => p.pain), 1);

  const xScale = (strike) => padding + ((strike - lo) / (hi - lo || 1)) * (width - 2 * padding);
  const yScale = (pain) => (height - padding) - (pain / maxVal) * (height - 2 * padding);

  const barWidth = Math.max(2, ((width - 2 * padding) / painTable.length) * 0.7);

  return (
    <svg width={width} height={height} className="payoff-chart">
      <line
        x1={padding} y1={height - padding} x2={width - padding} y2={height - padding}
        style={{ stroke: 'var(--sb-border, #9ca3af)' }}
      />
      {painTable.map((p) => (
        <rect
          key={p.strike}
          x={xScale(p.strike) - barWidth / 2}
          y={yScale(p.pain)}
          width={barWidth}
          height={(height - padding) - yScale(p.pain)}
          style={{ fill: p.strike === maxPain ? 'var(--sb-accent, #6b2338)' : 'var(--sb-muted, #6b7280)' }}
          opacity={p.strike === maxPain ? 1 : 0.5}
        />
      ))}
      {spot != null && spot >= lo && spot <= hi && (
        <line
          x1={xScale(spot)} y1={padding} x2={xScale(spot)} y2={height - padding}
          style={{ stroke: 'var(--sb-muted, #6b7280)' }} strokeDasharray="3"
        />
      )}
      {maxPain != null && (
        <text
          x={xScale(maxPain)} y={padding - 8} textAnchor="middle"
          style={{ fill: 'var(--sb-accent, #6b2338)' }} fontSize="11" fontWeight="600"
        >
          Max Pain ${maxPain}
        </text>
      )}
      {spot != null && spot >= lo && spot <= hi && (
        <text
          x={xScale(spot)} y={height - padding + 14} textAnchor="middle"
          style={{ fill: 'var(--sb-muted, #6b7280)' }} fontSize="10"
        >
          spot ${spot}
        </text>
      )}
    </svg>
  );
}
