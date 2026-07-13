import { useState } from 'react';
import { formatMoney } from '../utils/format';

const ROLE_LABEL = { entry: 'Entry', target: 'Target (profit)', stop: 'Stop (loss)' };

export function BracketConfirmModal({ preview, onConfirm, onCancel, disabled }) {
  const [submitting, setSubmitting] = useState(false);

  if (!preview) return null;

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
        <h3>Review bracket order {preview.dryRun && <span className="tag">DRY RUN</span>}</h3>
        <table className="review-table">
          <tbody>
            <tr><td>Symbol</td><td>{preview.symbol}</td></tr>
            <tr><td>Expiry / Strike / Right</td><td>{preview.expiry} {preview.strike} {preview.right}</td></tr>
            <tr><td>Quantity</td><td>{preview.quantity}</td></tr>
            <tr><td>Live bid / ask</td><td>{preview.bid ?? '--'} / {preview.ask ?? '--'}</td></tr>
            <tr>
              <td>Legs</td>
              <td>
                <table>
                  <thead><tr><th>Leg</th><th>Action</th><th>Type</th><th>Price</th></tr></thead>
                  <tbody>
                    {preview.legs.map((l, i) => (
                      <tr key={i}>
                        <td>{ROLE_LABEL[l.role] || l.role}</td>
                        <td>{l.action}</td>
                        <td>{l.orderType}</td>
                        <td>{l.price}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </td>
            </tr>
            <tr><td>Est. cost (entry)</td><td>{formatMoney(preview.estCost)}</td></tr>
          </tbody>
        </table>
        <p className="payoff-note">
          All three legs are linked -- the entry (limit) triggers first, and whichever exit (target or stop) fills first
          automatically cancels the other. Time in force is DAY on all legs.
        </p>
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
