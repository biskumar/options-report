import { useEffect, useState } from 'react';
import { isTradingBlocked } from '../components/ConnectionBanner';
import { OrderConfirmModal } from '../components/OrderConfirmModal';
import { PayoffChart } from '../components/PayoffChart';
import { TickerSidebar } from '../components/TickerSidebar';
import { useLiveData } from '../state/LiveDataContext';
import { api } from '../utils/api';
import { filterNextTwoMonths } from '../utils/dates';
import { formatMoney } from '../utils/format';
import {
  computeAggregateGreeks,
  computeNetDebitCredit,
  computePayoffCurve,
  computePOP,
  daysToExpiryFromToday,
  detectUncapped,
  findBreakevens,
  maxLoss as calcMaxLoss,
  maxProfit as calcMaxProfit,
  estimateMarginRequired,
  syntheticIV,
} from '../utils/optionMath';

const PRESETS = {
  bull_call_spread: {
    label: 'Bull call spread', backendName: 'vertical', right: 'C',
    strikeFields: ['Buy strike (lower)', 'Sell strike (higher)'], needsRight: false, needsSide: false, needsExpiry2: false,
  },
  bear_put_spread: {
    label: 'Bear put spread', backendName: 'vertical', right: 'P',
    strikeFields: ['Buy strike (higher)', 'Sell strike (lower)'], needsRight: false, needsSide: false, needsExpiry2: false,
  },
  iron_condor: {
    label: 'Iron condor', backendName: 'iron_condor',
    strikeFields: ['Put long', 'Put short', 'Call short', 'Call long'], needsRight: false, needsSide: false, needsExpiry2: false,
  },
  straddle: {
    label: 'Straddle', backendName: 'straddle',
    strikeFields: ['Strike'], needsRight: false, needsSide: true, needsExpiry2: false,
  },
  strangle: {
    label: 'Strangle', backendName: 'strangle',
    strikeFields: ['Call strike', 'Put strike'], needsRight: false, needsSide: true, needsExpiry2: false,
  },
  calendar_spread: {
    label: 'Calendar spread', backendName: 'calendar_spread',
    strikeFields: ['Strike'], needsRight: true, needsSide: true, needsExpiry2: true,
  },
  butterfly: {
    label: 'Butterfly', backendName: 'butterfly',
    strikeFields: ['Low strike', 'Mid strike', 'High strike'], needsRight: true, needsSide: true, needsExpiry2: false,
  },
};

function emptyLeg() {
  return { expiry: '', strike: '', right: 'C', action: 'BUY', ratio: 1 };
}

function numericLegs(legs) {
  return legs
    .filter((l) => l.strike !== '' && l.expiry)
    .map((l) => ({ ...l, strike: parseFloat(l.strike), ratio: parseInt(l.ratio, 10) || 1 }));
}

function StatCard({ label, value }) {
  return (
    <div className="stat-card">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
    </div>
  );
}

export function StrategyBuilder() {
  const liveData = useLiveData();
  const blocked = isTradingBlocked(liveData);

  const [symbol, setSymbol] = useState('');
  const [spot, setSpot] = useState(null);
  const [chainData, setChainData] = useState(null);
  const [expiryOptions, setExpiryOptions] = useState([]);
  const [expiry, setExpiry] = useState('');
  const [expiry2, setExpiry2] = useState('');
  const [presetName, setPresetName] = useState('bull_call_spread');
  const [strikeInputs, setStrikeInputs] = useState(['', '']);
  const [right, setRight] = useState('C');
  const [side, setSide] = useState('long');
  const [legs, setLegs] = useState([]);
  const [quantity, setQuantity] = useState(1);
  const [orderType, setOrderType] = useState('limit');
  const [limitPrice, setLimitPrice] = useState('');
  const [preview, setPreview] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [payoffMode, setPayoffMode] = useState('atExpiry');
  const [savedStrategies, setSavedStrategies] = useState([]);
  const [selectedSavedIndex, setSelectedSavedIndex] = useState('');
  const [liveNetMid, setLiveNetMid] = useState(null);
  const [liveNetMidLoading, setLiveNetMidLoading] = useState(false);
  const [liveNetMidError, setLiveNetMidError] = useState(null);
  const [theme, setTheme] = useState(() => localStorage.getItem('strategyTheme') || 'light');

  function toggleTheme() {
    setTheme((t) => {
      const next = t === 'dark' ? 'light' : 'dark';
      localStorage.setItem('strategyTheme', next);
      return next;
    });
  }

  const preset = PRESETS[presetName];
  const effectiveRight = preset.right || right;


  useEffect(() => {
    if (!symbol || !expiry) {
      setChainData(null);
      setSpot(null);
      return;
    }
    api.get(`/api/chain?symbol=${encodeURIComponent(symbol)}&expiry=${expiry}`)
      .then((data) => { setChainData(data); setSpot(data.spot); })
      .catch((e) => setError(e.message));
  }, [symbol, expiry]);

  // Live net-mid quote for the legs currently in the table, shown next to
  // the Limit price field so you can see the real market price *before*
  // typing a limit price guess, instead of only finding out after
  // clicking Preview. Debounced since leg edits fire on every keystroke.
  useEffect(() => {
    const validLegsForQuote = numericLegs(legs);
    if (!symbol || validLegsForQuote.length === 0) {
      setLiveNetMid(null);
      setLiveNetMidError(null);
      return;
    }
    setLiveNetMidLoading(true);
    setLiveNetMidError(null);
    const timer = setTimeout(() => {
      api.post('/api/orders/combo/quote', {
        symbol: symbol.toUpperCase(),
        legs: validLegsForQuote.map((l) => ({ expiry: l.expiry, strike: l.strike, right: l.right, action: l.action, ratio: l.ratio })),
      })
        .then((data) => setLiveNetMid(data.netMid))
        .catch((e) => setLiveNetMidError(e.message))
        .finally(() => setLiveNetMidLoading(false));
    }, 500);
    return () => clearTimeout(timer);
  }, [legs, symbol]);

  async function selectSymbol(sym) {
    setSymbol(sym);
    setError(null);
    setExpiryOptions([]);
    setExpiry('');
    setExpiry2('');
    setLegs([]);
    setPreview(null);
    setResult(null);
    if (!sym) return;
    try {
      const data = await api.get(`/api/chain/expiries?symbol=${encodeURIComponent(sym)}`);
      const nearTerm = filterNextTwoMonths(data.expiries);
      setExpiryOptions(nearTerm);
      setExpiry(nearTerm[0] || '');
    } catch (e) {
      setError(e.message);
    }
  }

  function handlePresetChange(key) {
    setPresetName(key);
    const p = PRESETS[key];
    setStrikeInputs(Array(p.strikeFields.length).fill(''));
    setRight(p.right || 'C');
    setSide('long');
    setExpiry2('');
    setLegs([]);
    setPreview(null);
    setResult(null);
  }

  function updateStrike(i, value) {
    setStrikeInputs((arr) => arr.map((v, idx) => (idx === i ? value : v)));
  }

  function lookupChainMid(leg) {
    if (!chainData || leg.expiry !== expiry) return undefined;
    const rows = leg.right === 'C' ? chainData.calls : chainData.puts;
    const row = rows.find((r) => r.strike === leg.strike);
    return row ? row.mid : undefined;
  }

  async function loadPreset() {
    setError(null);
    try {
      const body = {
        name: preset.backendName,
        expiry,
        strikes: strikeInputs.map(Number),
        right: preset.needsRight || preset.right ? effectiveRight : null,
        side: preset.needsSide ? side : null,
        expiry2: preset.needsExpiry2 ? expiry2 : null,
      };
      const data = await api.post('/api/orders/combo/preset', body);
      const legsWithMid = data.legs.map((leg) => ({ ...leg, mid: lookupChainMid(leg) }));
      setLegs(legsWithMid);
    } catch (err) {
      setError(err.message);
    }
  }

  function addCustomLeg() {
    setLegs((ls) => [...ls, emptyLeg()]);
  }

  function updateLeg(i, field, value) {
    setLegs((ls) => ls.map((l, idx) => (idx === i ? { ...l, [field]: value } : l)));
  }

  function removeLeg(i) {
    setLegs((ls) => ls.filter((_, idx) => idx !== i));
  }

  async function handlePreview() {
    setError(null);
    setResult(null);
    try {
      const body = {
        symbol: symbol.toUpperCase(),
        legs: legs.map((l) => ({
          expiry: l.expiry,
          strike: parseFloat(l.strike),
          right: l.right,
          action: l.action,
          ratio: parseInt(l.ratio, 10) || 1,
        })),
        quantity: parseInt(quantity, 10),
        orderType,
        limitPrice: limitPrice ? parseFloat(limitPrice) : null,
      };
      const data = await api.post('/api/orders/combo/preview', body);
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

  function saveStrategy() {
    const snapshot = {
      label: `${symbol || '?'} · ${preset.label} · ${expiry || '?'}`,
      symbol, presetName, expiry, expiry2, strikeInputs, right, side, legs, quantity, orderType, limitPrice,
    };
    setSavedStrategies((arr) => [...arr, snapshot]);
  }

  function loadStrategy(idx) {
    const s = savedStrategies[idx];
    if (!s) return;
    setSymbol(s.symbol);
    setPresetName(s.presetName);
    setExpiry(s.expiry);
    setExpiry2(s.expiry2);
    setStrikeInputs(s.strikeInputs);
    setRight(s.right);
    setSide(s.side);
    setLegs(s.legs);
    setQuantity(s.quantity);
    setOrderType(s.orderType);
    setLimitPrice(s.limitPrice);
    setPreview(null);
    setResult(null);
  }

  const validLegs = numericLegs(legs);
  const hasLegs = validLegs.length > 0 && spot != null;

  let curve = [];
  let curveToday = [];
  let curveAtExpiry = [];
  let breakevens = [];
  let greeks = null;
  let uncapped = { uncappedUp: false, uncappedDown: false };
  let maxP = null, maxL = null, margin = null, netDebitCredit = null, pop = null, dte = null;

  if (hasLegs) {
    const strikes = validLegs.map((l) => l.strike);
    const lo = Math.min(...strikes) * 0.7;
    const hi = Math.max(...strikes) * 1.3;
    const steps = 80;
    const spotRange = Array.from({ length: steps + 1 }, (_, i) => lo + ((hi - lo) * i) / steps);

    curveToday = computePayoffCurve(validLegs, spot, 'today', spotRange);
    curveAtExpiry = computePayoffCurve(validLegs, spot, 'atExpiry', spotRange);
    curve = payoffMode === 'today' ? curveToday : curveAtExpiry;
    breakevens = findBreakevens(curve);
    greeks = computeAggregateGreeks(validLegs, spot);
    uncapped = detectUncapped(curve);
    maxP = calcMaxProfit(curve);
    maxL = calcMaxLoss(curve);
    margin = estimateMarginRequired(maxL, uncapped);
    netDebitCredit = computeNetDebitCredit(validLegs, spot);
    dte = daysToExpiryFromToday(expiry);
    pop = computePOP(curve, breakevens, spot, validLegs, dte);
  }

  const maxProfitAtRight = curve.length && curve[curve.length - 1].pnl === maxP;
  const maxProfitAtLeft = curve.length && curve[0].pnl === maxP;
  const maxProfitUncapped = (maxProfitAtRight && uncapped.uncappedUp) || (maxProfitAtLeft && uncapped.uncappedDown);
  const maxLossAtRight = curve.length && curve[curve.length - 1].pnl === maxL;
  const maxLossAtLeft = curve.length && curve[0].pnl === maxL;
  const maxLossUncapped = (maxLossAtRight && uncapped.uncappedUp) || (maxLossAtLeft && uncapped.uncappedDown);

  const riskReward = !maxProfitUncapped && !maxLossUncapped && maxL !== 0 && maxL != null
    ? Math.abs(maxP / maxL).toFixed(2)
    : null;

  return (
    <div className="page">
      <h2>Strategy Builder</h2>
      {error && <p className="warning">{error}</p>}
      {result && (
        <p className="tag">
          {result.dryRun ? 'DRY RUN — ' : ''}Order {result.status} {result.orderId ? `(id ${result.orderId})` : ''}
        </p>
      )}

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
                {symbol} {spot != null ? formatMoney(spot) : '--'}
              </p>
            )}

            <div className="preset-pills">
              {Object.entries(PRESETS).map(([key, p]) => (
                <button
                  key={key}
                  className={presetName === key ? 'active' : ''}
                  onClick={() => handlePresetChange(key)}
                >
                  {p.label}
                </button>
              ))}
            </div>

            <div className="strategy-preset-form">
              <label>Expiry (next 2 months)
                <select value={expiry} onChange={(e) => setExpiry(e.target.value)} disabled={expiryOptions.length === 0}>
                  {expiryOptions.length === 0 && <option value="">Select a ticker first…</option>}
                  {expiryOptions.map((exp) => <option key={exp} value={exp}>{exp}</option>)}
                </select>
              </label>
              {preset.needsExpiry2 && (
                <label>Far expiry
                  <select value={expiry2} onChange={(e) => setExpiry2(e.target.value)} disabled={expiryOptions.length === 0}>
                    <option value="">Select…</option>
                    {expiryOptions.filter((exp) => exp > expiry).map((exp) => <option key={exp} value={exp}>{exp}</option>)}
                  </select>
                </label>
              )}
              {preset.strikeFields.map((label, i) => (
                <label key={label}>{label} <input type="number" step="0.5" value={strikeInputs[i] || ''} onChange={(e) => updateStrike(i, e.target.value)} /></label>
              ))}
              {preset.needsRight && (
                <label>Right
                  <select value={right} onChange={(e) => setRight(e.target.value)}>
                    <option value="C">Call</option>
                    <option value="P">Put</option>
                  </select>
                </label>
              )}
              {preset.needsSide && (
                <label>Side
                  <select value={side} onChange={(e) => setSide(e.target.value)}>
                    <option value="long">Long</option>
                    <option value="short">Short</option>
                  </select>
                </label>
              )}
              <button onClick={loadPreset} disabled={!symbol || !expiry}>Load preset legs</button>
            </div>

            <div className="stats-grid">
              <StatCard label="Net debit/credit" value={hasLegs ? formatMoney(netDebitCredit) : '--'} />
              <StatCard label={`Max profit${hasLegs ? (payoffMode === 'today' ? ' (today)' : ' (expiry)') : ''}`} value={!hasLegs ? '--' : maxProfitUncapped ? 'Uncapped' : formatMoney(maxP)} />
              <StatCard label={`Max loss${hasLegs ? (payoffMode === 'today' ? ' (today)' : ' (expiry)') : ''}`} value={!hasLegs ? '--' : maxLossUncapped ? 'Uncapped' : formatMoney(maxL)} />
              <StatCard label="Risk : reward" value={riskReward ?? '--'} />
              <StatCard label="Breakeven(s)" value={hasLegs && breakevens.length ? breakevens.map((b) => b.toFixed(2)).join(', ') : '--'} />
              <StatCard label="Prob. of profit" value={hasLegs ? `${(pop * 100).toFixed(0)}%` : '--'} />
              <StatCard label="Margin required" value={!hasLegs ? '--' : margin == null ? 'N/A — uncapped risk' : formatMoney(margin)} />
              <StatCard label="Days to expiry" value={hasLegs ? dte : '--'} />
            </div>

            <div className="greeks-bar">
              <span>Delta {greeks ? greeks.delta.toFixed(3) : '--'}</span>
              <span>Gamma {greeks ? greeks.gamma.toFixed(4) : '--'}</span>
              <span>Theta {greeks ? greeks.theta.toFixed(3) : '--'}</span>
              <span>Vega {greeks ? greeks.vega.toFixed(3) : '--'}</span>
            </div>

            <div className="chart-toggle-row">
              <div className="pill-toggle">
                <button className={payoffMode === 'today' ? 'active' : ''} onClick={() => setPayoffMode('today')}>Today</button>
                <button className={payoffMode === 'atExpiry' ? 'active' : ''} onClick={() => setPayoffMode('atExpiry')}>At expiry</button>
              </div>
              <div className="chart-legend">
                <span><span className="dot" />Today</span>
                <span><span className="dash" />At expiry</span>
              </div>
            </div>

            {hasLegs ? (
              <PayoffChart
                curveToday={curveToday}
                curveAtExpiry={curveAtExpiry}
                activeMode={payoffMode}
                breakevens={breakevens}
                currentSpot={spot}
                width={720}
              />
            ) : (
              <p className="payoff-note">Pick a preset above and load legs to see the payoff chart.</p>
            )}

            <div className="legs-header">
              <h3>Legs {legs.length > 0 ? `(${legs.length})` : ''}</h3>
              <button onClick={addCustomLeg}>+ Add leg</button>
            </div>
            {legs.length === 0 ? (
              <p className="payoff-note">Pick a preset above to get started.</p>
            ) : (
              <div className="legs-list">
                {legs.map((leg, i) => {
                  const buy = leg.action === 'BUY';
                  const strikeNum = parseFloat(leg.strike);
                  const ivPct = spot != null && !Number.isNaN(strikeNum) ? Math.round(syntheticIV(strikeNum, spot) * 100) : null;
                  return (
                    <div className="leg-row" key={i}>
                      <button
                        className={`leg-pill ${buy ? 'buy' : 'sell'}`}
                        onClick={() => updateLeg(i, 'action', buy ? 'SELL' : 'BUY')}
                      >
                        {buy ? 'BUY' : 'SELL'}
                      </button>
                      <input
                        className="leg-ratio-input" type="number" min="1" value={leg.ratio}
                        onChange={(e) => updateLeg(i, 'ratio', e.target.value)}
                      />
                      <span>$</span>
                      <input
                        className="leg-strike-input" type="number" step="0.5" value={leg.strike}
                        onChange={(e) => updateLeg(i, 'strike', e.target.value)}
                      />
                      <button
                        className="leg-right-pill"
                        onClick={() => updateLeg(i, 'right', leg.right === 'C' ? 'P' : 'C')}
                      >
                        {leg.right === 'C' ? 'Call' : 'Put'}
                      </button>
                      <input
                        className="leg-expiry-input" value={leg.expiry} placeholder="YYYYMMDD"
                        onChange={(e) => updateLeg(i, 'expiry', e.target.value)}
                      />
                      {ivPct != null && <span className="leg-iv-badge">{ivPct}% IV</span>}
                      <button className="leg-remove-btn" aria-label="Remove leg" onClick={() => removeLeg(i)}>×</button>
                    </div>
                  );
                })}
              </div>
            )}

            <div className="strategy-footer">
              <div className="strategy-save-row">
                <button onClick={saveStrategy} disabled={legs.length === 0}>Save</button>
                <select
                  value={selectedSavedIndex}
                  onChange={(e) => { setSelectedSavedIndex(e.target.value); if (e.target.value !== '') loadStrategy(Number(e.target.value)); }}
                >
                  <option value="">Load saved… (this session only)</option>
                  {savedStrategies.map((s, i) => <option key={i} value={i}>{s.label}</option>)}
                </select>
              </div>

              <div className="strategy-order-form">
                <label>Quantity (combo units) <input type="number" min="1" value={quantity} onChange={(e) => setQuantity(e.target.value)} /></label>
                <label>Order type
                  <select value={orderType} onChange={(e) => setOrderType(e.target.value)}>
                    <option value="market">Market</option>
                    <option value="limit">Limit (net price, + debit / - credit)</option>
                  </select>
                </label>
                {orderType === 'limit' && (
                  <label>Limit (net) price
                    <div className="limit-price-row">
                      <input type="number" step="0.01" value={limitPrice} onChange={(e) => setLimitPrice(e.target.value)} />
                      <span className="live-net-mid">
                        {liveNetMidLoading
                          ? 'Live: …'
                          : liveNetMidError
                          ? 'Live: --'
                          : liveNetMid != null
                          ? `Live: ${formatMoney(Math.abs(liveNetMid))} ${liveNetMid > 0 ? 'debit' : liveNetMid < 0 ? 'credit' : ''}`
                          : 'Live: --'}
                      </span>
                      {liveNetMid != null && (
                        <button type="button" onClick={() => setLimitPrice(liveNetMid.toFixed(2))}>Use</button>
                      )}
                    </div>
                  </label>
                )}
                <button className="confirm-btn" onClick={handlePreview} disabled={blocked || legs.length === 0}>Preview combo order</button>
                {blocked && <p className="warning">Trading is blocked — connect to IBKR and/or disengage the kill switch.</p>}
              </div>
            </div>

            <p className="payoff-note">
              Greeks/IV are a synthetic skew approximation (24% base + distance-from-spot term), not real chain IV.
              Prob. of profit uses that same synthetic IV in a lognormal model, not the broker's own calc.
              Margin required equals max loss for defined-risk spreads only — uncapped-risk legs show "N/A" until real margin logic is added.
              "Uncapped" detection is a slope heuristic on the payoff chart's edges, reliable for straddles/strangles, approximate for other shapes.
            </p>
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
