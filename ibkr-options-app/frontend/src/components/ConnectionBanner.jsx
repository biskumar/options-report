import { useEffect, useState } from 'react';
import { useLiveData } from '../state/LiveDataContext';
import { api } from '../utils/api';

export function isTradingBlocked({ connection, killSwitch }) {
  return killSwitch.engaged || connection.status !== 'connected';
}

function ModeBadge({ allowOrders }) {
  if (allowOrders === null) return null;
  return <span className="tag mode-badge">{allowOrders ? 'Live' : 'Mock'}</span>;
}

export function ConnectionBanner() {
  const { connection, killSwitch } = useLiveData();
  const [allowOrders, setAllowOrders] = useState(null);

  useEffect(() => {
    api.get('/api/health').then((h) => setAllowOrders(h.allowOrders)).catch(() => {});
  }, []);

  async function toggleKillSwitch() {
    await api.post('/api/killswitch', { engaged: !killSwitch.engaged, reason: 'manual toggle' });
  }

  async function reconnect() {
    await api.post('/api/account/reconnect');
  }

  if (killSwitch.engaged) {
    return (
      <div className="banner banner-danger">
        <span>ORDER SUBMISSION DISABLED {killSwitch.reason ? `(${killSwitch.reason})` : ''}</span>
        <span className="banner-right">
          <ModeBadge allowOrders={allowOrders} />
          <button onClick={toggleKillSwitch}>Re-enable trading</button>
        </span>
      </div>
    );
  }

  if (connection.status !== 'connected') {
    return (
      <div className="banner banner-danger">
        <span>
          Disconnected from IBKR{connection.lastError ? ` — ${connection.lastError}` : ''} — orders blocked
        </span>
        <span className="banner-right">
          <ModeBadge allowOrders={allowOrders} />
          <button onClick={reconnect}>Reconnect</button>
        </span>
      </div>
    );
  }

  return (
    <div className="banner banner-nominal">
      <span><span className="status-dot status-dot-ok" />Connected to IBKR — {connection.host}:{connection.port}</span>
      <span className="banner-right">
        <ModeBadge allowOrders={allowOrders} />
        <button onClick={toggleKillSwitch}>Kill switch</button>
      </span>
    </div>
  );
}
