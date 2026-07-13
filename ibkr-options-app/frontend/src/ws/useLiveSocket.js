import { useEffect, useRef, useState } from 'react';
import { WS_URL } from '../config';

const MAX_BACKOFF_MS = 8000;
const MAX_ATTEMPTS = 6;

export function useLiveSocket(onMessage) {
  const [wsStatus, setWsStatus] = useState('connecting');
  const attemptsRef = useRef(0);
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;

  useEffect(() => {
    let socket;
    let reconnectTimer;
    let cancelled = false;

    function connect() {
      setWsStatus('connecting');
      socket = new WebSocket(WS_URL);

      socket.onopen = () => {
        attemptsRef.current = 0;
        setWsStatus('open');
      };

      socket.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          onMessageRef.current?.(msg);
        } catch {
          // ignore malformed frames
        }
      };

      socket.onclose = () => {
        if (cancelled) return;
        setWsStatus('closed');
        if (attemptsRef.current >= MAX_ATTEMPTS) {
          setWsStatus('gave-up');
          return;
        }
        const delay = Math.min(1000 * 2 ** attemptsRef.current, MAX_BACKOFF_MS);
        attemptsRef.current += 1;
        reconnectTimer = setTimeout(connect, delay);
      };

      socket.onerror = () => {
        socket.close();
      };
    }

    connect();
    return () => {
      cancelled = true;
      clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, []);

  return wsStatus;
}
