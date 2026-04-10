import asyncio
import logging
from collections import OrderedDict

from app.config import settings

logger = logging.getLogger(__name__)


class RadioOperationError(RuntimeError):
    """Base class for shared radio operation lock errors."""


class RadioOperationBusyError(RadioOperationError):
    """Raised when a non-blocking radio operation cannot acquire the lock."""


class RadioDisconnectedError(RadioOperationError):
    """Raised when the radio disconnects between pre-check and lock acquisition."""


class RadioRuntimeState:
    """Mutable runtime state for one live radio session manager."""

    def __init__(self) -> None:
        self.connection_info: str | None = None
        self.connection_desired: bool = True
        self.reconnect_task: asyncio.Task | None = None
        self.last_connected: bool = False
        self.reconnect_lock: asyncio.Lock | None = None
        self.operation_lock: asyncio.Lock | None = None
        self.setup_lock: asyncio.Lock | None = None
        self.setup_in_progress: bool = False
        self.setup_complete: bool = False
        self.frontend_reconnect_error_broadcasts: int = 0
        self.device_info_loaded: bool = False
        self.max_contacts: int | None = None
        self.device_model: str | None = None
        self.firmware_build: str | None = None
        self.firmware_version: str | None = None
        self.max_channels: int = 40
        self.path_hash_mode: int = 0
        self.path_hash_mode_supported: bool = False
        self.channel_slot_by_key: OrderedDict[str, int] = OrderedDict()
        self.channel_key_by_slot: dict[int, str] = {}
        self.pending_message_channel_key_by_slot: dict[int, str] = {}

    @property
    def is_reconnecting(self) -> bool:
        return self.reconnect_lock is not None and self.reconnect_lock.locked()

    async def acquire_operation_lock(self, name: str, *, blocking: bool) -> None:
        if self.operation_lock is None:
            self.operation_lock = asyncio.Lock()

        if not blocking:
            if self.operation_lock.locked():
                raise RadioOperationBusyError(f"Radio is busy (operation: {name})")
            # No coroutine can acquire the lock between the check above and
            # this await because we have not yielded yet.
            await self.operation_lock.acquire()
        else:
            await self.operation_lock.acquire()

        logger.debug("Acquired radio operation lock (%s)", name)

    def release_operation_lock(self, name: str) -> None:
        if self.operation_lock and self.operation_lock.locked():
            self.operation_lock.release()
            logger.debug("Released radio operation lock (%s)", name)
        else:
            logger.error("Attempted to release unlocked radio operation lock (%s)", name)

    def reset_connected_runtime_state(self) -> None:
        self.setup_complete = False
        self.device_info_loaded = False
        self.max_contacts = None
        self.device_model = None
        self.firmware_build = None
        self.firmware_version = None
        self.max_channels = 40
        self.path_hash_mode = 0
        self.path_hash_mode_supported = False
        self.reset_channel_send_cache()
        self.clear_pending_message_channel_slots()

    def reset_channel_send_cache(self) -> None:
        self.channel_slot_by_key.clear()
        self.channel_key_by_slot.clear()

    def remember_pending_message_channel_slot(self, channel_key: str, slot: int) -> None:
        self.pending_message_channel_key_by_slot[slot] = channel_key.upper()

    def get_pending_message_channel_key(self, slot: int) -> str | None:
        return self.pending_message_channel_key_by_slot.get(slot)

    def clear_pending_message_channel_slots(self) -> None:
        self.pending_message_channel_key_by_slot.clear()

    def channel_slot_reuse_enabled(self) -> bool:
        if settings.force_channel_slot_reconfigure:
            return False
        if self.connection_info:
            return not self.connection_info.startswith("TCP:")
        return settings.connection_type != "tcp"

    def get_channel_send_cache_capacity(self) -> int:
        try:
            return max(1, int(self.max_channels))
        except (TypeError, ValueError):
            return 1

    def get_cached_channel_slot(self, channel_key: str) -> int | None:
        return self.channel_slot_by_key.get(channel_key.upper())

    def plan_channel_send_slot(
        self,
        channel_key: str,
        *,
        preferred_slot: int = 0,
    ) -> tuple[int, bool, str | None]:
        if not self.channel_slot_reuse_enabled():
            return preferred_slot, True, None

        normalized_key = channel_key.upper()
        cached_slot = self.channel_slot_by_key.get(normalized_key)
        if cached_slot is not None:
            return cached_slot, False, None

        capacity = self.get_channel_send_cache_capacity()
        if len(self.channel_slot_by_key) < capacity:
            slot = self._find_first_free_channel_slot(capacity, preferred_slot)
            return slot, True, None

        evicted_key, slot = next(iter(self.channel_slot_by_key.items()))
        return slot, True, evicted_key

    def note_channel_slot_loaded(self, channel_key: str, slot: int) -> None:
        if not self.channel_slot_reuse_enabled():
            return

        normalized_key = channel_key.upper()
        previous_slot = self.channel_slot_by_key.pop(normalized_key, None)
        if previous_slot is not None and previous_slot != slot:
            self.channel_key_by_slot.pop(previous_slot, None)

        displaced_key = self.channel_key_by_slot.get(slot)
        if displaced_key is not None and displaced_key != normalized_key:
            self.channel_slot_by_key.pop(displaced_key, None)

        self.channel_key_by_slot[slot] = normalized_key
        self.channel_slot_by_key[normalized_key] = slot

    def note_channel_slot_used(self, channel_key: str) -> None:
        if not self.channel_slot_reuse_enabled():
            return

        normalized_key = channel_key.upper()
        slot = self.channel_slot_by_key.get(normalized_key)
        if slot is None:
            return
        self.channel_slot_by_key.move_to_end(normalized_key)
        self.channel_key_by_slot[slot] = normalized_key

    def invalidate_cached_channel_slot(self, channel_key: str) -> None:
        normalized_key = channel_key.upper()
        slot = self.channel_slot_by_key.pop(normalized_key, None)
        if slot is None:
            return
        if self.channel_key_by_slot.get(slot) == normalized_key:
            self.channel_key_by_slot.pop(slot, None)

    def get_channel_send_cache_snapshot(self) -> list[tuple[str, int]]:
        return list(self.channel_slot_by_key.items())

    def reset_reconnect_error_broadcasts(self) -> None:
        self.frontend_reconnect_error_broadcasts = 0

    def _find_first_free_channel_slot(self, capacity: int, preferred_slot: int) -> int:
        if preferred_slot < capacity and preferred_slot not in self.channel_key_by_slot:
            return preferred_slot

        for slot in range(capacity):
            if slot not in self.channel_key_by_slot:
                return slot

        return preferred_slot
