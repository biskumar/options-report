import { createContext, useCallback, useContext, useReducer } from 'react';
import { useLiveSocket } from '../ws/useLiveSocket';

const LiveDataContext = createContext(null);

const initialState = {
  connection: { status: 'disconnected', host: null, port: null, clientId: null, lastError: null },
  killSwitch: { engaged: false, engagedAt: null, reason: null },
  positions: {},
  pnl: {},
  quotes: {},
  orderEvents: [],
  triggeredAlerts: [],
};

function reducer(state, action) {
  switch (action.type) {
    case 'connection':
      return { ...state, connection: action.data };
    case 'killswitch':
      return { ...state, killSwitch: action.data };
    case 'position':
      return { ...state, positions: { ...state.positions, [action.data.conId]: action.data } };
    case 'pnl':
      return { ...state, pnl: { ...state.pnl, [action.data.account]: action.data } };
    case 'quote':
      return { ...state, quotes: { ...state.quotes, [action.data.conId]: action.data } };
    case 'order_status':
    case 'execution':
      return { ...state, orderEvents: [action.data, ...state.orderEvents].slice(0, 50) };
    case 'alert_triggered':
      return { ...state, triggeredAlerts: [action.data, ...state.triggeredAlerts].slice(0, 50) };
    default:
      return state;
  }
}

export function LiveDataProvider({ children }) {
  const [state, dispatch] = useReducer(reducer, initialState);

  const handleMessage = useCallback((msg) => {
    if (msg?.type) dispatch({ type: msg.type, data: msg.data });
  }, []);

  const wsStatus = useLiveSocket(handleMessage);

  return (
    <LiveDataContext.Provider value={{ ...state, wsStatus }}>
      {children}
    </LiveDataContext.Provider>
  );
}

export function useLiveData() {
  const ctx = useContext(LiveDataContext);
  if (!ctx) throw new Error('useLiveData must be used within a LiveDataProvider');
  return ctx;
}
