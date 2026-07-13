import { GreeksBadge } from './GreeksBadge';

function Row({ row, onSelect }) {
  return (
    <tr onClick={() => onSelect(row)} className="chain-row">
      <td>{row.strike}</td>
      <td>{row.bid ?? '--'}</td>
      <td>{row.ask ?? '--'}</td>
      <td>{row.mid ?? '--'}</td>
      <td>{row.volume ?? 0}</td>
      <td><GreeksBadge {...row} /></td>
    </tr>
  );
}

export function OptionChainTable({ calls, puts, onSelect }) {
  return (
    <div className="chain-tables">
      <div>
        <h4>Calls</h4>
        <table>
          <thead><tr><th>Strike</th><th>Bid</th><th>Ask</th><th>Mid</th><th>Vol</th><th>Greeks</th></tr></thead>
          <tbody>
            {calls.map((row) => (
              <Row key={row.strike} row={{ ...row, right: 'C' }} onSelect={onSelect} />
            ))}
          </tbody>
        </table>
      </div>
      <div>
        <h4>Puts</h4>
        <table>
          <thead><tr><th>Strike</th><th>Bid</th><th>Ask</th><th>Mid</th><th>Vol</th><th>Greeks</th></tr></thead>
          <tbody>
            {puts.map((row) => (
              <Row key={row.strike} row={{ ...row, right: 'P' }} onSelect={onSelect} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
