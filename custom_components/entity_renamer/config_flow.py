"""Config flow for Entity ID Renamer.

There is nothing to configure -- the flow exists only so the integration can be
added from the UI (and so HACS can offer it as a normal integration).
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN, PANEL_TITLE


class EntityRenamerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Single-step, single-instance setup."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is None:
            return self.async_show_form(step_id="user")

        return self.async_create_entry(title=PANEL_TITLE, data={})
