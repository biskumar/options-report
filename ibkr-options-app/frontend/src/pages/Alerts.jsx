import { useEffect, useState } from 'react';
import { useLiveData } from '../state/LiveDataContext';
import { api } from '../utils/api';

const CONDITIONS = [
  { value: 'price_above', label: 'Price above' },
  { value: 'price_below', label: 'Price below' },
  { value: 'iv_above', label: 'IV % above' },
  { value: 'iv_below', label: 'IV % below' },
  { value: 'delta_above', label: 'Delta above' },
  { value: 'delta_below', label: 'Delta below' },
];

export function Alerts() {
  const { triggeredAlerts } = useLiveData();
  const [alerts, setAlerts] = useState([]);
  const [error, setError] = useState(null);

  const [symbol, setSymbol] = useState('');
  const [secType, setSecType] = useState('STK');
  const [expiry, setExpiry] = useState('');
  const [strike, setStrike] = useState('');
  const [right, setRight] = useState('C');
  const [condition, setCondition] = useState('price_above');
  const [threshold, setThreshold] = useState('');
  const [note, setNote] = useState('');

  async function load() {
    try {
      const data = await api.get('/api/alerts');
      setAlerts(data);
    } catch (e) {
      setError(e.message);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Refresh the list whenever a live alert_triggered event comes in over
  // the WebSocket, so status flips from active -> triggered without a
  // manual reload.
  useEffect(() => {
    if (triggeredAlerts.length > 0) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [triggeredAlerts.length]);

  async function createAlert(e) {
    e.preventDefault();
    setError(null);
    try {
      await api.post('/api/alerts', {
        symbol: symbol.toUpperCase(),
        secType,
        expiry: secType === 'OPT' ? expiry : null,
        strike: secType === 'OPT' ? parseFloat(strike) : null,
        right: secType === 'OPT' ? right : null,
        condition,
        threshold: parseFloat(threshold),
        note: note || null,
      });
      setThreshold('');
      setNote('');
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  async function removeAlert(id) {
    try {
      await api.del(`/api/alerts/${id}`);
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div className="page">
      <h2>Alerts</h2>
      {error && <p className="warning">{error}</p>}

      <form onSubmit={createAlert} className="order-form">
        <label>Symbol <input value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} required /></label>
        <label>Type
          <select value={secType} onChange={(e) => setSecType(e.target.value)}>
            <option value="STK">Stock</option>
            <option value="OPT">Option</option>
          </select>
        </label>
        {secType === 'OPT' && (
          <>
            <label>Expiry (YYYYMMDD) <input value={expiry} onChange={(e) => setExpiry(e.target.value)} required /></label>
            <label>Strike <input type="number" step="0.5" value={strike} onChange={(e) => setStrike(e.target.value)} required /></label>
            <label>Right
              <select value={right} onChange={(e) => setRight(e.target.value)}>
                <option value="C">Call</option>
                <option value="P">Put</option>
              </select>
            </label>
          </>
        )}
        <label>Condition
          <select value={condition} onChange={(e) => setCondition(e.target.value)}>
            {CONDITIONS.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
          </select>
        </label>
        <label>Threshold <input type="number" step="0.01" value={threshold} onChange={(e) => setThreshold(e.target.value)} required /></label>
        <label>Note (optional) <input value={note} onChange={(e) => setNote(e.target.value)} /></label>
        <button type="submit">Create alert</button>
      </form>

      <h3>Rules</h3>
      <table>
        <thead>
          <tr><th>Symbol</th><th>Type</th><th>Condition</th><th>Threshold</th><th>Status</th><th>Last value</th><th></th></tr>
        </thead>
        <tbody>
          {alerts.map((a) => (
            <tr key={a.id}>
              <td>{a.symbol}{a.secType === 'OPT' ? ` ${a.expiry} ${a.strike}${a.right}` : ''}</td>
              <td>{a.secType}</td>
              <td>{a.condition}</td>
              <td>{a.threshold}</td>
              <td>{a.triggered ? 'Triggered' : a.active ? 'Active' : 'Inactive'}</td>
              <td>{a.lastValue ?? '--'}</td>
              <td><button onClick={() => removeAlert(a.id)}>Delete</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
