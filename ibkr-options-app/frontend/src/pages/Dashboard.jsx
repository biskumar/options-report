import { useEffect, useState } from 'react';
import { PositionRow } from '../components/PositionRow';
import { useLiveData } from '../state/LiveDataContext';
import { api } from '../utils/api';
import { formatMoney } from '../utils/format';

export function Dashboard() {
  const { pnl } = useLiveData();
  const [summary, setSummary] = useState([]);
  const [positions, setPositions] = useState([]);
  const [orders, setOrders] = useState([]);
  const [error, setError] = useState(null);

  function refresh() {
    api.get('/api/account/summary').then(setSummary).catch((e) => setError(e.message));
    api.get('/api/positions').then(setPositions).catch((e) => setError(e.message));
    api.get('/api/orders').then(setOrders).catch((e) => setError(e.message));
  }

  useEffect(refresh, []);

  async function cancelOrder(orderId) {
    try {
      await api.post(`/api/orders/${orderId}/cancel`);
      refresh();
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div className="page">
      <h2>Dashboard</h2>
      {error && <p className="warning">{error}</p>}

      <h3>Account summary</h3>
      <table>
        <thead><tr><th>Account</th><th>Net Liq</th><th>Buying Power</th><th>Cash</th></tr></thead>
        <tbody>
          {summary.map((a) => (
            <tr key={a.account}>
              <td>{a.account}</td>
              <td>{formatMoney(a.netLiquidation)}</td>
              <td>{formatMoney(a.buyingPower)}</td>
              <td>{formatMoney(a.totalCashValue)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>Live P&L</h3>
      <table>
        <thead><tr><th>Account</th><th>Daily</th><th>Unrealized</th><th>Realized</th></tr></thead>
        <tbody>
          {Object.values(pnl).map((p) => (
            <tr key={p.account}>
              <td>{p.account}</td>
              <td>{formatMoney(p.dailyPnL)}</td>
              <td>{formatMoney(p.unrealizedPnL)}</td>
              <td>{formatMoney(p.realizedPnL)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>Positions</h3>
      <table>
        <thead>
          <tr><th>Symbol</th><th>Type</th><th>Expiry</th><th>Strike</th><th>Right</th><th>Qty</th><th>Avg cost</th><th>Mkt price</th><th>Unrealized</th></tr>
        </thead>
        <tbody>
          {positions.map((p) => <PositionRow key={p.conId} position={p} />)}
        </tbody>
      </table>

      <h3>Open Orders</h3>
      <table>
        <thead>
          <tr><th>ID</th><th>Symbol</th><th>Action</th><th>Type</th><th>Qty</th><th>Limit</th><th>Status</th><th>Filled</th><th></th></tr>
        </thead>
        <tbody>
          {orders.map((o) => (
            <tr key={o.orderId}>
              <td>{o.orderId}</td>
              <td>{o.symbol}</td>
              <td>{o.action}</td>
              <td>{o.orderType}</td>
              <td>{o.totalQuantity}</td>
              <td>{o.lmtPrice ?? '--'}</td>
              <td>{o.status}</td>
              <td>{o.filled}</td>
              <td>
                {o.remaining > 0 && <button onClick={() => cancelOrder(o.orderId)}>Cancel</button>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button onClick={refresh}>Refresh</button>
    </div>
  );
}
