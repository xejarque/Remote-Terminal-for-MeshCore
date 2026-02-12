import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Menu, Radio, Settings, MessageSquare, Wifi, WifiOff } from 'lucide-react';
import type { HealthStatus, RadioConfig } from '../types';
import { api } from '../api';
import { toast } from './ui/sonner';

interface StatusBarProps {
  health: HealthStatus | null;
  config: RadioConfig | null;
  settingsMode?: boolean;
  onSettingsClick: () => void;
  onMenuClick?: () => void;
}

export function StatusBar({
  health,
  config,
  settingsMode = false,
  onSettingsClick,
  onMenuClick,
}: StatusBarProps) {
  const connected = health?.radio_connected ?? false;
  const [reconnecting, setReconnecting] = useState(false);

  const handleReconnect = async () => {
    setReconnecting(true);
    try {
      const result = await api.reconnectRadio();
      if (result.connected) {
        toast.success('Reconnected', { description: result.message });
      }
    } catch (err) {
      toast.error('Reconnection failed', {
        description: err instanceof Error ? err.message : 'Check radio connection and power',
      });
    } finally {
      setReconnecting(false);
    }
  };

  return (
    <div className="relative flex items-center gap-3 px-4 py-2.5 border-b border-border/50 bg-card/80 backdrop-blur-sm">
      {/* Subtle gradient overlay */}
      <div className="absolute inset-0 bg-gradient-to-r from-primary/[0.03] via-transparent to-accent/[0.03] pointer-events-none" />

      {/* Mobile menu button */}
      {onMenuClick && (
        <button
          onClick={onMenuClick}
          className="md:hidden p-1.5 rounded-lg bg-transparent text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
          aria-label="Open menu"
        >
          <Menu className="h-5 w-5" />
        </button>
      )}

      {/* Logo / Title */}
      <div className="flex items-center gap-2 mr-auto">
        <div className="relative">
          <Radio className="h-5 w-5 text-primary" />
          {connected && (
            <motion.div
              className="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full bg-emerald-400"
              animate={{ scale: [1, 1.3, 1] }}
              transition={{ duration: 2, repeat: Infinity, ease: 'easeInOut' }}
            />
          )}
        </div>
        <h1 className="text-base font-bold tracking-tight text-gradient-amber">RemoteTerm</h1>
      </div>

      {/* Connection status */}
      <div className="flex items-center gap-2">
        <AnimatePresence mode="wait">
          {connected ? (
            <motion.div
              key="connected"
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.8 }}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/20"
            >
              <Wifi className="h-3.5 w-3.5 text-emerald-400" />
              <span className="hidden lg:inline text-xs font-medium text-emerald-400">
                Connected
              </span>
            </motion.div>
          ) : (
            <motion.div
              key="disconnected"
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.8 }}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-destructive/10 border border-destructive/20"
            >
              <WifiOff className="h-3.5 w-3.5 text-destructive/70" />
              <span className="hidden lg:inline text-xs font-medium text-destructive/70">
                Offline
              </span>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Radio info */}
      {config && (
        <div className="hidden lg:flex items-center gap-2">
          <span className="text-xs font-medium text-foreground/80">{config.name || 'Unnamed'}</span>
          <span
            className="font-mono text-[11px] text-muted-foreground cursor-pointer hover:text-primary transition-colors"
            onClick={() => {
              navigator.clipboard.writeText(config.public_key);
              toast.success('Public key copied!');
            }}
            title="Click to copy public key"
          >
            {config.public_key.toLowerCase().slice(0, 16)}...
          </span>
        </div>
      )}

      {/* Action buttons */}
      <div className="flex items-center gap-1.5">
        {!connected && (
          <motion.button
            initial={{ opacity: 0, x: 10 }}
            animate={{ opacity: 1, x: 0 }}
            onClick={handleReconnect}
            disabled={reconnecting}
            className="px-3 py-1.5 text-xs font-medium rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-400 hover:bg-amber-500/20 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {reconnecting ? 'Reconnecting...' : 'Reconnect'}
          </motion.button>
        )}
        <button
          onClick={onSettingsClick}
          className={`p-2 rounded-lg transition-all ${
            settingsMode
              ? 'bg-primary/15 text-primary border border-primary/30'
              : 'text-muted-foreground hover:text-foreground hover:bg-secondary'
          }`}
          title={settingsMode ? 'Back to Chat' : 'Settings'}
        >
          {settingsMode ? <MessageSquare className="h-4 w-4" /> : <Settings className="h-4 w-4" />}
        </button>
      </div>
    </div>
  );
}
