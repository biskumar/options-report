import { useState } from 'react';
import { MaxPainChart } from '../components/MaxPainChart';
import { TickerSidebar } from '../components/TickerSidebar';
import { api } from '../utils/api';
import { filterNextTwoMonths } from '../utils/dates';
import { formatMoney } from '../utils/format';

const DIRECTION_LABEL = {
  PULL_UP: '🟢 Pull Up',
  PULL_DOWN: '🔴 Pull Down',
  PINNED: '⚪ Pinned',
};

export function MaxPain() {
  const [symbol, setSymbol] = useState('');
  const [expiries, setExpiries] = useState([]);
  const [expiry, setExpiry] = useState('');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [theme, setTheme] = useState(() => localStorage.getItem('strategyTheme') || 'light');

  function toggleTheme() {
    setTheme((t) => {
      const next = t === 'dark' ? 'light' : 'dark';
      localStorage.setItem('strategyTheme', next);
      return next;
    });
  }

  async function selectSymbol(sym) {
    if (!sym) return;
    setSymbol(sym);
    setError(null);
    setData(null);
    setExpiries([]);
    setExpiry('');
    try {
      const res = await api.get(`/api/chain/expiries?symbol=${encodeURIComponent(sym)}`);
      const filtered = filterNextTwoMonths(res.expiries);
      const list = filtered.length ? filtered : res.expiries;
      setExpiries(list);
      const first = list[0] || '';
      setExpiry(first);
      if (first) await loadMaxPain(sym, first);
    } catch (e) {
      setError(e.message);
    }
  }

  async function loadMaxPain(sym, exp) {
    if (!sym || !exp) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api.get(`/api/maxpain?symbol=${encodeURIComponent(sym)}&expiry=${exp}`);
      setData(res);
    } catch (e) {
      setError(e.message);
      setData(null);
    } finally {
      setLoading(false);
    }
  }

  async function handleExpiryChange(exp) {
    setExpiry(exp);
    setData(null);
    if (symbol) await loadMaxPain(symbol, exp);
  }

  return (
    <div className="page">
      <h2>🧲 Max Pain</h2>
      <p style={{ color: 'var(--text-muted)', marginTop: -8, marginBottom: 16 }}>
        The strike where option writers lose the least at expiry -- price tends to gravitate here as expiry approaches.
      </p>
      {error && <p className="warning">{error}</p>}

      <div className="strategy-theme" data-theme={theme}>
        <div className="strategy-topbar">
          <button className="strategy-theme-toggle" onClick={toggleTheme}>
            {theme === 'dark' ? '☀️ Light' : '🌙 Dark'}
          </button>
        </div>

        <div className="strategy-layout">
          <TickerSidebar activeSymbol={symbol} onSelect={selectSymbol} onError={setError} />

          <div className="strategy-main">
            {symbol && (
              <p className="strategy-ticker-header">
                {symbol} {data?.spot != null ? formatMoney(data.spot) : '--'}
              </p>
            )}

            {expiries.length > 0 && (
              <div className="chain-controls" style={{ marginBottom: 16 }}>
                <label style={{ fontWeight: 600, marginRight: 8 }}>Expiry</label>
                <select
                  value={expiry}
                  onChange={(e) => handleExpiryChange(e.target.value)}
                  className="chain-expiry-select"
                >
                  {expiries.map((e) => <option key={e} value={e}>{e}</option>)}
                </select>
              </div>
            )}

            {loading && <p style={{ color: 'var(--text-muted)' }}>Loading open interest…</p>}

            {data && !loading && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 20, maxWidth: 720 }}>
                <div style={{
                  background: 'var(--surface)',
                  border: '2px solid var(--border)',
                  borderRadius: 10,
                  padding: '20px 24px',
                  textAlign: 'center',
                }}>
                  <div style={{ fontSize: '0.9rem', color: 'var(--text-muted)', marginBottom: 6, fontWeight: 600, letterSpacing: '0.05em', textTransform: 'uppercase' }}>
                    Max Pain
                  </div>
                  <div style={{ fontSize: '2.2rem', fontWeight: 700 }}>
                    {data.maxPain != null ? formatMoney(data.maxPain) : '--'}
                  </div>
                  {data.direction && (
                    <div style={{ fontSize: '1rem', fontWeight: 600, marginTop: 4 }}>
                      {DIRECTION_LABEL[data.direction] || data.direction}
                      {data.distancePct != null && (
                        <span style={{ fontWeight: 400, color: 'var(--text-muted)' }}> ({data.distancePct >= 0 ? '+' : ''}{data.distancePct}% from spot)</span>
                      )}
                    </div>
                  )}
                  {data.signal && (
                    <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginTop: 8 }}>{data.signal}</div>
                  )}
                </div>

                <MaxPainChart painTable={data.painTable} maxPain={data.maxPain} spot={data.spot} />

                <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
                  <div>
                    <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>Total Call OI</div>
                    <div style={{ fontWeight: 600 }}>{data.totalCallOI?.toLocaleString() ?? '--'}</div>
                  </div>
                  <div>
                    <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>Total Put OI</div>
                    <div style={{ fontWeight: 600 }}>{data.totalPutOI?.toLocaleString() ?? '--'}</div>
                  </div>
                  <div>
                    <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>Put/Call Ratio</div>
                    <div style={{ fontWeight: 600 }}>{data.pcr ?? '--'}</div>
                  </div>
                </div>

                <div style={{ display: 'flex', gap: 32, flexWrap: 'wrap' }}>
                  {data.callWalls?.length > 0 && (
                    <div>
                      <div style={{ fontWeight: 600, marginBottom: 6 }}>Call Walls</div>
                      {data.callWalls.map((w) => (
                        <div key={w.strike} style={{ fontSize: '0.9rem', color: 'var(--text-muted)' }}>
                          ${w.strike} · OI {w.openInterest.toLocaleString()}
                        </div>
                      ))}
                    </div>
                  )}
                  {data.putWalls?.length > 0 && (
                    <div>
                      <div style={{ fontWeight: 600, marginBottom: 6 }}>Put Walls</div>
                      {data.putWalls.map((w) => (
                        <div key={w.strike} style={{ fontSize: '0.9rem', color: 'var(--text-muted)' }}>
                          ${w.strike} · OI {w.openInterest.toLocaleString()}
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                  Based on open interest across strikes within the selected window, sourced live from IBKR -- not a guarantee, just where market makers currently have the least incentive to move price away from.
                </p>
              </div>
            )}

            {!symbol && (
              <p style={{ color: 'var(--text-muted)', marginTop: 40 }}>Select a ticker from the sidebar to begin.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
