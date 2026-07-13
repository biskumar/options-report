import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { isTradingBlocked } from '../components/ConnectionBanner';
import { OrderConfirmModal } from '../components/OrderConfirmModal';
import { TickerSidebar } from '../components/TickerSidebar';
import { useLiveData } from '../state/LiveDataContext';
import { api } from '../utils/api';
import { filterNextTwoMonths } from '../utils/dates';
import { formatMoney } from '../utils/format';

export function OrderTicket() {
  const [params] = useSearchParams();
  const liveData = useLiveData();
  const blocked = isTradingBlocked(liveData);

  const [expiryOptions, setExpiryOptions] = useState([]);
  const [spot, setSpot] = useState(null);
  const [theme, setTheme] = useState(() => localStorage.getItem('strategyTheme') || 'light');
  const [form, setForm] = useState({
    symbol: params.get('symbol') || '',
    expiry: params.get('expiry') || '',
    strike: params.get('strike') || '',
    right: params.get('right') || 'C',
    side: 'buy',
    quantity: 1,
    orderType: 'limit',
    limitPrice: '',
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

  // Polls the single-leg recommendation inbox (POST
  // /api/recommendations/single-leg -- meant to be pushed to from a
  // separate options-analyzer session/process) and auto-fills the form
  // the moment one arrives, then marks it consumed so it doesn't
  // reappear. Never previews or submits anything itself -- Preview order
  // / Confirm & Submit below are still manual.
  useEffect(() => {
    let cancelled = false;
    function poll() {
      api.get('/api/recommendations/single-leg')
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
            orderType: rec.orderType,
            limitPrice: rec.limitPrice != null ? String(rec.limitPrice) : '',
            stopPrice: rec.stopPrice != null ? String(rec.stopPrice) : '',
          });
          setRecNotice({ symbol: rec.symbol, source: rec.source, note: rec.note, receivedAt: rec.receivedAt });
          api.post(`/api/recommendations/single-leg/${rec.id}/consume`).catch(() => {});
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

  // Populates the Expiry dropdown with real expiries for the chosen symbol,
  // filtered to the next 2 months so the list stays short and relevant --
  // same convention as Strategy Builder/Chain. Keeps the current expiry if
  // it's still in the fresh list (e.g. arriving here via a Chain deep link),
  // otherwise defaults to the nearest one.
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

  // Underlying spot price for the ticker header (e.g. "AAL $17.89"), same
  // /api/chain endpoint Chain.jsx uses for the same purpose. This is a
  // display-only value -- the option contract's own bid/ask/mid below is
  // fetched separately once a strike is picked.
  useEffect(() => {
    if (!form.symbol || !form.expiry) {
      setSpot(null);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      api.get(`/api/chain?symbol=${encodeURIComponent(form.symbol.toUpperCase())}&expiry=${form.expiry}`)
        .then((data) => { if (!cancelled) setSpot(data.spot ?? null); })
        .catch((e) => { if (!cancelled) setError(e.message); });
    }, 500);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [form.symbol, form.expiry]);

  // Live bid/ask/mid for the exact contract currently on the ticket, shown
  // next to the limit/stop price fields so you can see the real market
  // before typing a price guess -- reuses the combo quote endpoint with a
  // single leg since its net mid for one BUY leg is just that leg's mid.
  // This bootstrap fetch also has a server-side side effect: qualify_legs()
  // calls ib.reqTickersAsync() for the contract, which subscribes it on the
  // shared IB connection -- IB then keeps streaming ticks for it into
  // ib_service._on_tickers, which broadcasts them over the WebSocket keyed
  // by conId. The effect below picks those up for true push updates
  // instead of re-polling this endpoint.
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

  // Push-based update: whenever IBKR streams a new tick for this exact
  // contract, LiveDataContext stores it in `quotes` keyed by conId (see
  // ib_service._on_tickers / LiveDataContext's 'quote' reducer case).
  // Merge it into the displayed quote in place of polling. Only fires
  // while liveQuoteConId is set, i.e. after the bootstrap fetch resolves.
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
        orderType: form.orderType,
        limitPrice: form.limitPrice ? parseFloat(form.limitPrice) : null,
        stopPrice: form.stopPrice ? parseFloat(form.stopPrice) : null,
      };
      const data = await api.post('/api/orders/preview', body);
      setPreview(data);
    } catch (err) {
      setError(err.message);
    }
  }

  async function handleConfirm(previewId) {
    try {
      const data = await api.post('/api/orders/submit', { previewId });
      setResult(data);
      setPreview(null);
    } catch (err) {
      setError(err.message);
      setPreview(null);
    }
  }

  return (
    <div className="page">
      <h2>Order Ticket</h2>
      {error && <p className="warning">{error}</p>}
      {result && (
        <p className="tag">
          {result.dryRun ? 'DRY RUN — ' : ''}Order {result.status} {result.orderId ? `(id ${result.orderId})` : ''}
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

            <form onSubmit={handlePreview}>
            <div className="strategy-preset-form">
              <label>Symbol <input value={form.symbol} onChange={(e) => update('symbol', e.target.value.toUpperCase())} required /></label>
              <label>Expiry (next 2 months)
                <select value={form.expiry} onChange={(e) => update('expiry', e.target.value)} disabled={expiryOptions.length === 0} required>
                  {expiryOptions.length === 0 && <option value="">Select a symbol first…</option>}
                  {expiryOptions.map((exp) => <option key={exp} value={exp}>{exp}</option>)}
                </select>
              </label>
              <label>Strike <input type="number" step="0.5" value={form.strike} onChange={(e) => update('strike', e.target.value)} required /></label>
              <label>Right
                <button
                  type="button"
                  className="leg-right-pill"
                  onClick={() => update('right', form.right === 'C' ? 'P' : 'C')}
                >
                  {form.right === 'C' ? 'Call' : 'Put'}
                </button>
              </label>
              <label>Side
                <button
                  type="button"
                  className={`leg-pill ${form.side === 'buy' ? 'buy' : 'sell'}`}
                  onClick={() => update('side', form.side === 'buy' ? 'sell' : 'buy')}
                >
                  {form.side.toUpperCase()}
                </button>
              </label>
              <label>Quantity <input type="number" min="1" value={form.quantity} onChange={(e) => update('quantity', e.target.value)} required /></label>
              <label>Order type
                <select value={form.orderType} onChange={(e) => update('orderType', e.target.value)}>
                  <option value="market">Market</option>
                  <option value="limit">Limit</option>
                  <option value="stop">Stop</option>
                  <option value="stop_limit">Stop-limit</option>
                </select>
              </label>
              {(form.orderType === 'limit' || form.orderType === 'stop_limit') && (
                <>
                  <span className="live-net-mid">
                    {liveQuoteLoading
                      ? 'Current: …'
                      : liveQuoteError
                      ? 'Current: --'
                      : liveQuote
                      ? `Current: ${liveQuote.bid != null ? formatMoney(liveQuote.bid) : '--'} / ${liveQuote.ask != null ? formatMoney(liveQuote.ask) : '--'} (mid ${liveQuote.mid != null ? formatMoney(liveQuote.mid) : '--'})`
                      : 'Current: --'}
                  </span>
                  <label>Limit price
                    <div className="limit-price-row">
                      <input type="number" step="0.01" value={form.limitPrice} onChange={(e) => update('limitPrice', e.target.value)} required />
                      {liveQuote?.mid != null && (
                        <button type="button" onClick={() => update('limitPrice', liveQuote.mid.toFixed(2))}>Use</button>
                      )}
                    </div>
                  </label>
                </>
              )}
              {(form.orderType === 'stop' || form.orderType === 'stop_limit') && (
                <label>Stop price <input type="number" step="0.01" value={form.stopPrice} onChange={(e) => update('stopPrice', e.target.value)} required /></label>
              )}
            </div>

            <div className="strategy-footer">
              <button type="submit" className="confirm-btn" disabled={blocked}>Preview order</button>
              {blocked && <p className="warning">Trading is blocked — connect to IBKR and/or disengage the kill switch.</p>}
            </div>
            </form>
          </div>
        </div>
      </div>

      <OrderConfirmModal
        preview={preview}
        disabled={blocked}
        onConfirm={handleConfirm}
        onCancel={() => setPreview(null)}
      />
    </div>
  );
}
