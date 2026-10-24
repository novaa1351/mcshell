"""The settings hub: which page a row belongs to, and who answers for it.

M6's promise is that a new setting is a daemon-side change. This is where that
promise is kept: the mod is handed rows of a few generic types and hands back a
key with a new value, so adding a setting means adding a row here, and adding a
whole page means writing one provider and registering it.

A provider owns one page. It needs:

    page                    "audio" | "video" | "controls" | "network"
    async items()           the rows, values included
    async set(key, value)   apply one; an error message, or None
    async start() / stop()  optional, for anything long-lived

Keys are namespaced by the page's own name — `audio.sink..volume` — so routing
a `setting_set` never needs a lookup table that could disagree with the schema
that produced the key.
"""

from __future__ import annotations

import asyncio
import logging

from . import protocol as p

log = logging.getLogger(__name__)


class Settings:
    def __init__(self) -> None:
        self._providers: dict[str, object] = {}

    def register(self, provider) -> None:
        self._providers[provider.page] = provider

    def pages(self) -> list[str]:
        return list(self._providers)

    async def start(self) -> None:
        for provider in self._providers.values():
            start = getattr(provider, "start", None)
            if start is None:
                continue
            try:
                await start()
            except Exception:
                # One page that cannot start is a page that draws empty, not a
                # daemon that fails to come up.
                log.exception("settings: %s failed to start", provider.page)

    async def stop(self) -> None:
        for provider in self._providers.values():
            stop = getattr(provider, "stop", None)
            if stop is None:
                continue
            try:
                await stop()
            except Exception:
                log.exception("settings: %s failed to stop", provider.page)

    async def schema(self, page: str | None = None) -> p.SettingsSchema:
        """Build one page, or every page when `page` is None."""
        if page:
            provider = self._providers.get(page)
            if provider is None:
                return p.SettingsSchema(items=[], page=page)
            return p.SettingsSchema(items=await self._items(provider), page=page)

        results = await asyncio.gather(
            *(self._items(provider) for provider in self._providers.values())
        )
        return p.SettingsSchema(items=[row for rows in results for row in rows], page="")

    async def _items(self, provider) -> list[p.SettingsSchemaItem]:
        try:
            return await provider.items()
        except Exception:
            # A page that throws should say so on the page, not take the socket
            # down with it — this runs inside a client's request.
            log.exception("settings: %s failed to build", provider.page)
            return [p.SettingsSchemaItem(
                key=f"{provider.page}.error..text", type="label", page=provider.page,
                label="This page could not be read; see the daemon log",
                enabled=False,
            )]

    async def set(self, key: str, value) -> str | None:
        """Apply one change. Returns an error message, or None on success."""
        if not isinstance(key, str) or "." not in key:
            return f"not a settings key: {key!r}"
        provider = self._providers.get(key.split(".", 1)[0])
        if provider is None:
            return f"no page owns {key!r}"
        try:
            return await provider.set(key, value)
        except Exception as e:
            log.exception("settings: %s failed to set %s", provider.page, key)
            return f"{key} could not be set: {e}"
