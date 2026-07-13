import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useLiveData } from '../state/LiveDataContext';
import { api } from '../utils/api';
import { formatMoney } from '../utils/format';

function UsWatchlist() {
  const navigate = useNavigate();
  const { connection } = useLiveData();
  const [rows, setRows] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setRows(await api.get('/api/watchlist/us'));
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const allBlank = !error && !loading && rows.length > 0 && rows.every((r) => r.last === null);

  return (
    <>
      <h3>US Watchlist</h3>
      {error && <p className="warning">{error}</p>}
      {allBlank && connection.status !== 'connected' && (
        <p className="payoff-note">Connect to IBKR to see live prices — showing symbols only.</p>
      )}
      {allBlank && connection.status === 'connected' && (
        <p className="payoff-note">Connected, but no live price data came back — check that this account has a US market data subscription (or delayed data enabled) in IBKR.</p>
      )}
      <button onClick={load} disabled={loading}>Refresh</button>
      <table>
        <thead>
          <tr><th>Symbol</th><th>Name</th><th>Last</th><th>Change</th><th>Change %</th></tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.symbol} className="chain-row" onClick={() => navigate(`/chain?symbol=${encodeURIComponent(r.symbol)}`)}>
              <td>{r.symbol}</td>
              <td>{r.name}</td>
              <td>{r.last != null ? formatMoney(r.last) : '--'}</td>
              <td className={r.change > 0 ? 'text-positive' : r.change < 0 ? 'text-negative' : ''}>
                {r.change != null ? formatMoney(r.change) : '--'}
              </td>
              <td className={r.changePct > 0 ? 'text-positive' : r.changePct < 0 ? 'text-negative' : ''}>
                {r.changePct != null ? `${r.changePct}%` : '--'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function NseWatchlist() {
  const navigate = useNavigate();
  const [rows, setRows] = useState([]);
  const [fetchedAt, setFetchedAt] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  async function load(refresh = false) {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get(`/api/watchlist${refresh ? '?refresh=true' : ''}`);
      setRows(data.results || []);
      setFetchedAt(data.fetchedAt);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <>
      <h3>NSE Morning Scan</h3>
      {error && <p className="warning">{error}</p>}
      {fetchedAt && <p className="payoff-note">Last computed: {new Date(fetchedAt * 1000).toLocaleString()}</p>}
      {loading && <p>Loading — the first computation after a cold start can take a few minutes (scans ~60 symbols), cached for 15 minutes after that…</p>}

      <button onClick={() => load(true)} disabled={loading}>Force refresh</button>

      <table>
        <thead>
          <tr><th>Symbol</th><th>Price</th><th>Change</th><th>Score</th><th>RSI</th><th>Trend</th><th>Setup</th><th>SL</th><th>Target</th></tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={`${r.Symbol}-${i}`} className="chain-row" onClick={() => navigate(`/chain?symbol=${encodeURIComponent(r.Symbol)}`)}>
              <td>{r.Symbol}</td>
              <td>{r.Price}</td>
              <td>{r.Change}</td>
              <td>{r.Score ?? r._score}</td>
              <td>{r.RSI}</td>
              <td>{r.Trend}</td>
              <td>{r.Setup}</td>
              <td>{r.SL}</td>
              <td>{r.Target}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

export function Watchlist() {
  return (
    <div className="page">
      <h2>Watchlist</h2>
      <UsWatchlist />
      <NseWatchlist />
    </div>
  );
}
