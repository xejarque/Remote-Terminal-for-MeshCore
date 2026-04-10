"""Shared access seam over the process-global radio runtime.

The runtime object is the public boundary for application code. It exposes the
current manager plus its mutable session state through an explicit API instead
of forwarding arbitrary attribute access to the manager instance.
"""

from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import HTTPException

import app.radio as radio_module


class RadioRuntime:
    """Explicit access seam over the process-global RadioManager."""

    def __init__(self, manager_or_getter=None):
        if manager_or_getter is None:
            self._manager_getter: Callable[[], Any] = lambda: radio_module.radio_manager
        elif callable(manager_or_getter):
            self._manager_getter = manager_or_getter
        else:
            self._manager_getter = lambda: manager_or_getter

    @property
    def manager(self) -> Any:
        return self._manager_getter()

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(
            f"{type(self).__name__!s} does not expose attribute {name!r}. "
            "Use an explicit RadioRuntime property or method."
        )

    @property
    def state(self) -> Any:
        return self.manager.state

    @property
    def meshcore(self) -> Any:
        return self.manager.meshcore

    @property
    def connection_info(self) -> str | None:
        return self.manager.connection_info

    @property
    def is_connected(self) -> bool:
        return self.manager.is_connected

    @property
    def is_reconnecting(self) -> bool:
        return self.manager.is_reconnecting

    @property
    def is_setup_in_progress(self) -> bool:
        return self.manager.is_setup_in_progress

    @property
    def is_setup_complete(self) -> bool:
        return self.manager.is_setup_complete

    @property
    def connection_desired(self) -> bool:
        return self.manager.connection_desired

    @property
    def max_contacts(self) -> int | None:
        return self.state.max_contacts

    @max_contacts.setter
    def max_contacts(self, value: int | None) -> None:
        self.state.max_contacts = value

    @property
    def max_channels(self) -> int:
        return self.state.max_channels

    @max_channels.setter
    def max_channels(self, value: int) -> None:
        self.state.max_channels = value

    @property
    def path_hash_mode(self) -> int:
        return self.state.path_hash_mode

    @path_hash_mode.setter
    def path_hash_mode(self, value: int) -> None:
        self.state.path_hash_mode = value

    @property
    def path_hash_mode_supported(self) -> bool:
        return self.state.path_hash_mode_supported

    @path_hash_mode_supported.setter
    def path_hash_mode_supported(self, value: bool) -> None:
        self.state.path_hash_mode_supported = value

    @property
    def device_info_loaded(self) -> bool:
        return self.state.device_info_loaded

    @property
    def device_model(self) -> str | None:
        return self.state.device_model

    @property
    def firmware_build(self) -> str | None:
        return self.state.firmware_build

    @property
    def firmware_version(self) -> str | None:
        return self.state.firmware_version

    def require_connected(self):
        """Return MeshCore when available, mirroring existing HTTP semantics."""
        if self.is_setup_in_progress:
            raise HTTPException(status_code=503, detail="Radio is initializing")
        if not self.is_connected:
            raise HTTPException(status_code=503, detail="Radio not connected")
        mc = self.meshcore
        if mc is None:
            raise HTTPException(status_code=503, detail="Radio not connected")
        return mc

    @asynccontextmanager
    async def radio_operation(self, name: str, **kwargs):
        async with self.manager.radio_operation(name, **kwargs) as mc:
            yield mc

    async def start_connection_monitor(self) -> None:
        await self.manager.start_connection_monitor()

    async def stop_connection_monitor(self) -> None:
        await self.manager.stop_connection_monitor()

    async def disconnect(self) -> None:
        await self.manager.disconnect()

    async def prepare_connected(self, *, broadcast_on_success: bool = True) -> bool:
        from app.services.radio_lifecycle import prepare_connected_radio

        return await prepare_connected_radio(
            self.manager, broadcast_on_success=broadcast_on_success
        )

    async def reconnect_and_prepare(self, *, broadcast_on_success: bool = True) -> bool:
        from app.services.radio_lifecycle import reconnect_and_prepare_radio

        return await reconnect_and_prepare_radio(
            self.manager,
            broadcast_on_success=broadcast_on_success,
        )

    def reset_channel_send_cache(self) -> None:
        self.state.reset_channel_send_cache()

    def remember_pending_message_channel_slot(self, channel_key: str, slot: int) -> None:
        self.state.remember_pending_message_channel_slot(channel_key, slot)

    def get_pending_message_channel_key(self, slot: int) -> str | None:
        return self.state.get_pending_message_channel_key(slot)

    def clear_pending_message_channel_slots(self) -> None:
        self.state.clear_pending_message_channel_slots()

    def channel_slot_reuse_enabled(self) -> bool:
        return self.state.channel_slot_reuse_enabled()

    def get_channel_send_cache_capacity(self) -> int:
        return self.state.get_channel_send_cache_capacity()

    def get_cached_channel_slot(self, channel_key: str) -> int | None:
        return self.state.get_cached_channel_slot(channel_key)

    def plan_channel_send_slot(
        self,
        channel_key: str,
        *,
        preferred_slot: int = 0,
    ) -> tuple[int, bool, str | None]:
        return self.state.plan_channel_send_slot(channel_key, preferred_slot=preferred_slot)

    def note_channel_slot_loaded(self, channel_key: str, slot: int) -> None:
        self.state.note_channel_slot_loaded(channel_key, slot)

    def note_channel_slot_used(self, channel_key: str) -> None:
        self.state.note_channel_slot_used(channel_key)

    def invalidate_cached_channel_slot(self, channel_key: str) -> None:
        self.state.invalidate_cached_channel_slot(channel_key)

    def get_channel_send_cache_snapshot(self) -> list[tuple[str, int]]:
        return self.state.get_channel_send_cache_snapshot()

    def resume_connection(self) -> None:
        self.manager.resume_connection()

    async def pause_connection(self) -> None:
        await self.manager.pause_connection()


radio_runtime = RadioRuntime()
