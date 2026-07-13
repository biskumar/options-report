import { useState } from 'react';
import { formatMoney } from '../utils/format';

export function PositionRow({ position, onSell, sellDisabled }) {
  const [limitPrice, setLimitPrice] = useState('');
  const showSellColumn = typeof onSell === 'function';
  const canSell = showSellColumn && position.secType === 'OPT' && position.position > 0;

  return (
    <tr>
      <td>{position.symbol}</td>
      <td>{position.secType}</td>
      <td>{position.expiry ?? '--'}</td>
      <td>{position.strike ?? '--'}</td>
      <td>{position.right ?? '--'}</td>
      <td>{position.position}</td>
      <td>{formatMoney(position.avgCost)}</td>
      <td>{formatMoney(position.marketPrice)}</td>
      <td>{formatMoney(position.unrealizedPnL)}</td>
      {showSellColumn && (
        <td>
          {canSell && (
            <div className="position-sell-row">
              <input
                type="number" step="0.01" placeholder="Limit"
                value={limitPrice} onChange={(e) => setLimitPrice(e.target.value)}
              />
              <button
                disabled={sellDisabled || !limitPrice}
                onClick={() => onSell(position, limitPrice)}
              >
                Sell
              </button>
            </div>
          )}
        </td>
      )}
    </tr>
  );
}
