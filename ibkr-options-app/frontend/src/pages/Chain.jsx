import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { OptionChainTable } from '../components/OptionChainTable';
import { TickerSidebar } from '../components/TickerSidebar';
import { api } from '../utils/api';
import { formatMoney } from '../utils/format';

export function Chain() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const initialSymbol = searchParams.get('symbol') || '';
  const [symbol, setSymbol] = useState(initialSymbol);
  const [expiries, setExpiries] = useState([]);
  const [expiry, setExpiry] = useState('');
  const [chain, setChain] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [theme, setTheme] = useState(() => localStorage.getItem('strategyTheme') || 'light');

  function toggleTheme() {
    setTheme((t) => {
      const next = t === 'dark' ? 'light' : 'dark';
      localStorage.setItem('strategyTheme', next);
      return next;
    });
  }

  async function loadChain(sym, exp) {
    if (!sym || !exp) return;
    setLoading(true);
    setError(null);
    try {
      const data = await api.get(`/api/chain?symbol=${encodeURIComponent(sym)}&expiry=${exp}`);
      setChain(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function selectSymbol(sym) {
    if (!sym) return;
    setSymbol(sym);
    setError(null);
    setChain(null);
    setExpiries([]);
    setExpiry('');
    try {
      const data = await api.get(`/api/chain/expiries?symbol=${encodeURIComponent(sym)}`);
      setExpiries(data.expiries);
      const firstExpiry = data.expiries[0] || '';
      setExpiry(firstExpiry);
      if (firstExpiry) await loadChain(sym, firstExpiry);
    } catch (e) {
      setError(e.message);
    }
  }

  useEffect(() => {
    if (initialSymbol) selectSymbol(initialSymbol);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handleSelect(row) {
    const params = new URLSearchParams({
      symbol: chain.symbol,
      expiry: chain.expiry,
      strike: row.strike,
      right: row.right,
    });
    navigate(`/order?${params.toString()}`);
  }

  return (
    <div className="page">
      <h2>Option Chain</h2>
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
                {symbol} {chain ? formatMoney(chain.spot) : '--'}
              </p>
            )}

            <div className="chain-controls">
              {expiries.length > 0 && (
                <select
                  value={expiry}
                  onChange={(e) => {
                    setExpiry(e.target.value);
                    loadChain(symbol, e.target.value);
                  }}
                >
                  {expiries.map((e) => <option key={e} value={e}>{e}</option>)}
                </select>
              )}
              {expiry && <button onClick={() => loadChain(symbol, expiry)}>Refresh</button>}
            </div>

            {loading && <p className="payoff-note">Loading…</p>}
            {!symbol && <p className="payoff-note">Pick a ticker on the left to see its option chain.</p>}
            {chain && <OptionChainTable calls={chain.calls} puts={chain.puts} onSelect={handleSelect} />}
          </div>
        </div>
      </div>
    </div>
  );
}
