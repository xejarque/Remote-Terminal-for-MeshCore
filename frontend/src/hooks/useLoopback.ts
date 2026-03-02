import { useState, useCallback, useRef, useEffect } from 'react';

export type LoopbackStatus = 'idle' | 'connecting' | 'connected' | 'error';
export type LoopbackTransportType = 'serial' | 'ble';

// Nordic UART Service UUIDs (used by MeshCore BLE)
const UART_SERVICE_UUID = '6e400001-b5a3-f393-e0a9-e50e24dcca9e';
const UART_TX_CHAR_UUID = '6e400003-b5a3-f393-e0a9-e50e24dcca9e'; // notifications from radio
const UART_RX_CHAR_UUID = '6e400002-b5a3-f393-e0a9-e50e24dcca9e'; // write to radio

function getTransportWsUrl(): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const isDev = window.location.port === '5173';
  return isDev
    ? `ws://localhost:8000/api/ws/transport`
    : `${protocol}//${window.location.host}/api/ws/transport`;
}

export interface UseLoopbackReturn {
  status: LoopbackStatus;
  error: string | null;
  transportType: LoopbackTransportType | null;
  serialAvailable: boolean;
  bluetoothAvailable: boolean;
  connectSerial: (baudRate?: number) => Promise<void>;
  connectBluetooth: () => Promise<void>;
  disconnect: () => void;
}

export function useLoopback(onConnected?: () => void): UseLoopbackReturn {
  const [status, setStatus] = useState<LoopbackStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const [transportType, setTransportType] = useState<LoopbackTransportType | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const serialPortRef = useRef<SerialPort | null>(null);
  const serialReaderRef = useRef<ReadableStreamDefaultReader<Uint8Array> | null>(null);
  const bleDeviceRef = useRef<BluetoothDevice | null>(null);
  const cleaningUpRef = useRef(false);

  const serialAvailable = typeof navigator !== 'undefined' && 'serial' in navigator;
  const bluetoothAvailable = typeof navigator !== 'undefined' && 'bluetooth' in navigator;

  const cleanup = useCallback(() => {
    if (cleaningUpRef.current) return;
    cleaningUpRef.current = true;

    // Close WebSocket
    const ws = wsRef.current;
    if (ws && ws.readyState <= WebSocket.OPEN) {
      try {
        ws.close();
      } catch {
        // ignore
      }
    }
    wsRef.current = null;

    // Close serial reader and port
    const reader = serialReaderRef.current;
    if (reader) {
      try {
        reader.cancel();
      } catch {
        // ignore
      }
    }
    serialReaderRef.current = null;

    const port = serialPortRef.current;
    if (port) {
      try {
        port.close();
      } catch {
        // ignore
      }
    }
    serialPortRef.current = null;

    // Disconnect BLE
    const bleDevice = bleDeviceRef.current;
    if (bleDevice?.gatt?.connected) {
      try {
        bleDevice.gatt.disconnect();
      } catch {
        // ignore
      }
    }
    bleDeviceRef.current = null;

    setTransportType(null);
    setStatus('idle');
    cleaningUpRef.current = false;
  }, []);

  // Cleanup on unmount
  useEffect(() => cleanup, [cleanup]);

  const connectSerial = useCallback(
    async (baudRate = 115200) => {
      setError(null);
      setStatus('connecting');
      setTransportType('serial');

      try {
        // Request serial port from user
        const port = await navigator.serial!.requestPort();
        await port.open({ baudRate, flowControl: 'none' });

        // Match meshcore serial behaviour
        try {
          await port.setSignals({ requestToSend: false });
        } catch {
          // Not all adapters support setSignals
        }

        serialPortRef.current = port;

        // Open transport WebSocket
        const ws = new WebSocket(getTransportWsUrl());
        ws.binaryType = 'arraybuffer';
        wsRef.current = ws;

        await new Promise<void>((resolve, reject) => {
          ws.onopen = () => resolve();
          ws.onerror = () => reject(new Error('Transport WebSocket failed to connect'));
          // Timeout
          const timeout = setTimeout(() => reject(new Error('Transport WebSocket timeout')), 10000);
          ws.addEventListener('open', () => clearTimeout(timeout), { once: true });
        });

        // Send init
        ws.send(JSON.stringify({ type: 'init', mode: 'serial' }));

        // Start serial → WS read loop
        const reader = port.readable!.getReader();
        serialReaderRef.current = reader;

        const readLoop = async () => {
          try {
            while (true) {
              const { value, done } = await reader.read();
              if (done) break;
              if (value && ws.readyState === WebSocket.OPEN) {
                ws.send(value);
              }
            }
          } catch (err) {
            // Reader cancelled or port closed — expected during disconnect
            if (!cleaningUpRef.current) {
              console.debug('Serial read loop ended:', err);
            }
          }
        };
        readLoop();

        // WS → serial write
        ws.onmessage = async (event) => {
          if (event.data instanceof ArrayBuffer) {
            const writer = port.writable!.getWriter();
            try {
              await writer.write(new Uint8Array(event.data));
            } finally {
              writer.releaseLock();
            }
          } else if (typeof event.data === 'string') {
            try {
              const msg = JSON.parse(event.data);
              if (msg.type === 'disconnect') {
                cleanup();
              }
            } catch {
              // ignore non-JSON text
            }
          }
        };

        ws.onclose = () => {
          if (!cleaningUpRef.current) {
            cleanup();
          }
        };

        ws.onerror = () => {
          if (!cleaningUpRef.current) {
            setError('Transport WebSocket error');
            cleanup();
            setStatus('error');
          }
        };

        setStatus('connected');
        onConnected?.();
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Serial connection failed';
        // Don't show error for user-cancelled port picker
        if (err instanceof DOMException && err.name === 'NotFoundError') {
          setStatus('idle');
          setTransportType(null);
          return;
        }
        setError(message);
        cleanup();
        setStatus('error');
      }
    },
    [cleanup, onConnected]
  );

  const connectBluetooth = useCallback(async () => {
    setError(null);
    setStatus('connecting');
    setTransportType('ble');

    try {
      const device = await navigator.bluetooth!.requestDevice({
        filters: [{ namePrefix: 'MeshCore' }],
        optionalServices: [UART_SERVICE_UUID],
      });

      if (!device.gatt) {
        throw new Error('Bluetooth GATT not available');
      }

      bleDeviceRef.current = device;

      const server = await device.gatt.connect();
      const service = await server.getPrimaryService(UART_SERVICE_UUID);
      const txChar = await service.getCharacteristic(UART_TX_CHAR_UUID);
      const rxChar = await service.getCharacteristic(UART_RX_CHAR_UUID);

      // Open transport WebSocket
      const ws = new WebSocket(getTransportWsUrl());
      ws.binaryType = 'arraybuffer';
      wsRef.current = ws;

      await new Promise<void>((resolve, reject) => {
        ws.onopen = () => resolve();
        ws.onerror = () => reject(new Error('Transport WebSocket failed to connect'));
        const timeout = setTimeout(() => reject(new Error('Transport WebSocket timeout')), 10000);
        ws.addEventListener('open', () => clearTimeout(timeout), { once: true });
      });

      // Send init
      ws.send(JSON.stringify({ type: 'init', mode: 'ble' }));

      // BLE RX notifications → WS
      await txChar.startNotifications();
      txChar.addEventListener('characteristicvaluechanged', (event) => {
        const value = (event.target as BluetoothRemoteGATTCharacteristic).value;
        if (value && ws.readyState === WebSocket.OPEN) {
          ws.send(value.buffer);
        }
      });

      // WS → BLE TX
      ws.onmessage = async (event) => {
        if (event.data instanceof ArrayBuffer) {
          await rxChar.writeValueWithResponse(new Uint8Array(event.data));
        } else if (typeof event.data === 'string') {
          try {
            const msg = JSON.parse(event.data);
            if (msg.type === 'disconnect') {
              cleanup();
            }
          } catch {
            // ignore non-JSON text
          }
        }
      };

      ws.onclose = () => {
        if (!cleaningUpRef.current) {
          cleanup();
        }
      };

      ws.onerror = () => {
        if (!cleaningUpRef.current) {
          setError('Transport WebSocket error');
          cleanup();
          setStatus('error');
        }
      };

      // Handle BLE disconnect
      device.addEventListener('gattserverdisconnected', () => {
        if (!cleaningUpRef.current) {
          cleanup();
        }
      });

      setStatus('connected');
      onConnected?.();
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Bluetooth connection failed';
      // Don't show error for user-cancelled device picker
      if (err instanceof DOMException && err.name === 'NotFoundError') {
        setStatus('idle');
        setTransportType(null);
        return;
      }
      setError(message);
      cleanup();
      setStatus('error');
    }
  }, [cleanup, onConnected]);

  const disconnect = useCallback(() => {
    // Send graceful disconnect before cleanup
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      try {
        ws.send(JSON.stringify({ type: 'disconnect' }));
      } catch {
        // ignore
      }
    }
    cleanup();
  }, [cleanup]);

  return {
    status,
    error,
    transportType,
    serialAvailable,
    bluetoothAvailable,
    connectSerial,
    connectBluetooth,
    disconnect,
  };
}
