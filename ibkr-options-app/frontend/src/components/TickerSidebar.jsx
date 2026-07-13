import { useEffect, useState } from 'react';
import { api } from '../utils/api';
import { formatMoney } from '../utils/format';

// Shared ticker rail used by Strategy Builder/Chain/Order Ticket/Bracket
// Order. Fetches /api/watchlist/us (async, not the bare /us/tickers list)
// so each symbol shows its live last price next to it -- same one-shot
// snapshot-then-cancel endpoint the Watchlist page already uses, so this
// doesn't leave 37 persistent market-data subscriptions open the way the
// per-contract order-ticket quotes intentionally do.
export function TickerSidebar({ activeSymbol, onSelect, onError }) {
  const [tickers, setTickers] = useState([]);

  useEffect(() => {
    api.get('/api/watchlist/us')
      .then((data) => setTickers([...data].sort((a, b) => a.symbol.localeCompare(b.symbol))))
      .catch((e) => onError?.(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <aside className="strategy-sidebar">
      {tickers.map((t) => (
        <button
          key={t.symbol}
          className={activeSymbol === t.symbol ? 'active' : ''}
          onClick={() => onSelect(t.symbol)}
        >
          <span>{t.symbol}</span>
          <span className="ticker-price">{t.last != null ? formatMoney(t.last) : '--'}</span>
        </button>
      ))}
    </aside>
  );
}
