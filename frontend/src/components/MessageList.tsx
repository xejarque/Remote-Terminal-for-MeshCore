import {
  useEffect,
  useLayoutEffect,
  useRef,
  useCallback,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ChevronDown } from 'lucide-react';
import type { Contact, Message, MessagePath, RadioConfig } from '../types';
import { CONTACT_TYPE_REPEATER } from '../types';
import { formatTime, parseSenderFromText } from '../utils/messageParser';
import { formatHopCounts, type SenderInfo } from '../utils/pathUtils';
import { ContactAvatar } from './ContactAvatar';
import { PathModal } from './PathModal';
import { cn } from '@/lib/utils';

interface MessageListProps {
  messages: Message[];
  contacts: Contact[];
  loading: boolean;
  loadingOlder?: boolean;
  hasOlderMessages?: boolean;
  onSenderClick?: (sender: string) => void;
  onLoadOlder?: () => void;
  radioName?: string;
  config?: RadioConfig | null;
}

// URL regex for linkifying plain text
const URL_PATTERN =
  /https?:\/\/(www\.)?[-a-zA-Z0-9@:%._+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_+.~#?&//=]*)/g;

// Helper to convert URLs in a plain text string into clickable links
function linkifyText(text: string, keyPrefix: string): ReactNode[] {
  const parts: ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let keyIndex = 0;

  URL_PATTERN.lastIndex = 0;
  while ((match = URL_PATTERN.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    parts.push(
      <a
        key={`${keyPrefix}-link-${keyIndex++}`}
        href={match[0]}
        target="_blank"
        rel="noopener noreferrer"
        className="text-accent underline decoration-accent/40 hover:decoration-accent hover:text-accent/80 transition-colors"
      >
        {match[0]}
      </a>
    );
    lastIndex = match.index + match[0].length;
  }

  if (lastIndex === 0) return [text];
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }
  return parts;
}

// Helper to render text with highlighted @[Name] mentions and clickable URLs
function renderTextWithMentions(text: string, radioName?: string): ReactNode {
  const mentionPattern = /@\[([^\]]+)\]/g;
  const parts: ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let keyIndex = 0;

  while ((match = mentionPattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(...linkifyText(text.slice(lastIndex, match.index), `pre-${keyIndex}`));
    }

    const mentionedName = match[1];
    const isOwnMention = radioName ? mentionedName === radioName : false;

    parts.push(
      <span
        key={`mention-${keyIndex++}`}
        className={cn(
          'rounded-md px-1 py-0.5 text-[13px]',
          isOwnMention
            ? 'bg-primary/20 text-primary font-semibold ring-1 ring-primary/30'
            : 'bg-accent/10 text-accent/80'
        )}
      >
        @{mentionedName}
      </span>
    );

    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < text.length) {
    parts.push(...linkifyText(text.slice(lastIndex), `post-${keyIndex}`));
  }

  return parts.length > 0 ? parts : text;
}

// Clickable hop count badge
interface HopCountBadgeProps {
  paths: MessagePath[];
  onClick: () => void;
  variant: 'header' | 'inline';
}

function HopCountBadge({ paths, onClick, variant }: HopCountBadgeProps) {
  const hopInfo = formatHopCounts(paths);
  const label = hopInfo.display;

  return (
    <span
      className={cn(
        'cursor-pointer transition-colors',
        variant === 'header'
          ? 'ml-1.5 text-[10px] px-1.5 py-0.5 rounded-full bg-accent/10 text-accent/60 hover:text-accent hover:bg-accent/15'
          : 'ml-1.5 text-[10px] px-1.5 py-0.5 rounded-full bg-muted text-muted-foreground/50 hover:text-accent hover:bg-accent/10'
      )}
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      title="View message path"
    >
      {label}
    </span>
  );
}

export function MessageList({
  messages,
  contacts,
  loading,
  loadingOlder = false,
  hasOlderMessages = false,
  onSenderClick,
  onLoadOlder,
  radioName,
  config,
}: MessageListProps) {
  const listRef = useRef<HTMLDivElement>(null);
  const prevMessagesLengthRef = useRef<number>(0);
  const isInitialLoadRef = useRef<boolean>(true);
  const [showScrollToBottom, setShowScrollToBottom] = useState(false);
  const [selectedPath, setSelectedPath] = useState<{
    paths: MessagePath[];
    senderInfo: SenderInfo;
  } | null>(null);

  const scrollStateRef = useRef({
    scrollTop: 0,
    scrollHeight: 0,
    clientHeight: 0,
    wasNearTop: false,
    wasNearBottom: true,
  });

  const prevConvKeyRef = useRef<string | null>(null);

  useLayoutEffect(() => {
    if (!listRef.current) return;

    const list = listRef.current;
    const messagesAdded = messages.length - prevMessagesLengthRef.current;

    const convKey = messages.length > 0 ? messages[0].conversation_key : null;
    const conversationChanged = convKey !== null && convKey !== prevConvKeyRef.current;
    if (convKey !== null) prevConvKeyRef.current = convKey;

    if ((isInitialLoadRef.current || conversationChanged) && messages.length > 0) {
      list.scrollTop = list.scrollHeight;
      isInitialLoadRef.current = false;
    } else if (messagesAdded > 0 && prevMessagesLengthRef.current > 0) {
      const scrollHeightDiff = list.scrollHeight - scrollStateRef.current.scrollHeight;

      if (scrollStateRef.current.wasNearTop && scrollHeightDiff > 0) {
        list.scrollTop = scrollStateRef.current.scrollTop + scrollHeightDiff;
      } else if (scrollStateRef.current.wasNearBottom) {
        list.scrollTop = list.scrollHeight;
      }
    }

    prevMessagesLengthRef.current = messages.length;
  }, [messages]);

  useEffect(() => {
    if (messages.length === 0) {
      isInitialLoadRef.current = true;
      prevMessagesLengthRef.current = 0;
      prevConvKeyRef.current = null;
      scrollStateRef.current = {
        scrollTop: 0,
        scrollHeight: 0,
        clientHeight: 0,
        wasNearTop: false,
        wasNearBottom: true,
      };
    }
  }, [messages.length]);

  const handleScroll = useCallback(() => {
    if (!listRef.current) return;

    const { scrollTop, scrollHeight, clientHeight } = listRef.current;
    const distanceFromBottom = scrollHeight - scrollTop - clientHeight;

    scrollStateRef.current = {
      scrollTop,
      scrollHeight,
      clientHeight,
      wasNearTop: scrollTop < 150,
      wasNearBottom: distanceFromBottom < 100,
    };

    setShowScrollToBottom(distanceFromBottom > 100);

    if (!onLoadOlder || loadingOlder || !hasOlderMessages) return;

    if (scrollTop < 100) {
      onLoadOlder();
    }
  }, [onLoadOlder, loadingOlder, hasOlderMessages]);

  const scrollToBottom = useCallback(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, []);

  const sortedMessages = useMemo(
    () => [...messages].sort((a, b) => a.received_at - b.received_at),
    [messages]
  );

  const getContact = (conversationKey: string | null): Contact | null => {
    if (!conversationKey) return null;
    return contacts.find((c) => c.public_key === conversationKey) || null;
  };

  const getContactByName = (name: string): Contact | null => {
    return contacts.find((c) => c.name === name) || null;
  };

  const getSenderInfo = (
    msg: Message,
    contact: Contact | null,
    parsedSender: string | null
  ): SenderInfo => {
    if (msg.type === 'PRIV' && contact) {
      return {
        name: contact.name || contact.public_key.slice(0, 12),
        publicKeyOrPrefix: contact.public_key,
        lat: contact.lat,
        lon: contact.lon,
      };
    }
    if (parsedSender) {
      const senderContact = getContactByName(parsedSender);
      if (senderContact) {
        return {
          name: parsedSender,
          publicKeyOrPrefix: senderContact.public_key,
          lat: senderContact.lat,
          lon: senderContact.lon,
        };
      }
    }
    return {
      name: parsedSender || 'Unknown',
      publicKeyOrPrefix: msg.conversation_key || '',
      lat: null,
      lon: null,
    };
  };

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
          <span className="text-sm text-muted-foreground">Loading messages...</span>
        </div>
      </div>
    );
  }

  if (messages.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center">
          <div className="text-3xl mb-2 opacity-20">💬</div>
          <span className="text-sm text-muted-foreground/60">No messages yet</span>
        </div>
      </div>
    );
  }

  const getSenderKey = (msg: Message, sender: string | null): string => {
    if (msg.outgoing) return '__outgoing__';
    if (msg.type === 'PRIV' && msg.conversation_key) return msg.conversation_key;
    return sender || '__unknown__';
  };

  return (
    <div className="flex-1 overflow-hidden relative">
      <div
        className="h-full overflow-y-auto px-4 py-3 flex flex-col gap-0.5"
        ref={listRef}
        onScroll={handleScroll}
      >
        {loadingOlder && (
          <div className="flex justify-center py-3">
            <div className="w-5 h-5 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
          </div>
        )}
        {!loadingOlder && hasOlderMessages && (
          <div className="text-center py-2 text-muted-foreground/40 text-xs">
            Scroll up for older messages
          </div>
        )}
        {sortedMessages.map((msg, index) => {
          const contact = msg.type === 'PRIV' ? getContact(msg.conversation_key) : null;
          const isRepeater = contact?.type === CONTACT_TYPE_REPEATER;

          const { sender, content } = isRepeater
            ? { sender: null, content: msg.text }
            : parseSenderFromText(msg.text);
          const displaySender = msg.outgoing
            ? 'You'
            : contact?.name || sender || msg.conversation_key?.slice(0, 8) || 'Unknown';

          const canClickSender = !msg.outgoing && onSenderClick && displaySender !== 'Unknown';

          const currentSenderKey = getSenderKey(msg, sender);
          const prevMsg = sortedMessages[index - 1];
          const prevSenderKey = prevMsg
            ? getSenderKey(prevMsg, parseSenderFromText(prevMsg.text).sender)
            : null;
          const showAvatar = !msg.outgoing && currentSenderKey !== prevSenderKey;
          const isFirstMessage = index === 0;

          let avatarName: string | null = null;
          let avatarKey: string = '';
          if (!msg.outgoing) {
            if (msg.type === 'PRIV' && msg.conversation_key) {
              avatarName = contact?.name || null;
              avatarKey = msg.conversation_key;
            } else if (sender) {
              const senderContact = getContactByName(sender);
              avatarName = sender;
              avatarKey = senderContact?.public_key || `name:${sender}`;
            }
          }

          return (
            <div
              key={msg.id}
              className={cn(
                'flex items-start max-w-[85%]',
                msg.outgoing && 'flex-row-reverse self-end',
                showAvatar && !isFirstMessage && 'mt-4'
              )}
            >
              {!msg.outgoing && (
                <div className="w-9 flex-shrink-0 flex items-start pt-0.5">
                  {showAvatar && avatarKey && (
                    <ContactAvatar name={avatarName} publicKey={avatarKey} size={30} />
                  )}
                </div>
              )}
              <div
                className={cn(
                  'py-2 px-3 rounded-2xl min-w-0 relative',
                  msg.outgoing
                    ? 'bg-gradient-to-br from-primary/20 to-primary/10 border border-primary/15'
                    : 'bg-secondary/60 border border-border/30'
                )}
              >
                {showAvatar && (
                  <div className="flex items-center gap-1.5 mb-1">
                    <span className="text-[13px] font-semibold">
                      {canClickSender ? (
                        <span
                          className="cursor-pointer hover:text-primary transition-colors"
                          onClick={() => onSenderClick(displaySender)}
                          title={`Mention ${displaySender}`}
                        >
                          {displaySender}
                        </span>
                      ) : (
                        <span className="text-muted-foreground">{displaySender}</span>
                      )}
                    </span>
                    <span className="text-[10px] text-muted-foreground/40">
                      {formatTime(msg.sender_timestamp || msg.received_at)}
                    </span>
                    {!msg.outgoing && msg.paths && msg.paths.length > 0 && (
                      <HopCountBadge
                        paths={msg.paths}
                        variant="header"
                        onClick={() =>
                          setSelectedPath({
                            paths: msg.paths!,
                            senderInfo: getSenderInfo(msg, contact, sender),
                          })
                        }
                      />
                    )}
                  </div>
                )}
                <div className="break-words whitespace-pre-wrap text-[14px] leading-relaxed">
                  {content.split('\n').map((line, i, arr) => (
                    <span key={i}>
                      {renderTextWithMentions(line, radioName)}
                      {i < arr.length - 1 && <br />}
                    </span>
                  ))}
                  {!showAvatar && (
                    <>
                      <span className="text-[10px] text-muted-foreground/30 ml-2">
                        {formatTime(msg.sender_timestamp || msg.received_at)}
                      </span>
                      {!msg.outgoing && msg.paths && msg.paths.length > 0 && (
                        <HopCountBadge
                          paths={msg.paths}
                          variant="inline"
                          onClick={() =>
                            setSelectedPath({
                              paths: msg.paths!,
                              senderInfo: getSenderInfo(msg, contact, sender),
                            })
                          }
                        />
                      )}
                    </>
                  )}
                  {msg.outgoing &&
                    (msg.acked > 0 ? (
                      msg.paths && msg.paths.length > 0 ? (
                        <span
                          className="ml-1.5 text-[11px] text-emerald-400/70 cursor-pointer hover:text-emerald-400 transition-colors"
                          onClick={(e) => {
                            e.stopPropagation();
                            setSelectedPath({
                              paths: msg.paths!,
                              senderInfo: {
                                name: config?.name || 'Unknown',
                                publicKeyOrPrefix: config?.public_key || '',
                                lat: config?.lat ?? null,
                                lon: config?.lon ?? null,
                              },
                            });
                          }}
                          title="View echo paths"
                        >
                          {` ✓${msg.acked > 1 ? msg.acked : ''}`}
                        </span>
                      ) : (
                        <span className="ml-1.5 text-[11px] text-emerald-400/70">
                          {` ✓${msg.acked > 1 ? msg.acked : ''}`}
                        </span>
                      )
                    ) : (
                      <span
                        className="ml-1.5 text-[11px] text-muted-foreground/30"
                        title="No repeats heard yet"
                      >
                        {' '}
                        ?
                      </span>
                    ))}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Scroll to bottom button */}
      <AnimatePresence>
        {showScrollToBottom && (
          <motion.button
            initial={{ opacity: 0, y: 10, scale: 0.9 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 10, scale: 0.9 }}
            onClick={scrollToBottom}
            className="absolute bottom-4 right-4 w-10 h-10 rounded-full bg-card border border-border/50 flex items-center justify-center shadow-lg hover:bg-secondary transition-all hover:border-primary/30"
            title="Scroll to bottom"
          >
            <ChevronDown className="h-5 w-5 text-muted-foreground" />
          </motion.button>
        )}
      </AnimatePresence>

      {/* Path modal */}
      {selectedPath && (
        <PathModal
          open={true}
          onClose={() => setSelectedPath(null)}
          paths={selectedPath.paths}
          senderInfo={selectedPath.senderInfo}
          contacts={contacts}
          config={config ?? null}
        />
      )}
    </div>
  );
}
