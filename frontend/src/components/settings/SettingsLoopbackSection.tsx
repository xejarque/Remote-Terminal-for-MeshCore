import { useState } from 'react';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { Label } from '../ui/label';
import { Separator } from '../ui/separator';
import type { UseLoopbackReturn } from '../../hooks/useLoopback';

export function SettingsLoopbackSection({
  loopback,
  className,
}: {
  loopback: UseLoopbackReturn;
  className?: string;
}) {
  const {
    status,
    error,
    transportType,
    serialAvailable,
    bluetoothAvailable,
    connectSerial,
    connectBluetooth,
    disconnect,
  } = loopback;

  const [baudRate, setBaudRate] = useState('115200');
  const [selectedTransport, setSelectedTransport] = useState<'serial' | 'ble'>(
    serialAvailable ? 'serial' : 'ble'
  );

  const isConnecting = status === 'connecting';
  const isConnected = status === 'connected';
  const busy = isConnecting || isConnected;

  const handleConnect = async () => {
    if (selectedTransport === 'serial') {
      await connectSerial(parseInt(baudRate, 10) || 115200);
    } else {
      await connectBluetooth();
    }
  };

  const neitherAvailable = !serialAvailable && !bluetoothAvailable;

  return (
    <div className={className}>
      <p className="text-sm text-muted-foreground">
        No direct radio connection detected. You can bridge a radio connected to{' '}
        <em>this browser's device</em> via Web Serial or Web Bluetooth.
      </p>

      {neitherAvailable && (
        <div className="rounded-md bg-yellow-500/10 border border-yellow-500/30 p-3 text-sm text-yellow-200">
          Your browser does not support Web Serial or Web Bluetooth. Use Chrome or Edge on a secure
          context (HTTPS or localhost).
        </div>
      )}

      {!neitherAvailable && (
        <>
          {isConnected ? (
            <>
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-green-500" />
                <span className="text-sm">
                  Connected via {transportType === 'serial' ? 'Serial' : 'Bluetooth'}
                </span>
              </div>

              <Button variant="outline" onClick={disconnect} className="w-full">
                Disconnect Loopback
              </Button>
            </>
          ) : (
            <>
              {/* Transport selector */}
              <div className="space-y-2">
                <Label>Transport</Label>
                <div className="flex gap-2">
                  <Button
                    variant={selectedTransport === 'serial' ? 'default' : 'outline'}
                    size="sm"
                    disabled={!serialAvailable || busy}
                    onClick={() => setSelectedTransport('serial')}
                  >
                    Serial
                  </Button>
                  <Button
                    variant={selectedTransport === 'ble' ? 'default' : 'outline'}
                    size="sm"
                    disabled={!bluetoothAvailable || busy}
                    onClick={() => setSelectedTransport('ble')}
                  >
                    Bluetooth
                  </Button>
                </div>
                {!serialAvailable && (
                  <p className="text-xs text-muted-foreground">
                    Web Serial not available in this browser
                  </p>
                )}
                {!bluetoothAvailable && (
                  <p className="text-xs text-muted-foreground">
                    Web Bluetooth not available in this browser
                  </p>
                )}
              </div>

              {/* Baud rate (serial only) */}
              {selectedTransport === 'serial' && (
                <div className="space-y-2">
                  <Label htmlFor="loopback-baud">Baud Rate</Label>
                  <Input
                    id="loopback-baud"
                    type="number"
                    value={baudRate}
                    onChange={(e) => setBaudRate(e.target.value)}
                    disabled={busy}
                  />
                </div>
              )}

              <Separator />

              <Button onClick={handleConnect} disabled={busy} className="w-full">
                {isConnecting ? 'Connecting...' : 'Connect via Loopback'}
              </Button>
            </>
          )}
        </>
      )}

      {error && <div className="text-sm text-destructive">{error}</div>}
    </div>
  );
}
