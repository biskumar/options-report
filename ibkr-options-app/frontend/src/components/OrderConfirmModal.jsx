import { useState } from 'react';
import { formatMoney } from '../utils/format';

export function OrderConfirmModal({ preview, onConfirm, onCancel, disabled }) {
  const [submitting, setSubmitting] = useState(false);

  if (!preview) return null;
  const isCombo = preview.legs.length > 1 || preview.legs[0]?.action !== undefined;
  const symbol = preview.symbol || preview.legs[0]?.symbol;

  async function handleConfirm() {
    setSubmitting(true);
    try {
      await onConfirm(preview.previewId);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="modal-backdrop">
      <div className="modal">
        <h3>Review order {preview.dryRun && <span className="tag">DRY RUN</span>}</h3>
        <table className="review-table">
          <tbody>
            <tr><td>Symbol</td><td>{symbol}</td></tr>
            {isCombo ? (
              <tr>
                <td>Legs</td>
                <td>
                  <table>
                    <thead><tr><th>Expiry</th><th>Strike</th><th>Right</th><th>Action</th><th>Ratio</th><th>Bid/Ask</th></tr></thead>
                    <tbody>
                      {preview.legs.map((l, i) => (
                        <tr key={i}>
                          <td>{l.expiry}</td><td>{l.strike}</td><td>{l.right}</td><td>{l.action}</td><td>{l.ratio}</td>
                          <td>{l.bid ?? '--'}/{l.ask ?? '--'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </td>
              </tr>
            ) : null}
            {isCombo ? (
              <tr><td>Quantity (combo units)</td><td>{preview.quantity}</td></tr>
            ) : (
              <>
                <tr><td>Expiry</td><td>{preview.legs[0].expiry}</td></tr>
                <tr><td>Strike / Right</td><td>{preview.legs[0].strike} {preview.legs[0].right}</td></tr>
                <tr><td>Side</td><td>{preview.legs[0].side.toUpperCase()}</td></tr>
                <tr><td>Quantity</td><td>{preview.legs[0].quantity}</td></tr>
                <tr><td>Live bid / ask</td><td>{preview.legs[0].bid ?? '--'} / {preview.legs[0].ask ?? '--'}</td></tr>
              </>
            )}
            <tr><td>Order type</td><td>{preview.orderType}</td></tr>
            {preview.limitPrice != null && <tr><td>Limit price</td><td>{preview.limitPrice}</td></tr>}
            {preview.stopPrice != null && <tr><td>Stop price</td><td>{preview.stopPrice}</td></tr>}
            {isCombo && <tr><td>Net mid (+debit/-credit)</td><td>{preview.netMid ?? '--'}</td></tr>}
            <tr><td>Est. cost</td><td>{formatMoney(preview.estCost)}</td></tr>
          </tbody>
        </table>
        {disabled && <p className="warning">Trading is currently blocked -- cannot submit.</p>}
        <div className="modal-actions">
          <button onClick={onCancel} disabled={submitting}>Cancel</button>
          <button
            className="confirm-btn"
            onClick={handleConfirm}
            disabled={disabled || submitting}
          >
            {submitting ? 'Submitting…' : 'Confirm & Submit'}
          </button>
        </div>
      </div>
    </div>
  );
}
