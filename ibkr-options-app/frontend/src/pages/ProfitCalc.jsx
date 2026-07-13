import { useEffect, useMemo, useState } from 'react';
import { TickerSidebar } from '../components/TickerSidebar';
import { api } from '../utils/api';
import { blackScholes, daysToExpiryFromToday, syntheticIV } from '../utils/optionMath';
import { formatMoney } from '../utils/format';

export function ProfitCalc() {
  const [symbol, setSymbol] = useState('');
  const [expiries, setExpiries] = useState([]);
  const [expiry, setExpiry] = useState('');
  const [chain, setChain] = useState(null);
  const [error, setError] = useState(null);
  const [theme, setTheme] = useState(() => localStorage.getItem('strategyTheme') || 'light');

  // Selected option
  const [selectedStrike, setSelectedStrike] = useState('');
  const [selectedRight, setSelectedRight] = useState('C');

  // Simulator inputs
  const [contracts, setContracts] = useState(1);
  const [simPrice, setSimPrice] = useState(0);
  const [simPriceInput, setSimPriceInput] = useState('');
  const [entryPremiumInput, setEntryPremiumInput] = useState('');
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
    setSelectedStrike('');
    try {
      const data = await api.get(`/api/chain/expiries?symbol=${encodeURIComponent(sym)}`);
      setExpiries(data.expiries);
      const first = data.expiries[0] || '';
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
      setSelectedStrike('');
      // Default sim price to current spot
      const spot = data.spot || 0;
      setSimPrice(spot);
      setSimPriceInput(spot.toFixed(2));
    } catch (e) {
      setError(e.message);
    }
  }

  async function handleExpiryChange(exp) {
    setExpiry(exp);
    if (symbol) await loadChain(symbol, exp);
  }

  // Build unique sorted strikes list
  const strikes = useMemo(() => {
    if (!chain) return [];
    const set = new Set([...chain.calls, ...chain.puts].map((r) => r.strike));
    return [...set].sort((a, b) => a - b);
  }, [chain]);

  // Find the selected row to get entry premium
  const selectedRow = useMemo(() => {
    if (!chain || !selectedStrike) return null;
    const rows = selectedRight === 'C' ? chain.calls : chain.puts;
    return rows.find((r) => r.strike === Number(selectedStrike)) || null;
  }, [chain, selectedStrike, selectedRight]);

  const marketPremium = useMemo(() => {
    if (!selectedRow) return null;
    if (selectedRow.mid != null) return selectedRow.mid;
    if (selectedRow.bid != null && selectedRow.ask != null) return (selectedRow.bid + selectedRow.ask) / 2;
    return null;
  }, [selectedRow]);

  // Default the editable entry premium to the market mid whenever the
  // selected option changes, but let the user override it (e.g. to match
  // their actual fill price) without it snapping back on every render.
  useEffect(() => {
    setEntryPremiumInput(marketPremium != null ? marketPremium.toFixed(2) : '');
  }, [selectedRow]);

  // Reset the evaluation date back to "today" whenever a different option
  // is picked, so decay from a stale selection doesn't carry over.
  useEffect(() => {
    setDaysForward(0);
  }, [selectedRow]);

  const entryPremium = useMemo(() => {
    const n = parseFloat(entryPremiumInput);
    return !isNaN(n) && n >= 0 ? n : null;
  }, [entryPremiumInput]);

  // Days to expiry as of today, and as of the user-chosen evaluation date
  // ("Days from now" slider) -- letting daysForward advance is what makes
  // theta actually show up in the P&L instead of always pricing "today".
  const dteToday = useMemo(() => (expiry ? daysToExpiryFromToday(expiry) : 0), [expiry]);
  const evalDte = Math.max(dteToday - daysForward, 0);

  // Theoretical value + greeks of the selected option at the simulated
  // price, evaluated as of the chosen date. Uses the chain's real IV when
  // IBKR has it; falls back to the same synthetic IV curve the Strategy
  // Builder uses otherwise.
  const theo = useMemo(() => {
    if (!selectedRow || !chain || simPrice <= 0) return null;
    if (evalDte <= 0) {
      const strike = Number(selectedStrike);
      const intrinsic = selectedRight === 'C' ? Math.max(simPrice - strike, 0) : Math.max(strike - simPrice, 0);
      return {
        price: intrinsic,
        delta: selectedRight === 'C' ? (simPrice > strike ? 1 : 0) : (simPrice < strike ? -1 : 0),
        gamma: 0,
        theta: 0,
        vega: 0,
      };
    }
    const iv = selectedRow.impliedVolatility > 0 ? selectedRow.impliedVolatility : syntheticIV(Number(selectedStrike), chain.spot);
    return blackScholes(simPrice, Number(selectedStrike), evalDte / 365, iv, selectedRight);
  }, [selectedRow, chain, simPrice, evalDte, selectedStrike, selectedRight]);

  // P&L: theoretical exit value (at the simulated price/date) minus what was paid to enter
  const pnl = useMemo(() => {
    if (!theo || entryPremium == null) return null;
    return (theo.price - entryPremium) * 100 * contracts;
  }, [theo, entryPremium, contracts]);

  const spot = chain?.spot || 0;
  const sliderMin = spot > 0 ? Math.round(spot * 0.7) : 0;
  const sliderMax = spot > 0 ? Math.round(spot * 1.3) : 1000;

  // Sync typed input → slider when user finishes typing
  function handlePriceType(val) {
    setSimPriceInput(val);
    const n = parseFloat(val);
    if (!isNaN(n) && n > 0) setSimPrice(n);
  }

  // When spot loads for the first time
  useEffect(() => {
    if (spot > 0 && simPrice === 0) {
      setSimPrice(spot);
      setSimPriceInput(spot.toFixed(2));
    }
  }, [spot]);

  const pnlColor = pnl == null ? 'var(--text)' : pnl >= 0 ? 'var(--positive)' : 'var(--negative)';

  return (
    <div className="page">
      <h2>Options Profit Calculator</h2>
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
                {symbol} {spot ? formatMoney(spot) : '--'}
              </p>
            )}

            {/* Expiry selector */}
            {expiries.length > 0 && (
              <div className="chain-controls" style={{ marginBottom: '16px' }}>
                <label style={{ fontWeight: 600, marginRight: 8 }}>Expiry</label>
                <select
                  value={expiry}
                  onChange={(e) => handleExpiryChange(e.target.value)}
                  className="chain-expiry-select"
                >
                  {expiries.map((e) => (
                    <option key={e} value={e}>{e}</option>
                  ))}
                </select>
              </div>
            )}

            {chain && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', maxWidth: 560 }}>
                {/* Strike + Call/Put */}
                <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                  <div>
                    <label style={{ fontWeight: 600, display: 'block', marginBottom: 4 }}>Strike</label>
                    <select
                      value={selectedStrike}
                      onChange={(e) => setSelectedStrike(e.target.value)}
                      style={{ fontSize: '1rem', padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)' }}
                    >
                      <option value="">-- select --</option>
                      {strikes.map((s) => (
                        <option key={s} value={s}>{s}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label style={{ fontWeight: 600, display: 'block', marginBottom: 4 }}>Type</label>
                    <div style={{ display: 'flex', gap: 6 }}>
                      {['C', 'P'].map((r) => (
                        <button
                          key={r}
                          onClick={() => setSelectedRight(r)}
                          style={{
                            padding: '6px 18px',
                            borderRadius: 6,
                            border: '1px solid var(--border)',
                            background: selectedRight === r ? 'var(--primary)' : 'var(--surface)',
                            color: selectedRight === r ? '#fff' : 'var(--text)',
                            fontWeight: 600,
                            cursor: 'pointer',
                          }}
                        >
                          {r === 'C' ? 'Call' : 'Put'}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div>
                    <label style={{ fontWeight: 600, display: 'block', marginBottom: 4 }}>Contracts</label>
                    <input
                      type="number"
                      min={1}
                      value={contracts}
                      onChange={(e) => setContracts(Math.max(1, parseInt(e.target.value) || 1))}
                      style={{ width: 70, fontSize: '1rem', padding: '6px 8px', borderRadius: 6, border: '1px solid var(--border)' }}
                    />
                  </div>
                </div>

                {/* Entry premium: editable, defaults to market mid */}
                {selectedRow && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                    <label style={{ fontWeight: 600 }}>Entry premium</label>
                    <input
                      type="number"
                      step={0.01}
                      min={0}
                      value={entryPremiumInput}
                      onChange={(e) => setEntryPremiumInput(e.target.value)}
                      style={{ width: 90, fontSize: '1rem', padding: '6px 8px', borderRadius: 6, border: '1px solid var(--border)' }}
                    />
                    {marketPremium != null && (
                      <button
                        onClick={() => setEntryPremiumInput(marketPremium.toFixed(2))}
                        style={{
                          fontSize: '0.8rem',
                          padding: '4px 10px',
                          borderRadius: 6,
                          border: '1px solid var(--border)',
                          background: 'var(--surface)',
                          color: 'var(--text-muted)',
                          cursor: 'pointer',
                        }}
                      >
                        Reset to market ({formatMoney(marketPremium)})
                      </button>
                    )}
                    {entryPremium != null && (
                      <span style={{ fontSize: '0.95rem', color: 'var(--text-muted)' }}>
                        Cost: <strong style={{ color: 'var(--text)' }}>{formatMoney(entryPremium * 100 * contracts)}</strong> total
                      </span>
                    )}
                  </div>
                )}

                {/* Price slider */}
                <div>
                  <label style={{ fontWeight: 600, display: 'block', marginBottom: 8 }}>
                    Simulated Price: <span style={{ color: 'var(--primary)' }}>{formatMoney(simPrice)}</span>
                    {spot > 0 && (
                      <span style={{ fontWeight: 400, color: 'var(--text-muted)', marginLeft: 8 }}>
                        ({simPrice >= spot ? '+' : ''}{(((simPrice - spot) / spot) * 100).toFixed(1)}% from current)
                      </span>
                    )}
                  </label>
                  <input
                    type="range"
                    min={sliderMin}
                    max={sliderMax}
                    step={0.5}
                    value={Math.min(Math.max(simPrice, sliderMin), sliderMax)}
                    onChange={(e) => {
                      const v = parseFloat(e.target.value);
                      setSimPrice(v);
                      setSimPriceInput(v.toFixed(2));
                    }}
                    style={{ width: '100%', accentColor: 'var(--primary)' }}
                  />
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', color: 'var(--text-muted)', marginTop: 2 }}>
                    <span>{formatMoney(sliderMin)}</span>
                    <input
                      type="number"
                      value={simPriceInput}
                      step={0.5}
                      onChange={(e) => handlePriceType(e.target.value)}
                      style={{ width: 90, textAlign: 'center', fontSize: '0.9rem', padding: '2px 6px', borderRadius: 4, border: '1px solid var(--border)' }}
                    />
                    <span>{formatMoney(sliderMax)}</span>
                  </div>
                </div>

                {/* Evaluation date slider -- lets theta actually show up in the P&L */}
                {dteToday > 0 && (
                  <div>
                    <label style={{ fontWeight: 600, display: 'block', marginBottom: 8 }}>
                      Evaluate: <span style={{ color: 'var(--primary)' }}>{daysForward === 0 ? 'Today' : `${daysForward} day${daysForward !== 1 ? 's' : ''} from now`}</span>
                      <span style={{ fontWeight: 400, color: 'var(--text-muted)', marginLeft: 8 }}>
                        ({evalDte} of {dteToday} days to expiry left)
                      </span>
                    </label>
                    <input
                      type="range"
                      min={0}
                      max={dteToday}
                      step={1}
                      value={daysForward}
                      onChange={(e) => setDaysForward(parseInt(e.target.value, 10))}
                      style={{ width: '100%', accentColor: 'var(--primary)' }}
                    />
                  </div>
                )}

                {/* Greeks */}
                {selectedRow && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    <div style={{ fontWeight: 600 }}>Greeks</div>
                    <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', fontSize: '0.9rem' }}>
                      {[
                        ['Delta', theo?.delta],
                        ['Gamma', theo?.gamma],
                        ['Theta/day', theo?.theta],
                        ['Vega', theo?.vega],
                      ].map(([label, value]) => (
                        <div key={label}>
                          <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>{label}</div>
                          <div style={{ fontWeight: 600 }}>{value != null ? value.toFixed(4) : '--'}</div>
                        </div>
                      ))}
                    </div>
                    <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                      Model greeks at the simulated price/date above
                      {selectedRow.impliedVolatility > 0 ? ` · IV ${(selectedRow.impliedVolatility * 100).toFixed(1)}% (live)` : ' · IV estimated (no live IV for this contract)'}
                      {theo?.theta != null && (
                        <> · decay ≈ {formatMoney(theo.theta * 100 * contracts)}/day</>
                      )}
                    </div>
                    {(selectedRow.delta != null || selectedRow.gamma != null || selectedRow.theta != null || selectedRow.vega != null) && (
                      <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                        Live from broker (at current market price, today): Δ {selectedRow.delta?.toFixed(4) ?? '--'} · Γ {selectedRow.gamma?.toFixed(4) ?? '--'} · Θ {selectedRow.theta?.toFixed(4) ?? '--'} · V {selectedRow.vega?.toFixed(4) ?? '--'}
                      </div>
                    )}
                  </div>
                )}

                {/* P&L result */}
                <div style={{
                  background: 'var(--surface)',
                  border: `2px solid ${pnl == null ? 'var(--border)' : pnl >= 0 ? 'var(--positive)' : 'var(--negative)'}`,
                  borderRadius: 10,
                  padding: '20px 24px',
                  textAlign: 'center',
                }}>
                  <div style={{ fontSize: '0.9rem', color: 'var(--text-muted)', marginBottom: 6, fontWeight: 600, letterSpacing: '0.05em', textTransform: 'uppercase' }}>
                    Estimated P&amp;L
                  </div>
                  <div style={{ fontSize: '2.2rem', fontWeight: 700, color: pnlColor }}>
                    {pnl == null
                      ? '-- select a strike'
                      : `${pnl >= 0 ? '+' : ''}${formatMoney(pnl)}`}
                  </div>
                  {pnl != null && entryPremium != null && (
                    <div style={{ fontSize: '0.9rem', color: 'var(--text-muted)', marginTop: 6 }}>
                      {contracts} contract{contracts !== 1 ? 's' : ''} · {formatMoney(Math.abs(entryPremium * 100 * contracts))} at risk
                      {entryPremium > 0 && (
                        <span> · {((pnl / (entryPremium * 100 * contracts)) * 100).toFixed(1)}% return</span>
                      )}
                    </div>
                  )}
                </div>
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
