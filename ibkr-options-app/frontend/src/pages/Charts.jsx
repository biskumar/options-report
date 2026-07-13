import { createChart } from 'lightweight-charts';
import { useEffect, useRef, useState } from 'react';
import { api } from '../utils/api';

function toLineData(bars, values) {
  return bars
    .map((b, i) => ({ time: b.time, value: values[i] }))
    .filter((d) => d.value !== null && d.value !== undefined);
}

export function Charts() {
  const [symbol, setSymbol] = useState('AAPL');
  const [period, setPeriod] = useState('6mo');
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  const priceContainerRef = useRef(null);
  const rsiContainerRef = useRef(null);

  async function load() {
    setError(null);
    try {
      const res = await api.get(`/api/technicals/${encodeURIComponent(symbol)}?period=${period}&interval=1d`);
      setData(res);
    } catch (e) {
      setError(e.message);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!data || !priceContainerRef.current || !rsiContainerRef.current) return;

    const priceChart = createChart(priceContainerRef.current, {
      width: priceContainerRef.current.clientWidth,
      height: 320,
      layout: { background: { color: '#ffffff' }, textColor: '#2b1810' },
      grid: { vertLines: { color: '#eef0f5' }, horzLines: { color: '#eef0f5' } },
      timeScale: { timeVisible: false },
    });

    const candleSeries = priceChart.addCandlestickSeries({
      upColor: '#1c8c4b', downColor: '#e5484d', borderVisible: false,
      wickUpColor: '#1c8c4b', wickDownColor: '#e5484d',
    });
    candleSeries.setData(data.bars.map((b) => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close })));

    const ema21Series = priceChart.addLineSeries({ color: '#2563eb', lineWidth: 1 });
    ema21Series.setData(toLineData(data.bars, data.ema21));
    const ema50Series = priceChart.addLineSeries({ color: '#d97706', lineWidth: 1 });
    ema50Series.setData(toLineData(data.bars, data.ema50));
    const ema200Series = priceChart.addLineSeries({ color: '#6c5ce7', lineWidth: 1 });
    ema200Series.setData(toLineData(data.bars, data.ema200));
    const bbUpperSeries = priceChart.addLineSeries({ color: '#9ca3af', lineWidth: 1, lineStyle: 2 });
    bbUpperSeries.setData(toLineData(data.bars, data.bbUpper));
    const bbLowerSeries = priceChart.addLineSeries({ color: '#9ca3af', lineWidth: 1, lineStyle: 2 });
    bbLowerSeries.setData(toLineData(data.bars, data.bbLower));

    const rsiChart = createChart(rsiContainerRef.current, {
      width: rsiContainerRef.current.clientWidth,
      height: 120,
      layout: { background: { color: '#ffffff' }, textColor: '#2b1810' },
      grid: { vertLines: { color: '#eef0f5' }, horzLines: { color: '#eef0f5' } },
    });
    const rsiSeries = rsiChart.addLineSeries({ color: '#0ea5e9', lineWidth: 1 });
    rsiSeries.setData(toLineData(data.bars, data.rsi));

    priceChart.timeScale().fitContent();
    rsiChart.timeScale().fitContent();

    function handleResize() {
      priceChart.applyOptions({ width: priceContainerRef.current.clientWidth });
      rsiChart.applyOptions({ width: rsiContainerRef.current.clientWidth });
    }
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      priceChart.remove();
      rsiChart.remove();
    };
  }, [data]);

  return (
    <div className="page">
      <h2>Charts</h2>
      {error && <p className="warning">{error}</p>}
      <div className="chart-controls">
        <input value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} onKeyDown={(e) => e.key === 'Enter' && load()} />
        <select value={period} onChange={(e) => setPeriod(e.target.value)}>
          <option value="1mo">1M</option>
          <option value="3mo">3M</option>
          <option value="6mo">6M</option>
          <option value="1y">1Y</option>
        </select>
        <button onClick={load}>Load</button>
      </div>
      <p className="payoff-note">
        Candles + EMA21 (blue) / EMA50 (amber) / EMA200 (purple) / Bollinger 20,2 (dashed grey). RSI(14) below.
      </p>
      <div ref={priceContainerRef} />
      <div ref={rsiContainerRef} />
    </div>
  );
}
