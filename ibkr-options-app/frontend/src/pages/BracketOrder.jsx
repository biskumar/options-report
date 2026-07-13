import { useEffect, useState } from 'react';
import { isTradingBlocked } from '../components/ConnectionBanner';
import { BracketConfirmModal } from '../components/BracketConfirmModal';
import { TickerSidebar } from '../components/TickerSidebar';
import { useLiveData } from '../state/LiveDataContext';
import { api } from '../utils/api';
import { filterNextTwoMonths } from '../utils/dates';
import { formatMoney } from '../utils/format';

export function BracketOrder() {
  const liveData = useLiveData();
  const blocked = isTradingBlocked(liveData);

  const [expiryOptions, setExpiryOptions] = useState([]);
  const [strikeOptions, setStrikeOptions] = useState([]);
  const [spot, setSpot] = useState(null);
  const [theme, setTheme] = useState(() => localStorage.getItem('strategyTheme') || 'light');
  const [form, setForm] = useState({
    symbol: '',
    expiry: '',
    strike: '',
    right: 'C',
    side: 'buy',
    quantity: 1,
    entryLimitPrice: '',
    targetLimitPrice: '',
    stopPrice: '',
  });
  const [preview, setPreview] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [recNotice, setRecNotice] = useState(null);
  const [liveQuote, setLiveQuote] = useState(null);
  const [liveQuoteConId, setLiveQuoteConId] = useState(null);
  const [liveQuoteLoading, setLiveQuoteLoading] = useState(false);
  const [liveQuoteError, setLiveQuoteError] = useState(null);

  function toggleTheme() {
    setTheme((t) => {
      const next = t === 'dark' ? 'light' : 'dark';
      localStorage.setItem('strategyTheme', next);
      return next;
    });
  }

  function update(field, value) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  // Polls the recommendation inbox (POST /api/recommendations -- meant to
  // be pushed to from a separate options-analyzer session/process) and
  // auto-fills the form the moment one arrives, then marks it consumed so
  // it doesn't reappear. This never previews or submits anything by
  // itself -- Preview bracket order / Confirm & Submit below are still
  // manual, so a bad or unwanted recommendation just sits in the form
  // until you either edit it or navigate away.
  useEffect(() => {
    let cancelled = false;
    function poll() {
      api.get('/api/recommendations')
        .then((recs) => {
          if (cancelled || recs.length === 0) return;
          const rec = recs[0];
          setForm({
            symbol: rec.symbol,
            expiry: rec.expiry,
            strike: String(rec.strike),
            right: rec.right,
            side: rec.side,
            quantity: rec.quantity,
            entryLimitPrice: String(rec.entryLimitPrice),
            targetLimitPrice: String(rec.targetLimitPrice),
            stopPrice: String(rec.stopPrice),
          });
          setRecNotice({ symbol: rec.symbol, source: rec.source, note: rec.note, receivedAt: rec.receivedAt });
          api.post(`/api/recommendations/${rec.id}/consume`).catch(() => {});
        })
        .catch(() => {}); // silent -- a background poll shouldn't spam the error banner
    }
    poll();
    const interval = setInterval(poll, 5000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  // Populates the Expiry dropdown with real expiries for the chosen
  // symbol, filtered to the next 2 months -- same convention as Strategy
  // Builder/Chain/Order Ticket. Keeps the current expiry if it's still in
  // the fresh list, otherwise defaults to the nearest one.
  useEffect(() => {
    if (!form.symbol) {
      setExpiryOptions([]);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      api.get(`/api/chain/expiries?symbol=${encodeURIComponent(form.symbol.toUpperCase())}`)
        .then((data) => {
          if (cancelled) return;
          const nearTerm = filterNextTwoMonths(data.expiries);
          setExpiryOptions(nearTerm);
          setForm((f) => (nearTerm.includes(f.expiry) ? f : { ...f, expiry: nearTerm[0] || '' }));
        })
        .catch((e) => { if (!cancelled) setError(e.message); });
    }, 500);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [form.symbol]);

  // Populates the Strike dropdown with the 3 strikes closest to the
  // current spot, shared between Call and Put (the option chain uses the
  // same strike ladder for both) -- lets you pick a strike instead of
  // guessing a number. Also captures the underlying's spot price for the
  // ticker header (same /api/chain response, no extra request). Refetches
  // whenever symbol or expiry changes; not tied to Right, since neither
  // the closest strikes nor spot depend on it. Whatever strike is already
  // set (e.g. just loaded from a recommendation) is preserved in the list
  // even if it isn't one of the 3 closest to spot, instead of being
  // silently overwritten.
  useEffect(() => {
    if (!form.symbol || !form.expiry) {
      setStrikeOptions([]);
      setSpot(null);
      return;
    }
    let cancelled = false;
    const desiredStrike = parseFloat(form.strike);
    const timer = setTimeout(() => {
      api.get(`/api/chain?symbol=${encodeURIComponent(form.symbol.toUpperCase())}&expiry=${form.expiry}`)
        .then((data) => {
          if (cancelled) return;
          const spotPrice = data.spot;
          setSpot(spotPrice ?? null);
          const allStrikes = [...new Set([...data.calls, ...data.puts].map((r) => r.strike))];
          const closest = spotPrice != null
            ? allStrikes.sort((a, b) => Math.abs(a - spotPrice) - Math.abs(b - spotPrice)).slice(0, 3).sort((a, b) => a - b)
            : allStrikes.slice(0, 3);
          const options = !Number.isNaN(desiredStrike) && allStrikes.includes(desiredStrike) && !closest.includes(desiredStrike)
            ? [...closest, desiredStrike].sort((a, b) => a - b)
            : closest;
          setStrikeOptions(options);
          setForm((f) => (options.includes(parseFloat(f.strike)) ? f : { ...f, strike: options[0] ?? '' }));
        })
        .catch((e) => { if (!cancelled) setError(e.message); });
    }, 500);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [form.symbol, form.expiry]);

  // Live bid/ask/mid for the exact contract on the ticket, shown as a
  // reference before you set entry/target/stop -- same push-based
  // mechanism as Order Ticket: a debounced bootstrap fetch (which also
  // subscribes the contract on the shared IB connection) followed by a
  // merge of whatever IBKR streams afterward via the WebSocket, keyed by
  // conId. No polling.
  useEffect(() => {
    const strikeNum = parseFloat(form.strike);
    if (!form.symbol || !form.expiry || Number.isNaN(strikeNum)) {
      setLiveQuote(null);
      setLiveQuoteConId(null);
      setLiveQuoteError(null);
      return;
    }

    let cancelled = false;
    setLiveQuoteLoading(true);
    setLiveQuoteError(null);
    const timer = setTimeout(() => {
      api.post('/api/orders/combo/quote', {
        symbol: form.symbol.toUpperCase(),
        legs: [{ expiry: form.expiry, strike: strikeNum, right: form.right, action: 'BUY', ratio: 1 }],
      })
        .then((data) => {
          if (cancelled) return;
          setLiveQuote({ bid: data.legs[0]?.bid, ask: data.legs[0]?.ask, mid: data.netMid });
          setLiveQuoteConId(data.legs[0]?.conId ?? null);
        })
        .catch((e) => { if (!cancelled) setLiveQuoteError(e.message); })
        .finally(() => { if (!cancelled) setLiveQuoteLoading(false); });
    }, 500);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [form.symbol, form.expiry, form.strike, form.right]);

  useEffect(() => {
    if (liveQuoteConId == null) return;
    const pushed = liveData.quotes[liveQuoteConId];
    if (!pushed) return;
    setLiveQuote((prev) => {
      const bid = pushed.bid != null ? pushed.bid : prev?.bid ?? null;
      const ask = pushed.ask != null ? pushed.ask : prev?.ask ?? null;
      const mid = bid != null && ask != null ? (bid + ask) / 2 : prev?.mid ?? null;
      return { bid, ask, mid };
    });
  }, [liveData.quotes, liveQuoteConId]);

  async function handlePreview(e) {
    e.preventDefault();
    setError(null);
    setResult(null);
    try {
      const body = {
        symbol: form.symbol,
        expiry: form.expiry,
        strike: parseFloat(form.strike),
        right: form.right,
        side: form.side,
        quantity: parseInt(form.quantity, 10),
        entryLimitPrice: parseFloat(form.entryLimitPrice),
        targetLimitPrice: parseFloat(form.targetLimitPrice),
        stopPrice: parseFloat(form.stopPrice),
      };
      const data = await api.post('/api/orders/bracket/preview', body);
      setPreview(data);
    } catch (err) {
      setError(err.message);
    }
  }

  async function handleConfirm(previewId) {
    try {
      const data = await api.post('/api/orders/bracket/submit', { previewId });
      setResult(data);
      setPreview(null);
    } catch (err) {
      setError(err.message);
      setPreview(null);
    }
  }

  return (
    <div className="page">
      <h2>Bracket Order</h2>
      {error && <p className="warning">{error}</p>}
      {result && (
        <p className="tag">
          {result.dryRun ? 'DRY RUN — ' : ''}Order {result.status}
          {result.orderIds ? ` (ids ${result.orderIds.join(', ')})` : ''}
        </p>
      )}
      {recNotice && (
        <p className="tag">
          Loaded recommendation for {recNotice.symbol}{recNotice.source ? ` from ${recNotice.source}` : ''} at{' '}
          {new Date(recNotice.receivedAt).toLocaleTimeString()}
          {recNotice.note ? ` — ${recNotice.note}` : ''} — review before submitting
        </p>
      )}

      <div className="strategy-theme" data-theme={theme}>
        <div className="strategy-topbar">
          <button className="strategy-theme-toggle" onClick={toggleTheme}>
            {theme === 'dark' ? '☀️ Light' : '🌙 Dark'}
          </button>
        </div>

        <div className="strategy-layout">
          <TickerSidebar activeSymbol={form.symbol} onSelect={(sym) => update('symbol', sym)} onError={setError} />

          <div className="strategy-main">
            {form.symbol && (
              <p className="strategy-ticker-header">
                {form.symbol} {spot != null ? formatMoney(spot) : '--'}
              </p>
            )}
            <p className="payoff-note">
              Places one linked group: an entry limit order, plus a take-profit limit and a stop-loss, both attached
              to the entry. Whichever exit fills first cancels the other. All legs are DAY orders.
            </p>

            <form onSubmit={handlePreview}>
              <div className="strategy-preset-form">
                <label>Symbol <input value={form.symbol} onChange={(e) => update('symbol', e.target.value.toUpperCase())} required /></label>
                <label>Expiry (next 2 months)
                  <select value={form.expiry} onChange={(e) => update('expiry', e.target.value)} disabled={expiryOptions.length === 0} required>
                    {expiryOptions.length === 0 && <option value="">Select a symbol first…</option>}
                    {expiryOptions.map((exp) => <option key={exp} value={exp}>{exp}</option>)}
                  </select>
                </label>
                <label>Strike (3 closest)
                  <select value={form.strike} onChange={(e) => update('strike', e.target.value)} disabled={strikeOptions.length === 0} required>
                    {strikeOptions.length === 0 && <option value="">Select expiry first…</option>}
                    {strikeOptions.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                </label>
                <label>Right
                  <button
                    type="button"
                    className="leg-right-pill"
                    onClick={() => update('right', form.right === 'C' ? 'P' : 'C')}
                  >
                    {form.right === 'C' ? 'Call' : 'Put'}
                  </button>
                </label>
                <label>Side (entry)
                  <button
                    type="button"
                    className={`leg-pill ${form.side === 'buy' ? 'buy' : 'sell'}`}
                    onClick={() => update('side', form.side === 'buy' ? 'sell' : 'buy')}
                  >
                    {form.side.toUpperCase()}
                  </button>
                </label>
                <label>Quantity <input type="number" min="1" value={form.quantity} onChange={(e) => update('quantity', e.target.value)} required /></label>
              </div>

              <div className="strategy-preset-form">
                <span className="live-net-mid">
                  {liveQuoteLoading
                    ? 'Current: …'
                    : liveQuoteError
                    ? 'Current: --'
                    : liveQuote
                    ? `Current: ${liveQuote.bid != null ? formatMoney(liveQuote.bid) : '--'} / ${liveQuote.ask != null ? formatMoney(liveQuote.ask) : '--'} (mid ${liveQuote.mid != null ? formatMoney(liveQuote.mid) : '--'})`
                    : 'Current: --'}
                </span>
              </div>

              <div className="strategy-preset-form">
                <label>Entry limit price
                  <div className="limit-price-row">
                    <input type="number" step="0.01" value={form.entryLimitPrice} onChange={(e) => update('entryLimitPrice', e.target.value)} required />
                    {liveQuote?.mid != null && (
                      <button type="button" onClick={() => update('entryLimitPrice', liveQuote.mid.toFixed(2))}>Use</button>
                    )}
                  </div>
                </label>
                <label>Target limit price (profit) <input type="number" step="0.01" value={form.targetLimitPrice} onChange={(e) => update('targetLimitPrice', e.target.value)} required /></label>
                <label>Stop price (loss) <input type="number" step="0.01" value={form.stopPrice} onChange={(e) => update('stopPrice', e.target.value)} required /></label>
              </div>

              <div className="strategy-footer">
                <button type="submit" className="confirm-btn" disabled={blocked}>Preview bracket order</button>
                {blocked && <p className="warning">Trading is blocked — connect to IBKR and/or disengage the kill switch.</p>}
              </div>
            </form>
          </div>
        </div>
      </div>

      <BracketConfirmModal
        preview={preview}
        disabled={blocked}
        onConfirm={handleConfirm}
        onCancel={() => setPreview(null)}
      />
    </div>
  );
}
