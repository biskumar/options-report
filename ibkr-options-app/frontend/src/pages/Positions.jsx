import { useEffect, useState } from 'react';
import { isTradingBlocked } from '../components/ConnectionBanner';
import { OrderConfirmModal } from '../components/OrderConfirmModal';
import { PositionRow } from '../components/PositionRow';
import { useLiveData } from '../state/LiveDataContext';
import { api } from '../utils/api';

export function Positions() {
  const liveData = useLiveData();
  const blocked = isTradingBlocked(liveData);

  const [positions, setPositions] = useState([]);
  const [orders, setOrders] = useState([]);
  const [error, setError] = useState(null);
  const [preview, setPreview] = useState(null);
  const [result, setResult] = useState(null);

  function refresh() {
    api.get('/api/positions').then(setPositions).catch((e) => setError(e.message));
    api.get('/api/orders').then(setOrders).catch((e) => setError(e.message));
  }

  useEffect(refresh, []);

  async function cancel(orderId) {
    await api.post(`/api/orders/${orderId}/cancel`);
    refresh();
  }

  async function sellPosition(position, limitPrice) {
    setError(null);
    setResult(null);
    try {
      const body = {
        symbol: position.symbol,
        expiry: position.expiry,
        strike: position.strike,
        right: position.right,
        side: 'sell',
        quantity: Math.abs(position.position),
        orderType: 'limit',
        limitPrice: parseFloat(limitPrice),
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
      refresh();
    } catch (err) {
      setError(err.message);
      setPreview(null);
    }
  }

  return (
    <div className="page">
      <h2>Positions & Orders</h2>
      {error && <p className="warning">{error}</p>}
      {result && (
        <p className="tag">
          {result.dryRun ? 'DRY RUN — ' : ''}Order {result.status} {result.orderId ? `(id ${result.orderId})` : ''}
        </p>
      )}

      <h3>Positions</h3>
      <table>
        <thead>
          <tr>
            <th>Symbol</th><th>Type</th><th>Expiry</th><th>Strike</th><th>Right</th><th>Qty</th>
            <th>Avg cost</th><th>Mkt price</th><th>Unrealized</th><th>Sell (limit, day)</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((p) => (
            <PositionRow key={p.conId} position={p} onSell={sellPosition} sellDisabled={blocked} />
          ))}
        </tbody>
      </table>
      {blocked && <p className="warning">Trading is blocked — connect to IBKR and/or disengage the kill switch.</p>}

      <h3>Orders</h3>
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
                {o.remaining > 0 && <button onClick={() => cancel(o.orderId)}>Cancel</button>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button onClick={refresh}>Refresh</button>

      <OrderConfirmModal
        preview={preview}
        disabled={blocked}
        onConfirm={handleConfirm}
        onCancel={() => setPreview(null)}
      />
    </div>
  );
}
