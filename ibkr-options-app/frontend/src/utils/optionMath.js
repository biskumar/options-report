// Client-side option-strategy math for the Strategy Builder's stats cards
// and payoff chart. Everything here is a *model*, not a broker quote --
// see the caveats called out on each function below, and the summary
// note rendered in the UI (StrategyBuilder.jsx renders a caption pointing
// back to this file).

const RISK_FREE_RATE = 0.05; // rough constant placeholder, not fetched live

function erf(x) {
  // Abramowitz-Stegun 7.1.26 approximation (~1e-7 max error) -- fine for
  // UI-facing probability/greeks display, not for pricing real risk.
  const sign = x < 0 ? -1 : 1;
  x = Math.abs(x);
  const a1 = 0.254829592, a2 = -0.284496736, a3 = 1.421413741, a4 = -1.453152027, a5 = 1.061405429, p = 0.3275911;
  const t = 1 / (1 + p * x);
  const y = 1 - (((((a5 * t + a4) * t + a3) * t + a2) * t + a1) * t) * Math.exp(-x * x);
  return sign * y;
}

function normCdf(x) {
  return 0.5 * (1 + erf(x / Math.SQRT2));
}

function normPdf(x) {
  return Math.exp(-0.5 * x * x) / Math.sqrt(2 * Math.PI);
}

/**
 * Synthetic per-leg IV. NOT real market IV -- a placeholder skew curve
 * (base 24% + a term that grows with distance from spot) used only so the
 * "today" theoretical curve and greeks have *something* reasonable to
 * work with before this is wired up to the real per-strike IV already
 * available from the option chain endpoint. Swap this out for the chain's
 * actual impliedVolatility field per leg when available.
 */
export function syntheticIV(strike, spot) {
  const base = 0.24;
  const skew = spot > 0 ? (Math.abs(strike - spot) / spot) * 0.5 : 0;
  return base + skew;
}

function daysBetween(fromDate, expiryStr) {
  const year = parseInt(expiryStr.slice(0, 4), 10);
  const month = parseInt(expiryStr.slice(4, 6), 10) - 1;
  const day = parseInt(expiryStr.slice(6, 8), 10);
  const expiryDate = new Date(year, month, day);
  return Math.max((expiryDate - fromDate) / (1000 * 60 * 60 * 24), 0);
}

/** Standard Black-Scholes European price + greeks for one leg. */
export function blackScholes(spot, strike, tYears, iv, right) {
  if (tYears <= 0 || iv <= 0) {
    const intrinsic = right === 'C' ? Math.max(spot - strike, 0) : Math.max(strike - spot, 0);
    return { price: intrinsic, delta: right === 'C' ? (spot > strike ? 1 : 0) : (spot < strike ? -1 : 0), gamma: 0, theta: 0, vega: 0 };
  }
  const sqrtT = Math.sqrt(tYears);
  const d1 = (Math.log(spot / strike) + (RISK_FREE_RATE + 0.5 * iv * iv) * tYears) / (iv * sqrtT);
  const d2 = d1 - iv * sqrtT;
  const Nd1 = normCdf(d1);
  const nD1 = normPdf(d1);
  const discK = strike * Math.exp(-RISK_FREE_RATE * tYears);

  let price, delta, theta;
  if (right === 'C') {
    price = spot * Nd1 - discK * normCdf(d2);
    delta = Nd1;
    theta = (-(spot * nD1 * iv) / (2 * sqrtT) - RISK_FREE_RATE * discK * normCdf(d2)) / 365;
  } else {
    price = discK * normCdf(-d2) - spot * normCdf(-d1);
    delta = Nd1 - 1;
    theta = (-(spot * nD1 * iv) / (2 * sqrtT) + RISK_FREE_RATE * discK * normCdf(-d2)) / 365;
  }
  const gamma = nD1 / (spot * iv * sqrtT);
  const vega = (spot * nD1 * sqrtT) / 100; // per 1 point (1%) change in IV

  return { price, delta, gamma, theta, vega };
}

/** Theoretical value of a leg if the underlying were at `spot` on `asOfDate`. */
export function legTheoreticalValue(leg, spot, asOfDate) {
  const daysRemaining = daysBetween(asOfDate, leg.expiry);
  if (daysRemaining <= 0) {
    return leg.right === 'C' ? Math.max(spot - leg.strike, 0) : Math.max(leg.strike - spot, 0);
  }
  const iv = syntheticIV(leg.strike, spot);
  return blackScholes(spot, leg.strike, daysRemaining / 365, iv, leg.right).price;
}

/**
 * Builds a P&L curve across a range of hypothetical future spot prices.
 * mode: 'atExpiry' values every leg at pure intrinsic value (works
 * correctly even for multi-expiry combos like calendar spreads, since "at
 * expiry" of the whole structure means every leg has expired).
 * mode: 'today' values every leg via Black-Scholes using ITS OWN real
 * days-to-expiry from today -- this is what lets a calendar spread's
 * near/far legs behave differently in the "today" curve.
 */
export function computePayoffCurve(legs, currentSpot, mode, spotRange) {
  const today = new Date();
  const legsWithEntry = legs.map((leg) => ({
    ...leg,
    entryPremium: leg.mid != null ? leg.mid : legTheoreticalValue(leg, currentSpot, today),
  }));

  return spotRange.map((futureSpot) => {
    let pnl = 0;
    for (const leg of legsWithEntry) {
      const value =
        mode === 'atExpiry'
          ? (leg.right === 'C' ? Math.max(futureSpot - leg.strike, 0) : Math.max(leg.strike - futureSpot, 0))
          : legTheoreticalValue(leg, futureSpot, today);
      const sign = leg.action === 'BUY' ? 1 : -1;
      pnl += sign * (value - leg.entryPremium) * leg.ratio * 100;
    }
    return { spot: futureSpot, pnl };
  });
}

/** Aggregate portfolio greeks today, using each leg's real days-to-expiry. */
export function computeAggregateGreeks(legs, currentSpot) {
  const today = new Date();
  let delta = 0, gamma = 0, theta = 0, vega = 0;
  for (const leg of legs) {
    const daysRemaining = Math.max(daysBetween(today, leg.expiry), 0.001);
    const iv = syntheticIV(leg.strike, currentSpot);
    const g = blackScholes(currentSpot, leg.strike, daysRemaining / 365, iv, leg.right);
    const sign = leg.action === 'BUY' ? 1 : -1;
    delta += sign * g.delta * leg.ratio;
    gamma += sign * g.gamma * leg.ratio;
    theta += sign * g.theta * leg.ratio;
    vega += sign * g.vega * leg.ratio;
  }
  return { delta, gamma, theta, vega };
}

/** Zero-crossings of the P&L curve via linear interpolation between grid points. */
export function findBreakevens(curve) {
  const breakevens = [];
  for (let i = 1; i < curve.length; i++) {
    const a = curve[i - 1], b = curve[i];
    if ((a.pnl <= 0 && b.pnl > 0) || (a.pnl >= 0 && b.pnl < 0)) {
      const t = a.pnl === b.pnl ? 0 : -a.pnl / (b.pnl - a.pnl);
      breakevens.push(a.spot + t * (b.spot - a.spot));
    }
  }
  return breakevens;
}

export function maxProfit(curve) {
  return Math.max(...curve.map((p) => p.pnl));
}

export function maxLoss(curve) {
  return Math.min(...curve.map((p) => p.pnl));
}

/**
 * "Uncapped" detection: a slope heuristic on the last few grid points at
 * each edge of the sampled spot range, NOT a true analytical check on the
 * strategy's structure. Works fine for the simple cases we support today
 * (naked long/short calls & puts inside straddles/strangles) where payoff
 * is genuinely linear past the sampled range; would need real per-preset
 * logic (e.g. explicit case analysis) for more exotic/asymmetric combos.
 */
export function detectUncapped(curve) {
  const n = curve.length;
  const totalPnlSwing = maxProfit(curve) - maxLoss(curve) || 1;
  const spotSpan = curve[n - 1].spot - curve[0].spot || 1;
  const flatThreshold = (totalPnlSwing / spotSpan) * 0.05; // 5% of avg curve slope

  const rightSlope = (curve[n - 1].pnl - curve[n - 3].pnl) / (curve[n - 1].spot - curve[n - 3].spot);
  const leftSlope = (curve[2].pnl - curve[0].pnl) / (curve[2].spot - curve[0].spot);

  return {
    uncappedUp: rightSlope > flatThreshold,
    uncappedDown: leftSlope < -flatThreshold,
  };
}

function interpolatePnl(curve, spot) {
  if (spot <= curve[0].spot) return curve[0].pnl;
  if (spot >= curve[curve.length - 1].spot) return curve[curve.length - 1].pnl;
  for (let i = 1; i < curve.length; i++) {
    if (spot <= curve[i].spot) {
      const a = curve[i - 1], b = curve[i];
      const t = (spot - a.spot) / (b.spot - a.spot);
      return a.pnl + t * (b.pnl - a.pnl);
    }
  }
  return curve[curve.length - 1].pnl;
}

/**
 * Probability of profit: a lognormal approximation of the underlying's
 * distribution at expiry using the SAME synthetic IV as the rest of this
 * module (averaged across legs) -- directionally useful for comparing
 * strategies, not the broker's own (often more careful) probability calc.
 */
export function computePOP(curve, breakevens, currentSpot, legs, daysToExpiry) {
  const avgIv = legs.reduce((sum, l) => sum + syntheticIV(l.strike, currentSpot), 0) / Math.max(legs.length, 1);
  const T = Math.max(daysToExpiry, 0.001) / 365;
  const sigma = avgIv;

  function lognormalCdf(x) {
    const d = (Math.log(x / currentSpot) - (RISK_FREE_RATE - 0.5 * sigma * sigma) * T) / (sigma * Math.sqrt(T));
    return normCdf(d);
  }

  const sortedBE = [...breakevens].sort((a, b) => a - b);
  const spotLow = curve[0].spot, spotHigh = curve[curve.length - 1].spot;
  const boundaries = [spotLow, ...sortedBE, spotHigh];

  let pop = 0;
  for (let i = 0; i < boundaries.length - 1; i++) {
    const mid = (boundaries[i] + boundaries[i + 1]) / 2;
    if (interpolatePnl(curve, mid) > 0) {
      const lo = i === 0 ? 0 : lognormalCdf(boundaries[i]);
      const hi = i === boundaries.length - 2 ? 1 : lognormalCdf(boundaries[i + 1]);
      pop += Math.max(hi - lo, 0);
    }
  }
  return Math.min(Math.max(pop, 0), 1);
}

/**
 * Margin required == max loss, which is correct for defined-risk
 * debit/credit spreads (verticals, iron condors, butterflies) but WRONG
 * for anything with undefined risk (a naked short leg, a short
 * straddle/strangle) -- real broker margin for those depends on account
 * rules/SPAN, not just max loss. Returns null (render as "N/A -- uncapped
 * risk") when the loss side is uncapped, so the UI doesn't show a
 * confidently-wrong number.
 */
export function estimateMarginRequired(maxLossValue, uncapped) {
  if (uncapped.uncappedDown || uncapped.uncappedUp) return null;
  return Math.abs(maxLossValue);
}

/** Sum of signed entry premiums right now: positive = net debit (you pay
 * to enter), negative = net credit (you receive). */
export function computeNetDebitCredit(legs, currentSpot) {
  const today = new Date();
  let net = 0;
  for (const leg of legs) {
    const premium = leg.mid != null ? leg.mid : legTheoreticalValue(leg, currentSpot, today);
    const sign = leg.action === 'BUY' ? 1 : -1;
    net += sign * premium * leg.ratio * 100;
  }
  return net;
}

export function earliestExpiry(legs) {
  return legs.reduce((min, l) => (min === null || l.expiry < min ? l.expiry : min), null);
}

export function daysToExpiryFromToday(expiryStr) {
  return Math.round(daysBetween(new Date(), expiryStr));
}
