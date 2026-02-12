import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Radio,
  Map,
  Sparkles,
  KeyRound,
  CheckCheck,
  Search,
  X,
  Star,
  Hash,
  User,
} from 'lucide-react';
import {
  CONTACT_TYPE_REPEATER,
  type Contact,
  type Channel,
  type Conversation,
  type Favorite,
} from '../types';
import { getStateKey, type ConversationTimes } from '../utils/conversationState';
import { getContactDisplayName } from '../utils/pubkey';
import { ContactAvatar } from './ContactAvatar';
import { isFavorite } from '../utils/favorites';
import { cn } from '@/lib/utils';

type SortOrder = 'alpha' | 'recent';

interface SidebarProps {
  contacts: Contact[];
  channels: Channel[];
  activeConversation: Conversation | null;
  onSelectConversation: (conversation: Conversation) => void;
  onNewMessage: () => void;
  lastMessageTimes: ConversationTimes;
  unreadCounts: Record<string, number>;
  mentions: Record<string, boolean>;
  showCracker: boolean;
  crackerRunning: boolean;
  onToggleCracker: () => void;
  onMarkAllRead: () => void;
  favorites: Favorite[];
  sortOrder?: SortOrder;
  onSortOrderChange?: (order: SortOrder) => void;
}

export function Sidebar({
  contacts,
  channels,
  activeConversation,
  onSelectConversation,
  onNewMessage,
  lastMessageTimes,
  unreadCounts,
  mentions,
  showCracker,
  crackerRunning,
  onToggleCracker,
  onMarkAllRead,
  favorites,
  sortOrder: sortOrderProp = 'recent',
  onSortOrderChange,
}: SidebarProps) {
  const sortOrder = sortOrderProp;
  const [searchQuery, setSearchQuery] = useState('');

  const handleSortToggle = () => {
    const newOrder = sortOrder === 'alpha' ? 'recent' : 'alpha';
    onSortOrderChange?.(newOrder);
  };

  const handleSelectConversation = (conversation: Conversation) => {
    setSearchQuery('');
    onSelectConversation(conversation);
  };

  const isActive = (type: 'contact' | 'channel' | 'raw' | 'map' | 'visualizer', id: string) =>
    activeConversation?.type === type && activeConversation?.id === id;

  const getUnreadCount = (type: 'channel' | 'contact', id: string): number => {
    const key = getStateKey(type, id);
    return unreadCounts[key] || 0;
  };

  const hasMention = (type: 'channel' | 'contact', id: string): boolean => {
    const key = getStateKey(type, id);
    return mentions[key] || false;
  };

  const getLastMessageTime = (type: 'channel' | 'contact', id: string) => {
    const key = getStateKey(type, id);
    return lastMessageTimes[key] || 0;
  };

  // Deduplicate channels by name
  const uniqueChannels = channels.reduce<Channel[]>((acc, channel) => {
    if (!acc.some((c) => c.name === channel.name)) {
      acc.push(channel);
    }
    return acc;
  }, []);

  // Deduplicate contacts by public key
  const uniqueContacts = contacts
    .filter((c) => c.public_key && c.public_key.length > 0)
    .sort((a, b) => {
      if (a.name && !b.name) return -1;
      if (!a.name && b.name) return 1;
      return (a.name || '').localeCompare(b.name || '');
    })
    .reduce<Contact[]>((acc, contact) => {
      if (!acc.some((c) => c.public_key === contact.public_key)) {
        acc.push(contact);
      }
      return acc;
    }, []);

  // Sort channels
  const sortedChannels = [...uniqueChannels].sort((a, b) => {
    if (a.name === 'Public') return -1;
    if (b.name === 'Public') return 1;
    if (sortOrder === 'recent') {
      const timeA = getLastMessageTime('channel', a.key);
      const timeB = getLastMessageTime('channel', b.key);
      if (timeA && timeB) return timeB - timeA;
      if (timeA && !timeB) return -1;
      if (!timeA && timeB) return 1;
    }
    return a.name.localeCompare(b.name);
  });

  // Sort contacts
  const sortedContacts = [...uniqueContacts].sort((a, b) => {
    const aIsRepeater = a.type === CONTACT_TYPE_REPEATER;
    const bIsRepeater = b.type === CONTACT_TYPE_REPEATER;
    if (aIsRepeater && !bIsRepeater) return 1;
    if (!aIsRepeater && bIsRepeater) return -1;
    if (aIsRepeater && bIsRepeater) {
      return (a.name || a.public_key).localeCompare(b.name || b.public_key);
    }
    if (sortOrder === 'recent') {
      const timeA = getLastMessageTime('contact', a.public_key);
      const timeB = getLastMessageTime('contact', b.public_key);
      if (timeA && timeB) return timeB - timeA;
      if (timeA && !timeB) return -1;
      if (!timeA && timeB) return 1;
    }
    return (a.name || a.public_key).localeCompare(b.name || b.public_key);
  });

  // Filter by search
  const query = searchQuery.toLowerCase().trim();
  const filteredChannels = query
    ? sortedChannels.filter(
        (c) => c.name.toLowerCase().includes(query) || c.key.toLowerCase().includes(query)
      )
    : sortedChannels;
  const filteredContacts = query
    ? sortedContacts.filter(
        (c) => c.name?.toLowerCase().includes(query) || c.public_key.toLowerCase().includes(query)
      )
    : sortedContacts;

  // Separate favorites
  const favoriteChannels = filteredChannels.filter((c) => isFavorite(favorites, 'channel', c.key));
  const favoriteContacts = filteredContacts.filter((c) =>
    isFavorite(favorites, 'contact', c.public_key)
  );
  const nonFavoriteChannels = filteredChannels.filter(
    (c) => !isFavorite(favorites, 'channel', c.key)
  );
  const nonFavoriteContacts = filteredContacts.filter(
    (c) => !isFavorite(favorites, 'contact', c.public_key)
  );

  type FavoriteItem = { type: 'channel'; channel: Channel } | { type: 'contact'; contact: Contact };

  const favoriteItems: FavoriteItem[] = [
    ...favoriteChannels.map((channel) => ({ type: 'channel' as const, channel })),
    ...favoriteContacts.map((contact) => ({ type: 'contact' as const, contact })),
  ].sort((a, b) => {
    const timeA =
      a.type === 'channel'
        ? getLastMessageTime('channel', a.channel.key)
        : getLastMessageTime('contact', a.contact.public_key);
    const timeB =
      b.type === 'channel'
        ? getLastMessageTime('channel', b.channel.key)
        : getLastMessageTime('contact', b.contact.public_key);
    if (timeA && timeB) return timeB - timeA;
    if (timeA && !timeB) return -1;
    if (!timeA && timeB) return 1;
    const nameA = a.type === 'channel' ? a.channel.name : a.contact.name || a.contact.public_key;
    const nameB = b.type === 'channel' ? b.channel.name : b.contact.name || b.contact.public_key;
    return nameA.localeCompare(nameB);
  });

  // Unread badge component
  const UnreadBadge = ({ count, isMentionBadge }: { count: number; isMentionBadge: boolean }) => (
    <motion.span
      initial={{ scale: 0 }}
      animate={{ scale: 1 }}
      className={cn(
        'text-[10px] font-bold px-1.5 py-0.5 rounded-full min-w-[18px] text-center leading-none',
        isMentionBadge
          ? 'bg-destructive text-destructive-foreground shadow-[0_0_8px_hsl(0_72%_51%/0.4)]'
          : 'bg-primary text-primary-foreground shadow-glow-amber-sm'
      )}
    >
      {count}
    </motion.span>
  );

  // Conversation item component
  const ConversationItem = ({
    active,
    unreadCount,
    isMentionItem,
    onClick,
    icon,
    children,
  }: {
    active: boolean;
    unreadCount?: number;
    isMentionItem?: boolean;
    onClick: () => void;
    icon?: React.ReactNode;
    children: React.ReactNode;
  }) => (
    <div
      className={cn(
        'group px-3 py-2 cursor-pointer flex items-center gap-2.5 rounded-lg mx-1.5 my-0.5 transition-all duration-150',
        active
          ? 'bg-primary/10 border border-primary/20 shadow-glow-amber-sm'
          : 'border border-transparent hover:bg-secondary/60',
        (unreadCount ?? 0) > 0 && !active && 'bg-secondary/30'
      )}
      onClick={onClick}
    >
      {icon}
      <span
        className={cn(
          'flex-1 truncate text-sm transition-colors',
          active ? 'text-foreground font-medium' : 'text-foreground/70 group-hover:text-foreground',
          (unreadCount ?? 0) > 0 && 'text-foreground font-semibold'
        )}
      >
        {children}
      </span>
      {(unreadCount ?? 0) > 0 && (
        <UnreadBadge count={unreadCount!} isMentionBadge={isMentionItem ?? false} />
      )}
    </div>
  );

  return (
    <div className="sidebar w-64 h-full min-h-0 bg-card/50 backdrop-blur-sm border-r border-border/50 flex flex-col">
      {/* Header */}
      <div className="flex justify-between items-center px-4 py-3 border-b border-border/50">
        <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Conversations
        </span>
        <button
          onClick={onNewMessage}
          title="New Conversation"
          className="h-7 w-7 flex items-center justify-center rounded-lg bg-primary/10 text-primary hover:bg-primary/20 transition-all text-lg font-light"
        >
          +
        </button>
      </div>

      {/* Search */}
      <div className="px-3 py-2 border-b border-border/50">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground/50" />
          <input
            type="text"
            placeholder="Search..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full h-8 pl-8 pr-8 text-sm bg-secondary/40 border border-border/50 rounded-lg placeholder:text-muted-foreground/40 focus:outline-none focus:border-primary/30 focus:bg-secondary/60 transition-all"
          />
          <AnimatePresence>
            {searchQuery && (
              <motion.button
                initial={{ opacity: 0, scale: 0.5 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.5 }}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                onClick={() => setSearchQuery('')}
                title="Clear search"
              >
                <X className="h-3.5 w-3.5" />
              </motion.button>
            )}
          </AnimatePresence>
        </div>
      </div>

      {/* Quick nav - special views */}
      {!query && (
        <div className="flex items-center gap-1 px-3 py-2 border-b border-border/50">
          {[
            {
              type: 'raw' as const,
              id: 'raw',
              name: 'Raw Packet Feed',
              icon: Radio,
              title: 'Packet Feed',
            },
            { type: 'map' as const, id: 'map', name: 'Node Map', icon: Map, title: 'Node Map' },
            {
              type: 'visualizer' as const,
              id: 'visualizer',
              name: 'Mesh Visualizer',
              icon: Sparkles,
              title: 'Visualizer',
            },
          ].map((view) => (
            <button
              key={view.id}
              className={cn(
                'flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg text-xs transition-all',
                isActive(view.type, view.id)
                  ? 'bg-primary/15 text-primary border border-primary/20'
                  : 'text-muted-foreground hover:text-foreground hover:bg-secondary/50'
              )}
              onClick={() =>
                handleSelectConversation({
                  type: view.type,
                  id: view.id,
                  name: view.name,
                })
              }
              title={view.title}
            >
              <view.icon className="h-3.5 w-3.5" />
              <span className="hidden xl:inline">{view.title.split(' ')[0]}</span>
            </button>
          ))}
        </div>
      )}

      {/* Cracker + Mark all read */}
      {!query && (
        <div className="flex items-center gap-1 px-3 py-1.5 border-b border-border/50">
          <button
            className={cn(
              'flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg text-xs transition-all',
              showCracker
                ? 'bg-primary/15 text-primary border border-primary/20'
                : 'text-muted-foreground hover:text-foreground hover:bg-secondary/50'
            )}
            onClick={onToggleCracker}
            title="Room Finder"
          >
            <KeyRound className="h-3.5 w-3.5" />
            <span className="truncate">
              Finder
              {crackerRunning && (
                <span className="ml-1 inline-block w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              )}
            </span>
          </button>
          {Object.keys(unreadCounts).length > 0 && (
            <button
              className="flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg text-xs text-muted-foreground hover:text-foreground hover:bg-secondary/50 transition-all"
              onClick={onMarkAllRead}
              title="Mark all as read"
            >
              <CheckCheck className="h-3.5 w-3.5" />
              <span className="truncate">Read all</span>
            </button>
          )}
        </div>
      )}

      {/* Conversation list */}
      <div className="flex-1 overflow-y-auto py-1">
        {/* Favorites */}
        {favoriteItems.length > 0 && (
          <>
            <div className="flex items-center gap-1.5 px-4 py-2 pt-2.5">
              <Star className="h-3 w-3 text-amber-400/60" />
              <span className="text-[11px] uppercase tracking-wider font-medium text-amber-400/60">
                Favorites
              </span>
            </div>
            {favoriteItems.map((item) => {
              if (item.type === 'channel') {
                const channel = item.channel;
                const count = getUnreadCount('channel', channel.key);
                const mention = hasMention('channel', channel.key);
                return (
                  <ConversationItem
                    key={`fav-chan-${channel.key}`}
                    active={isActive('channel', channel.key)}
                    unreadCount={count}
                    isMentionItem={mention}
                    onClick={() =>
                      handleSelectConversation({
                        type: 'channel',
                        id: channel.key,
                        name: channel.name,
                      })
                    }
                    icon={<Hash className="h-4 w-4 text-muted-foreground/50 flex-shrink-0" />}
                  >
                    {channel.name}
                  </ConversationItem>
                );
              } else {
                const contact = item.contact;
                const count = getUnreadCount('contact', contact.public_key);
                const mention = hasMention('contact', contact.public_key);
                return (
                  <ConversationItem
                    key={`fav-contact-${contact.public_key}`}
                    active={isActive('contact', contact.public_key)}
                    unreadCount={count}
                    isMentionItem={mention}
                    onClick={() =>
                      handleSelectConversation({
                        type: 'contact',
                        id: contact.public_key,
                        name: getContactDisplayName(contact.name, contact.public_key),
                      })
                    }
                    icon={
                      <ContactAvatar
                        name={contact.name}
                        publicKey={contact.public_key}
                        size={22}
                        contactType={contact.type}
                      />
                    }
                  >
                    {getContactDisplayName(contact.name, contact.public_key)}
                  </ConversationItem>
                );
              }
            })}
          </>
        )}

        {/* Channels */}
        {nonFavoriteChannels.length > 0 && (
          <>
            <div className="flex justify-between items-center px-4 py-2 pt-3">
              <div className="flex items-center gap-1.5">
                <Hash className="h-3 w-3 text-muted-foreground/40" />
                <span className="text-[11px] uppercase tracking-wider font-medium text-muted-foreground/60">
                  Channels
                </span>
              </div>
              <button
                className="text-[10px] px-1.5 py-0.5 rounded bg-secondary/50 text-muted-foreground hover:text-foreground hover:bg-secondary transition-all"
                onClick={handleSortToggle}
                title={sortOrder === 'alpha' ? 'Sort by recent' : 'Sort alphabetically'}
              >
                {sortOrder === 'alpha' ? 'A-Z' : 'Recent'}
              </button>
            </div>
            {nonFavoriteChannels.map((channel) => {
              const count = getUnreadCount('channel', channel.key);
              const mention = hasMention('channel', channel.key);
              return (
                <ConversationItem
                  key={`chan-${channel.key}`}
                  active={isActive('channel', channel.key)}
                  unreadCount={count}
                  isMentionItem={mention}
                  onClick={() =>
                    handleSelectConversation({
                      type: 'channel',
                      id: channel.key,
                      name: channel.name,
                    })
                  }
                  icon={<Hash className="h-4 w-4 text-muted-foreground/50 flex-shrink-0" />}
                >
                  {channel.name}
                </ConversationItem>
              );
            })}
          </>
        )}

        {/* Contacts */}
        {nonFavoriteContacts.length > 0 && (
          <>
            <div className="flex justify-between items-center px-4 py-2 pt-3">
              <div className="flex items-center gap-1.5">
                <User className="h-3 w-3 text-muted-foreground/40" />
                <span className="text-[11px] uppercase tracking-wider font-medium text-muted-foreground/60">
                  Contacts
                </span>
              </div>
              {nonFavoriteChannels.length === 0 && (
                <button
                  className="text-[10px] px-1.5 py-0.5 rounded bg-secondary/50 text-muted-foreground hover:text-foreground hover:bg-secondary transition-all"
                  onClick={handleSortToggle}
                  title={sortOrder === 'alpha' ? 'Sort by recent' : 'Sort alphabetically'}
                >
                  {sortOrder === 'alpha' ? 'A-Z' : 'Recent'}
                </button>
              )}
            </div>
            {nonFavoriteContacts.map((contact) => {
              const count = getUnreadCount('contact', contact.public_key);
              const mention = hasMention('contact', contact.public_key);
              return (
                <ConversationItem
                  key={contact.public_key}
                  active={isActive('contact', contact.public_key)}
                  unreadCount={count}
                  isMentionItem={mention}
                  onClick={() =>
                    handleSelectConversation({
                      type: 'contact',
                      id: contact.public_key,
                      name: getContactDisplayName(contact.name, contact.public_key),
                    })
                  }
                  icon={
                    <ContactAvatar
                      name={contact.name}
                      publicKey={contact.public_key}
                      size={22}
                      contactType={contact.type}
                    />
                  }
                >
                  {getContactDisplayName(contact.name, contact.public_key)}
                </ConversationItem>
              );
            })}
          </>
        )}

        {/* Empty state */}
        {nonFavoriteContacts.length === 0 &&
          nonFavoriteChannels.length === 0 &&
          favoriteItems.length === 0 && (
            <div className="p-6 text-center text-muted-foreground/50 text-sm">
              {query ? 'No matches found' : 'No conversations yet'}
            </div>
          )}
      </div>
    </div>
  );
}
