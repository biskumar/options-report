import { useEffect, useState } from 'react';
import { api } from '../utils/api';
import { formatMoney } from '../utils/format';

const FLOW_LABEL = {
  bull: <span className="text-positive">🟢 Bull</span>,
  bear: <span className="text-negative">🔴 Bear</span>,
  neutral: <span style={{ color: 'var(--text-muted)' }}>⚪ Neutral</span>,
};

export function UnusualWhales() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [fetchedAt, setFetchedAt] = useState(null);
  const [theme, setTheme] = useState(() => localStorage.getItem('strategyTheme') || 'light');

  function toggleTheme() {
    setTheme((t) => {
      const next = t === 'dark' ? 'light' : 'dark';
      localStorage.setItem('strategyTheme', next);
      return next;
    });
  }

  // Deliberately no caching here -- every mount (including a plain browser
  // refresh) re-fetches fresh flow/IV/GEX data from Unusual Whales, which
  // is the whole point of this screen.
  async function load() {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get('/api/unusualwhales/watchlist');
      setRows(data);
      setFetchedAt(new Date());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  return (
    <div className="page">
      <h2>🐳 Unusual Whales</h2>
      <p style={{ color: 'var(--text-muted)', marginTop: -8, marginBottom: 16 }}>
        Options flow, IV rank and GEX across your watchlist -- sourced live from Unusual Whales on every load.
      </p>
      {error && <p className="warning">{error}</p>}

      <div className="strategy-theme" data-theme={theme}>
        <div className="strategy-topbar">
          <button className="strategy-theme-toggle" onClick={toggleTheme}>
            {theme === 'dark' ? '☀️ Light' : '🌙 Dark'}
          </button>
        </div>

        <div style={{ padding: 20 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
            <button onClick={load} disabled={loading}>
              {loading ? 'Scanning…' : '↺ Refresh'}
            </button>
            {fetchedAt && !loading && (
              <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
                Last updated {fetchedAt.toLocaleTimeString()}
              </span>
            )}
          </div>

          {loading && rows.length === 0 && (
            <p style={{ color: 'var(--text-muted)' }}>Scanning watchlist for unusual flow… this can take a few seconds.</p>
          )}

          {!loading && rows.length > 0 && (
            <div style={{ overflowX: 'auto' }}>
              <table>
                <thead>
                  <tr>
                    <th>Ticker</th>
                    <th>Score</th>
                    <th>Flow</th>
                    <th>Call Prem.</th>
                    <th>Put Prem.</th>
                    <th>Sweeps</th>
                    <th>Blocks</th>
                    <th>IV Rank</th>
                    <th>GEX Regime</th>
                    <th>Call Wall</th>
                    <th>Put Wall</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.ticker}>
                      <td style={{ fontWeight: 600 }}>{r.ticker}</td>
                      <td>{r.error ? '--' : `${r.score}/4`}</td>
                      <td>{r.error ? '--' : (FLOW_LABEL[r.flowDir] || r.flowDir)}</td>
                      <td>{r.error ? '--' : formatMoney(r.callPremium)}</td>
                      <td>{r.error ? '--' : formatMoney(r.putPremium)}</td>
                      <td>{r.error ? '--' : r.sweepCount}</td>
                      <td>{r.error ? '--' : r.blockCount}</td>
                      <td>{r.error || r.ivRank == null ? '--' : r.ivRank}</td>
                      <td style={{ maxWidth: 220, whiteSpace: 'normal', fontSize: '0.85rem' }}>
                        {r.error ? <span style={{ color: 'var(--negative)' }}>error: {r.error}</span> : (r.gexRegime || '--')}
                      </td>
                      <td>{r.error || r.callWall == null ? '--' : formatMoney(r.callWall)}</td>
                      <td>{r.error || r.putWall == null ? '--' : formatMoney(r.putWall)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: 16 }}>
            Score (0-4): 2+ qualifying sweep/block alerts, IV rank &gt; 60, single-leg (non-spread) flow available,
            and a non-neutral flow direction each add one point. Sorted highest score first.
          </p>
        </div>
      </div>
    </div>
  );
}
