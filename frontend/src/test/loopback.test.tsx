import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import { SettingsLoopbackSection } from '../components/settings/SettingsLoopbackSection';
import type { UseLoopbackReturn } from '../hooks/useLoopback';

function makeLoopback(overrides?: Partial<UseLoopbackReturn>): UseLoopbackReturn {
  return {
    status: 'idle',
    error: null,
    transportType: null,
    serialAvailable: true,
    bluetoothAvailable: true,
    connectSerial: vi.fn(async () => {}),
    connectBluetooth: vi.fn(async () => {}),
    disconnect: vi.fn(),
    ...overrides,
  };
}

describe('SettingsLoopbackSection', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders transport selector and connect button when idle', () => {
    render(<SettingsLoopbackSection loopback={makeLoopback()} />);

    expect(screen.getByText('Serial')).toBeInTheDocument();
    expect(screen.getByText('Bluetooth')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Connect via Loopback' })).toBeInTheDocument();
  });

  it('shows baud rate input when serial is selected', () => {
    render(<SettingsLoopbackSection loopback={makeLoopback()} />);

    expect(screen.getByLabelText('Baud Rate')).toBeInTheDocument();
  });

  it('hides baud rate input when BLE is selected', () => {
    render(<SettingsLoopbackSection loopback={makeLoopback()} />);

    // Click BLE button
    fireEvent.click(screen.getByText('Bluetooth'));

    expect(screen.queryByLabelText('Baud Rate')).not.toBeInTheDocument();
  });

  it('calls connectSerial with baud rate on connect', () => {
    const connectSerial = vi.fn(async () => {});
    render(<SettingsLoopbackSection loopback={makeLoopback({ connectSerial })} />);

    fireEvent.click(screen.getByRole('button', { name: 'Connect via Loopback' }));

    expect(connectSerial).toHaveBeenCalledWith(115200);
  });

  it('calls connectBluetooth when BLE selected and connect clicked', () => {
    const connectBluetooth = vi.fn(async () => {});
    render(<SettingsLoopbackSection loopback={makeLoopback({ connectBluetooth })} />);

    fireEvent.click(screen.getByText('Bluetooth'));
    fireEvent.click(screen.getByRole('button', { name: 'Connect via Loopback' }));

    expect(connectBluetooth).toHaveBeenCalled();
  });

  it('shows connected state with disconnect button', () => {
    render(
      <SettingsLoopbackSection
        loopback={makeLoopback({ status: 'connected', transportType: 'serial' })}
      />
    );

    expect(screen.getByText(/Connected via Serial/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Disconnect Loopback' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Connect via Loopback' })).not.toBeInTheDocument();
  });

  it('calls disconnect on disconnect button click', () => {
    const disconnect = vi.fn();
    render(
      <SettingsLoopbackSection
        loopback={makeLoopback({ status: 'connected', transportType: 'serial', disconnect })}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: 'Disconnect Loopback' }));

    expect(disconnect).toHaveBeenCalled();
  });

  it('shows connecting state', () => {
    render(<SettingsLoopbackSection loopback={makeLoopback({ status: 'connecting' })} />);

    expect(screen.getByRole('button', { name: 'Connecting...' })).toBeDisabled();
  });

  it('shows error message', () => {
    render(
      <SettingsLoopbackSection loopback={makeLoopback({ status: 'error', error: 'Port failed' })} />
    );

    expect(screen.getByText('Port failed')).toBeInTheDocument();
  });

  it('shows warning when neither serial nor bluetooth available', () => {
    render(
      <SettingsLoopbackSection
        loopback={makeLoopback({ serialAvailable: false, bluetoothAvailable: false })}
      />
    );

    expect(screen.getByText(/does not support Web Serial or Web Bluetooth/)).toBeInTheDocument();
    // Connect button should not appear
    expect(screen.queryByRole('button', { name: 'Connect via Loopback' })).not.toBeInTheDocument();
  });

  it('disables serial button when serial not available', () => {
    render(<SettingsLoopbackSection loopback={makeLoopback({ serialAvailable: false })} />);

    expect(screen.getByText('Serial')).toBeDisabled();
    expect(screen.getByText(/Web Serial not available/)).toBeInTheDocument();
  });

  it('disables bluetooth button when bluetooth not available', () => {
    render(<SettingsLoopbackSection loopback={makeLoopback({ bluetoothAvailable: false })} />);

    expect(screen.getByText('Bluetooth')).toBeDisabled();
    expect(screen.getByText(/Web Bluetooth not available/)).toBeInTheDocument();
  });

  it('defaults to BLE when serial is not available', () => {
    render(<SettingsLoopbackSection loopback={makeLoopback({ serialAvailable: false })} />);

    // BLE should be selected, so baud rate should NOT be visible
    expect(screen.queryByLabelText('Baud Rate')).not.toBeInTheDocument();
  });
});
