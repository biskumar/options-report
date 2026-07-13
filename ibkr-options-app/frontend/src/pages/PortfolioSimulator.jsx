import { useEffect, useMemo, useState } from 'react';
import { TickerSidebar } from '../components/TickerSidebar';
import { api } from '../utils/api';
import { filterNextTwoMonths } from '../utils/dates';
import { blackScholes, daysToExpiryFromToday, syntheticIV } from '../utils/optionMath';
import { formatMoney } from '../utils/format';

function positionMultiplier(p) {
  return p.secType === 'OPT' ? p.quantity * 100 : p.quantity;
}

/** Full Black-Scholes reprice at a hypothetical spot/date -- this is what
 * makes delta+gamma+theta+vega all fall out correctly together, instead of
 * a linear greeks-sum approximation that only holds for small moves. */
function theoreticalPrice(p, pctChange, daysForward) {
  if (p.spot == null) return null;
  const newSpot = p.spot * (1 + pctChange / 100);
  if (p.secType === 'STK') return newSpot;
  const dteToday = daysToExpiryFromToday(p.expiry);
  const evalDte = Math.max(dteToday - daysForward, 0);
  if (evalDte <= 0) {
    return p.right === 'C' ? Math.max(newSpot - p.strike, 0) : Math.max(p.strike - newSpot, 0);
  }
  const iv = p.impliedVolatility > 0 ? p.impliedVolatility : syntheticIV(p.strike, p.spot);
  return blackScholes(newSpot, p.strike, evalDte / 365, iv, p.right).price;
}

/** $ P&L this position would show for a 1% move today -- a real,
 * greeks-derived exposure number (not a market "beta", which would need an
 * external fundamentals feed this app doesn't have). */
function deltaDollarsPerOnePercent(p) {
  if (p.spot == null) return 0;
  if (p.secType === 'STK') return p.spot * p.quantity * 0.01;
  const dteToday = daysToExpiryFromToday(p.expiry);
  let delta;
  if (dteToday <= 0) {
    delta = p.right === 'C' ? (p.spot > p.strike ? 1 : 0) : (p.spot < p.strike ? -1 : 0);
  } else {
    const iv = p.impliedVolatility > 0 ? p.impliedVolatility : syntheticIV(p.strike, p.spot);
    delta = blackScholes(p.spot, p.strike, dteToday / 365, iv, p.right).delta;
  }
  return delta * p.spot * p.quantity * 100 * 0.01;
}

function positionLabel(p) {
  if (p.secType === 'STK') return 'Stock';
  return `${p.strike}${p.right} · ${p.expiry}`;
}

export function PortfolioSimulator() {
  const [positions, setPositions] = useState([]);
  const [theme, setTheme] = useState(() => localStorage.getItem('strategyTheme') || 'light');
  const [error, setError] = useState(null);
  const [importing, setImporting] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  // Add-position form state
  const [symbol, setSymbol] = useState('');
  const [expiries, setExpiries] = useState([]);
  const [expiry, setExpiry] = useState('');
  const [chain, setChain] = useState(null);
  const [newPosType, setNewPosType] = useState('OPT');
  const [newRight, setNewRight] = useState('C');
  const [newStrike, setNewStrike] = useState('');
  const [newQty, setNewQty] = useState('1');
  const [newEntryInput, setNewEntryInput] = useState('');

  // Simulation sliders
  const [priceChangePct, setPriceChangePct] = useState(0);
  const [daysForward, setDaysForward] = useState(0);

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
    setChain(null);
    setExpiries([]);
    setExpiry('');
    setNewStrike('');
    try {
      const data = await api.get(`/api/chain/expiries?symbol=${encodeURIComponent(sym)}`);
      const filtered = filterNextTwoMonths(data.expiries);
      const list = filtered.length ? filtered : data.expiries;
      setExpiries(list);
      const first = list[0] || '';
      setExpiry(first);
      if (first) await loadChain(sym, first);
    } catch (e) {
      setError(e.message);
    }
  }

  async function loadChain(sym, exp) {
    if (!sym || !exp) return;
    setError(null);
    try {
      const data = await api.get(`/api/chain?symbol=${encodeURIComponent(sym)}&expiry=${exp}`);
      setChain(data);
      setNewStrike('');
    } catch (e) {
      setError(e.message);
    }
  }

  async function handleExpiryChange(exp) {
    setExpiry(exp);
    // Clear the old expiry's chain/strike immediately, not just after the
    // new one loads -- otherwise there's a window where the strike dropdown
    // still shows the previous expiry's strikes/spot while `expiry` state
    // has already moved on, letting a fast Add Position pair the new
    // expiry with stale strike/IV/spot data.
    setChain(null);
    setNewStrike('');
    if (symbol) await loadChain(symbol, exp);
  }

  const strikes = useMemo(() => {
    if (!chain) return [];
    const set = new Set([...chain.calls, ...chain.puts].map((r) => r.strike));
    return [...set].sort((a, b) => a - b);
  }, [chain]);

  const selectedRow = useMemo(() => {
    if (!chain || !newStrike) return null;
    const rows = newRight === 'C' ? chain.calls : chain.puts;
    return rows.find((r) => r.strike === Number(newStrike)) || null;
  }, [chain, newStrike, newRight]);

  const marketPremium = useMemo(() => {
    if (!selectedRow) return null;
    if (selectedRow.mid != null) return selectedRow.mid;
    if (selectedRow.bid != null && selectedRow.ask != null) return (selectedRow.bid + selectedRow.ask) / 2;
    return null;
  }, [selectedRow]);

  // Default the entry-price input to the market mid for options, or spot
  // for stock, whenever the thing being priced changes -- editable so the
  // user can match their actual fill.
  useEffect(() => {
    if (newPosType === 'OPT') {
      setNewEntryInput(marketPremium != null ? marketPremium.toFixed(2) : '');
    } else {
      setNewEntryInput(chain?.spot != null ? chain.spot.toFixed(2) : '');
    }
  }, [newPosType, marketPremium, chain]);

  function addPosition() {
    setError(null);
    const qty = parseInt(newQty, 10);
    const entryPrice = parseFloat(newEntryInput);
    if (!symbol) { setError('Select a ticker first.'); return; }
    if (!qty) { setError('Quantity must be a non-zero whole number (negative for short).'); return; }
    if (isNaN(entryPrice) || entryPrice < 0) { setError('Enter a valid entry price.'); return; }

    if (newPosType === 'OPT') {
      if (!expiry || !newStrike) { setError('Select an expiry and strike first.'); return; }
      setPositions((prev) => [...prev, {
        id: crypto.randomUUID(),
        symbol,
        secType: 'OPT',
        expiry,
        strike: Number(newStrike),
        right: newRight,
        quantity: qty,
        entryPrice,
        spot: chain?.spot ?? null,
        markPrice: marketPremium,
        impliedVolatility: selectedRow?.impliedVolatility ?? null,
      }]);
    } else {
      setPositions((prev) => [...prev, {
        id: crypto.randomUUID(),
        symbol,
        secType: 'STK',
        expiry: null,
        strike: null,
        right: null,
        quantity: qty,
        entryPrice,
        spot: chain?.spot ?? entryPrice,
        markPrice: chain?.spot ?? entryPrice,
        impliedVolatility: null,
      }]);
    }
  }

  function removePosition(id) {
    setPositions((prev) => prev.filter((p) => p.id !== id));
  }

  async function importPositions() {
    setImporting(true);
    setError(null);
    try {
      const raw = await api.get('/api/positions');
      const optRows = raw.filter((p) => p.secType === 'OPT' && p.position !== 0);
      const stkRows = raw.filter((p) => p.secType === 'STK' && p.position !== 0);

      const chainKeys = [...new Set(optRows.map((p) => `${p.symbol}|${p.expiry}`))];
      const chainMap = {};
      await Promise.all(chainKeys.map(async (key) => {
        const [sym, exp] = key.split('|');
        try {
          chainMap[key] = await api.get(`/api/chain?symbol=${encodeURIComponent(sym)}&expiry=${exp}`);
        } catch {
          chainMap[key] = null;
        }
      }));

      const imported = [];
      for (const p of optRows) {
        const chainData = chainMap[`${p.symbol}|${p.expiry}`];
        const rows = chainData ? (p.right === 'C' ? chainData.calls : chainData.puts) : [];
        const row = rows.find((r) => r.strike === p.strike);
        imported.push({
          id: crypto.randomUUID(),
          symbol: p.symbol,
          secType: 'OPT',
          expiry: p.expiry,
          strike: p.strike,
          right: p.right,
          quantity: p.position,
          entryPrice: p.avgCost / 100,
          spot: chainData?.spot ?? null,
          markPrice: p.marketPrice ?? row?.mid ?? null,
          impliedVolatility: row?.impliedVolatility ?? null,
        });
      }
      for (const p of stkRows) {
        imported.push({
          id: crypto.randomUUID(),
          symbol: p.symbol,
          secType: 'STK',
          expiry: null,
          strike: null,
          right: null,
          quantity: p.position,
          entryPrice: p.avgCost,
          spot: p.marketPrice ?? null,
          markPrice: p.marketPrice ?? null,
          impliedVolatility: null,
        });
      }
      if (imported.length === 0) {
        setError('No open IBKR positions found to import.');
      }
      setPositions((prev) => [...prev, ...imported]);
    } catch (e) {
      setError(e.message);
    } finally {
      setImporting(false);
    }
  }

  async function refreshMarks() {
    if (positions.length === 0) return;
    setRefreshing(true);
    setError(null);
    try {
      const optKeys = [...new Set(positions.filter((p) => p.secType === 'OPT').map((p) => `${p.symbol}|${p.expiry}`))];
      const chainMap = {};
      await Promise.all(optKeys.map(async (key) => {
        const [sym, exp] = key.split('|');
        try {
          chainMap[key] = await api.get(`/api/chain?symbol=${encodeURIComponent(sym)}&expiry=${exp}`);
        } catch {
          chainMap[key] = null;
        }
      }));
      let watchlist = null;
      if (positions.some((p) => p.secType === 'STK')) {
        watchlist = await api.get('/api/watchlist/us');
      }
      setPositions((prev) => prev.map((p) => {
        if (p.secType === 'OPT') {
          const chainData = chainMap[`${p.symbol}|${p.expiry}`];
          if (!chainData) return p;
          const rows = p.right === 'C' ? chainData.calls : chainData.puts;
          const row = rows.find((r) => r.strike === p.strike);
          return {
            ...p,
            spot: chainData.spot ?? p.spot,
            markPrice: row?.mid ?? p.markPrice,
            impliedVolatility: row?.impliedVolatility ?? p.impliedVolatility,
          };
        }
        const t = watchlist?.find((w) => w.symbol === p.symbol);
        return t?.last != null ? { ...p, spot: t.last, markPrice: t.last } : p;
      }));
    } catch (e) {
      setError(e.message);
    } finally {
      setRefreshing(false);
    }
  }

  const dteMaxToday = useMemo(() => {
    const dtes = positions.filter((p) => p.secType === 'OPT').map((p) => daysToExpiryFromToday(p.expiry));
    return dtes.length ? Math.max(...dtes) : 0;
  }, [positions]);

  const summary = useMemo(() => {
    let costBasis = 0, currentPL = 0, deltaExposure = 0, missingData = false;
    for (const p of positions) {
      const mult = positionMultiplier(p);
      costBasis += Math.abs(p.entryPrice * mult);
      const mark = p.markPrice ?? p.entryPrice;
      currentPL += (mark - p.entryPrice) * mult;
      if (p.spot == null) { missingData = true; continue; }
      deltaExposure += deltaDollarsPerOnePercent(p);
    }
    const currentReturnsPct = costBasis > 0 ? (currentPL / costBasis) * 100 : null;
    return { costBasis, currentPL, currentReturnsPct, deltaExposure, missingData };
  }, [positions]);

  const hasSimulated = priceChangePct !== 0 || daysForward !== 0;

  const projected = useMemo(() => {
    if (!hasSimulated || positions.length === 0) return null;
    let newPL = 0;
    for (const p of positions) {
      const mult = positionMultiplier(p);
      const theo = theoreticalPrice(p, priceChangePct, daysForward);
      const value = theo ?? p.entryPrice;
      newPL += (value - p.entryPrice) * mult;
    }
    const newReturnsPct = summary.costBasis > 0 ? (newPL / summary.costBasis) * 100 : null;
    const impliedChange = (newReturnsPct != null && summary.currentReturnsPct != null)
      ? newReturnsPct - summary.currentReturnsPct
      : null;
    return { newPL, newReturnsPct, impliedChange };
  }, [positions, priceChangePct, daysForward, hasSimulated, summary.costBasis, summary.currentReturnsPct]);

  function resetSliders() {
    setPriceChangePct(0);
    setDaysForward(0);
  }

  return (
    <div className="page">
      <h2>📈 Portfolio Simulator</h2>
      <p style={{ color: 'var(--text-muted)', marginTop: -8, marginBottom: 16 }}>
        See how market moves may impact your returns, then test strategies to help protect profits or minimize losses.
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
                {symbol} {chain?.spot ? formatMoney(chain.spot) : '--'}
              </p>
            )}

            {/* Step 1: Select positions */}
            <h3>1&nbsp;&nbsp;Select Positions</h3>

            <div style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
              <button onClick={importPositions} disabled={importing}>
                {importing ? 'Importing…' : 'Import IBKR Positions'}
              </button>
              <button onClick={refreshMarks} disabled={refreshing || positions.length === 0}>
                {refreshing ? 'Refreshing…' : 'Refresh Marks'}
              </button>
            </div>

            {symbol && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 640, marginBottom: 20 }}>
                <div style={{ display: 'flex', gap: 6 }}>
                  {['OPT', 'STK'].map((t) => (
                    <button
                      key={t}
                      onClick={() => setNewPosType(t)}
                      style={{
                        padding: '6px 16px',
                        borderRadius: 6,
                        background: newPosType === t ? 'var(--primary)' : 'var(--surface)',
                        color: newPosType === t ? '#fff' : 'var(--text)',
                      }}
                    >
                      {t === 'OPT' ? 'Option' : 'Stock'}
                    </button>
                  ))}
                </div>

                {newPosType === 'OPT' && (
                  <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap' }}>
                    <div>
                      <label style={{ fontWeight: 600, display: 'block', marginBottom: 4 }}>Expiry</label>
                      <select value={expiry} onChange={(e) => handleExpiryChange(e.target.value)} style={{ padding: '6px 10px', borderRadius: 6 }}>
                        {expiries.map((e) => <option key={e} value={e}>{e}</option>)}
                      </select>
                    </div>
                    <div>
                      <label style={{ fontWeight: 600, display: 'block', marginBottom: 4 }}>Strike</label>
                      <select value={newStrike} onChange={(e) => setNewStrike(e.target.value)} style={{ padding: '6px 10px', borderRadius: 6 }}>
                        <option value="">-- select --</option>
                        {strikes.map((s) => <option key={s} value={s}>{s}</option>)}
                      </select>
                    </div>
                    <div>
                      <label style={{ fontWeight: 600, display: 'block', marginBottom: 4 }}>Type</label>
                      <div style={{ display: 'flex', gap: 6 }}>
                        {['C', 'P'].map((r) => (
                          <button
                            key={r}
                            onClick={() => setNewRight(r)}
                            style={{
                              padding: '6px 14px',
                              borderRadius: 6,
                              background: newRight === r ? 'var(--primary)' : 'var(--surface)',
                              color: newRight === r ? '#fff' : 'var(--text)',
                            }}
                          >
                            {r === 'C' ? 'Call' : 'Put'}
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>
                )}

                <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap' }}>
                  <div>
                    <label style={{ fontWeight: 600, display: 'block', marginBottom: 4 }}>
                      Quantity <span style={{ fontWeight: 400, color: 'var(--text-muted)' }}>(neg. = short)</span>
                    </label>
                    <input
                      type="number"
                      value={newQty}
                      onChange={(e) => setNewQty(e.target.value)}
                      style={{ width: 90, padding: '6px 8px', borderRadius: 6 }}
                    />
                  </div>
                  <div>
                    <label style={{ fontWeight: 600, display: 'block', marginBottom: 4 }}>Entry price</label>
                    <input
                      type="number"
                      step={0.01}
                      min={0}
                      value={newEntryInput}
                      onChange={(e) => setNewEntryInput(e.target.value)}
                      style={{ width: 100, padding: '6px 8px', borderRadius: 6 }}
                    />
                  </div>
                  <button onClick={addPosition}>Add Position</button>
                </div>
              </div>
            )}

            {positions.length > 0 && (
              <table style={{ maxWidth: 900 }}>
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Details</th>
                    <th>Qty</th>
                    <th>Entry</th>
                    <th>Mark</th>
                    <th>Spot</th>
                    <th>P/L</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((p) => {
                    const mult = positionMultiplier(p);
                    const mark = p.markPrice ?? p.entryPrice;
                    const pl = (mark - p.entryPrice) * mult;
                    return (
                      <tr key={p.id}>
                        <td>{p.symbol}</td>
                        <td>{positionLabel(p)}</td>
                        <td>{p.quantity}</td>
                        <td>{formatMoney(p.entryPrice)}</td>
                        <td>{p.markPrice != null ? formatMoney(p.markPrice) : <span style={{ color: 'var(--text-muted)' }}>no data</span>}</td>
                        <td>{p.spot != null ? formatMoney(p.spot) : <span style={{ color: 'var(--text-muted)' }}>no data</span>}</td>
                        <td className={pl >= 0 ? 'text-positive' : 'text-negative'}>{formatMoney(pl)}</td>
                        <td>
                          <button onClick={() => removePosition(p.id)} style={{ padding: '2px 10px', fontSize: '0.8rem' }}>✕</button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}

            {positions.length === 0 && (
              <p style={{ color: 'var(--text-muted)' }}>
                No positions yet -- select a ticker from the sidebar and add one, or import your open IBKR positions.
              </p>
            )}

            {positions.length > 0 && (
              <>
                {/* Step 2: Simulate returns */}
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 24 }}>
                  <h3 style={{ margin: 0 }}>2&nbsp;&nbsp;Simulate Returns</h3>
                  <button onClick={resetSliders} title="Reset sliders" style={{ padding: '4px 12px', fontSize: '0.85rem' }}>↺ Reset</button>
                </div>
                <p style={{ color: 'var(--text-muted)', marginTop: 4 }}>
                  Applies the same % price change to every position's own underlying, and reprices every option
                  leg via Black-Scholes (delta, gamma, theta and vega all update together) as of the chosen future date.
                </p>

                <div style={{ maxWidth: 640, marginBottom: 20 }}>
                  <label style={{ fontWeight: 600, display: 'block', marginBottom: 8 }}>
                    Price change
                    <span style={{ float: 'right', color: priceChangePct === 0 ? 'var(--text-muted)' : 'var(--primary)' }}>
                      {priceChangePct === 0 ? 'Current' : `${priceChangePct > 0 ? '+' : ''}${priceChangePct}%`}
                    </span>
                  </label>
                  <input
                    type="range"
                    min={-50}
                    max={50}
                    step={1}
                    value={priceChangePct}
                    onChange={(e) => setPriceChangePct(parseInt(e.target.value, 10))}
                    style={{ width: '100%', accentColor: 'var(--primary)' }}
                  />
                </div>

                {dteMaxToday > 0 && (
                  <div style={{ maxWidth: 640, marginBottom: 20 }}>
                    <label style={{ fontWeight: 600, display: 'block', marginBottom: 8 }}>
                      Time forward
                      <span style={{ float: 'right', color: daysForward === 0 ? 'var(--text-muted)' : 'var(--primary)' }}>
                        {daysForward === 0 ? 'Current' : `${daysForward} day${daysForward !== 1 ? 's' : ''}`}
                      </span>
                    </label>
                    <input
                      type="range"
                      min={0}
                      max={dteMaxToday}
                      step={1}
                      value={daysForward}
                      onChange={(e) => setDaysForward(parseInt(e.target.value, 10))}
                      style={{ width: '100%', accentColor: 'var(--primary)' }}
                    />
                  </div>
                )}

                {/* Step 3: Summary */}
                <h3>3&nbsp;&nbsp;Simulation Summary</h3>
                <div style={{
                  border: '1px solid var(--border)',
                  borderRadius: 10,
                  padding: '16px 20px',
                  maxWidth: 480,
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 8,
                }}>
                  <Row label="Current P/L Open" value={formatMoney(summary.currentPL)} color={summary.currentPL >= 0 ? 'var(--positive)' : 'var(--negative)'} />
                  <Row
                    label="Current Returns"
                    value={summary.currentReturnsPct != null ? `${summary.currentReturnsPct >= 0 ? '+' : ''}${summary.currentReturnsPct.toFixed(2)}%` : '--'}
                    color={summary.currentReturnsPct == null ? 'var(--text)' : summary.currentReturnsPct >= 0 ? 'var(--positive)' : 'var(--negative)'}
                  />
                  <hr style={{ border: 'none', borderTop: '1px solid var(--border)', margin: '4px 0' }} />
                  <Row
                    label="New Projected P/L"
                    value={projected ? formatMoney(projected.newPL) : '—'}
                    color={!projected ? 'var(--text-muted)' : projected.newPL >= 0 ? 'var(--positive)' : 'var(--negative)'}
                  />
                  <Row
                    label="Implied Change in Returns (vs Current)"
                    value={projected?.impliedChange != null ? `${projected.impliedChange >= 0 ? '+' : ''}${projected.impliedChange.toFixed(2)}%` : '—'}
                    color={!projected || projected.impliedChange == null ? 'var(--text-muted)' : projected.impliedChange >= 0 ? 'var(--positive)' : 'var(--negative)'}
                  />
                  <hr style={{ border: 'none', borderTop: '1px solid var(--border)', margin: '4px 0' }} />
                  <Row label="Delta $ Exposure (per 1% move)" value={formatMoney(summary.deltaExposure)} />
                </div>
                {summary.missingData && (
                  <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem', marginTop: 8 }}>
                    Some positions are missing a live underlying price (no market data for that symbol/expiry) and are excluded from the simulated projection.
                  </p>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function Row({ label, value, color }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
      <span style={{ color: 'var(--text-muted)' }}>{label}</span>
      <strong style={{ color: color || 'var(--text)' }}>{value}</strong>
    </div>
  );
}
