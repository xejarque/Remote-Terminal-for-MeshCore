import {
  useState,
  useCallback,
  useImperativeHandle,
  forwardRef,
  useRef,
  useMemo,
  type FormEvent,
  type KeyboardEvent,
} from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Send, Lock } from 'lucide-react';
import { toast } from './ui/sonner';
import { cn } from '@/lib/utils';

// MeshCore message size limits (empirically determined from LoRa packet constraints)
const DM_HARD_LIMIT = 156;
const DM_WARNING_THRESHOLD = 140;
const CHANNEL_HARD_LIMIT = 156;
const CHANNEL_WARNING_THRESHOLD = 120;
const CHANNEL_DANGER_BUFFER = 8;

const textEncoder = new TextEncoder();
function byteLen(s: string): number {
  return textEncoder.encode(s).length;
}

interface MessageInputProps {
  onSend: (text: string) => Promise<void>;
  disabled: boolean;
  placeholder?: string;
  isRepeaterMode?: boolean;
  conversationType?: 'contact' | 'channel' | 'raw';
  senderName?: string;
}

type LimitState = 'normal' | 'warning' | 'danger' | 'error';

export interface MessageInputHandle {
  appendText: (text: string) => void;
}

export const MessageInput = forwardRef<MessageInputHandle, MessageInputProps>(function MessageInput(
  { onSend, disabled, placeholder, isRepeaterMode, conversationType, senderName },
  ref
) {
  const [text, setText] = useState('');
  const [sending, setSending] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useImperativeHandle(ref, () => ({
    appendText: (appendedText: string) => {
      setText((prev) => prev + appendedText);
      inputRef.current?.focus();
    },
  }));

  const limits = useMemo(() => {
    if (conversationType === 'contact') {
      return {
        warningAt: DM_WARNING_THRESHOLD,
        dangerAt: DM_HARD_LIMIT,
        hardLimit: DM_HARD_LIMIT,
      };
    } else if (conversationType === 'channel') {
      const nameByteLen = senderName ? byteLen(senderName) : 10;
      const hardLimit = Math.max(1, CHANNEL_HARD_LIMIT - nameByteLen - 2);
      return {
        warningAt: CHANNEL_WARNING_THRESHOLD,
        dangerAt: Math.max(1, hardLimit - CHANNEL_DANGER_BUFFER),
        hardLimit,
      };
    }
    return null;
  }, [conversationType, senderName]);

  const textByteLen = useMemo(() => byteLen(text), [text]);

  const { limitState, warningMessage } = useMemo((): {
    limitState: LimitState;
    warningMessage: string | null;
  } => {
    if (!limits) return { limitState: 'normal', warningMessage: null };

    if (textByteLen >= limits.hardLimit) {
      return { limitState: 'error', warningMessage: 'likely truncated' };
    }
    if (textByteLen >= limits.dangerAt) {
      return { limitState: 'danger', warningMessage: 'multi-hop risk' };
    }
    if (textByteLen >= limits.warningAt) {
      return { limitState: 'warning', warningMessage: 'multi-hop risk' };
    }
    return { limitState: 'normal', warningMessage: null };
  }, [textByteLen, limits]);

  const remaining = limits ? limits.hardLimit - textByteLen : 0;

  const handleSubmit = useCallback(
    async (e: FormEvent) => {
      e.preventDefault();
      const trimmed = text.trim();

      if (isRepeaterMode) {
        if (sending || disabled) return;
        setSending(true);
        try {
          await onSend(trimmed);
          setText('');
        } catch (err) {
          console.error('Failed to request telemetry:', err);
          toast.error('Failed to request telemetry', {
            description: err instanceof Error ? err.message : 'Check radio connection',
          });
          return;
        } finally {
          setSending(false);
        }
        setTimeout(() => inputRef.current?.focus(), 0);
      } else {
        if (!trimmed || sending || disabled) return;
        setSending(true);
        try {
          await onSend(trimmed);
          setText('');
        } catch (err) {
          console.error('Failed to send message:', err);
          toast.error('Failed to send message', {
            description: err instanceof Error ? err.message : 'Check radio connection',
          });
          return;
        } finally {
          setSending(false);
        }
        setTimeout(() => inputRef.current?.focus(), 0);
      }
    },
    [text, sending, disabled, onSend, isRepeaterMode]
  );

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLInputElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSubmit(e as unknown as FormEvent);
      }
    },
    [handleSubmit]
  );

  const canSubmit = isRepeaterMode ? true : text.trim().length > 0;
  const showCharCounter = !isRepeaterMode && limits !== null && textByteLen > 0;

  return (
    <div className="px-4 py-3 border-t border-border/50">
      <form onSubmit={handleSubmit} className="flex flex-col gap-1.5">
        <div className="flex items-center gap-2">
          {/* Input container with glow */}
          <div
            className={cn(
              'flex-1 relative rounded-xl border transition-all duration-200',
              disabled
                ? 'bg-muted/30 border-border/30'
                : text.length > 0
                  ? 'bg-secondary/40 border-primary/25 shadow-glow-amber-sm'
                  : 'bg-secondary/30 border-border/50 focus-within:border-primary/30 focus-within:shadow-glow-amber-sm'
            )}
          >
            {isRepeaterMode && (
              <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground/40" />
            )}
            <input
              ref={inputRef}
              type={isRepeaterMode ? 'password' : 'text'}
              autoComplete={isRepeaterMode ? 'off' : undefined}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={
                placeholder ||
                (isRepeaterMode ? 'Enter password for admin login...' : 'Type a message...')
              }
              disabled={disabled || sending}
              className={cn(
                'w-full h-10 bg-transparent rounded-xl text-sm placeholder:text-muted-foreground/40 focus:outline-none disabled:cursor-not-allowed disabled:opacity-40',
                isRepeaterMode ? 'pl-9 pr-3' : 'px-4'
              )}
            />
          </div>

          {/* Send button */}
          <motion.button
            type="submit"
            disabled={disabled || sending || !canSubmit}
            whileTap={{ scale: 0.92 }}
            className={cn(
              'h-10 rounded-xl flex items-center justify-center gap-2 font-medium text-sm transition-all duration-200 disabled:opacity-30 disabled:cursor-not-allowed flex-shrink-0',
              isRepeaterMode
                ? 'px-4 bg-accent/15 text-accent border border-accent/25 hover:bg-accent/25'
                : canSubmit && !disabled
                  ? 'px-4 bg-primary text-primary-foreground shadow-glow-amber-sm hover:shadow-glow-amber active:shadow-none'
                  : 'px-4 bg-secondary text-muted-foreground'
            )}
          >
            {sending ? (
              <div className="w-4 h-4 border-2 border-current/30 border-t-current rounded-full animate-spin" />
            ) : isRepeaterMode ? (
              <>
                <Lock className="h-4 w-4" />
                <span className="hidden sm:inline">{text.trim() ? 'Login' : 'Guest'}</span>
              </>
            ) : (
              <>
                <Send className="h-4 w-4" />
                <span className="hidden sm:inline">Send</span>
              </>
            )}
          </motion.button>
        </div>

        {/* Character counter */}
        <AnimatePresence>
          {showCharCounter && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="flex items-center justify-end gap-2 text-xs overflow-hidden"
            >
              <span
                className={cn(
                  'tabular-nums font-mono text-[11px]',
                  limitState === 'error' || limitState === 'danger'
                    ? 'text-red-400 font-medium'
                    : limitState === 'warning'
                      ? 'text-amber-400'
                      : 'text-muted-foreground/50'
                )}
              >
                {textByteLen}/{limits!.hardLimit}b{remaining < 0 && ` (${remaining})`}
              </span>
              {warningMessage && (
                <span
                  className={cn(
                    'text-[11px]',
                    limitState === 'error' ? 'text-red-400' : 'text-amber-400/70'
                  )}
                >
                  {warningMessage}
                </span>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </form>
    </div>
  );
});
