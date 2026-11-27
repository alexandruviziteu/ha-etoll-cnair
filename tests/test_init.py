"""Teste pentru setup/unload, reauth la eșec de autentificare și options reload."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.etoll_cnair.api import (
    EtollAuthError,
    EtollConnectionError,
    EtollHttpError,
)

from .conftest import setup_entry


async def test_setup_and_unload(
    hass: HomeAssistant,
    mock_api: SimpleNamespace,
    mock_config_entry: MockConfigEntry,
) -> None:
    await setup_entry(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert mock_config_entry.runtime_data is not None

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED


@pytest.mark.parametrize(
    "exc", [EtollConnectionError("down"), EtollHttpError(500), EtollHttpError(403)]
)
async def test_setup_retry_on_transient_error(
    hass: HomeAssistant,
    mock_api: SimpleNamespace,
    mock_config_entry: MockConfigEntry,
    exc: Exception,
) -> None:
    """Erorile non-auth (inclusiv 403) => SETUP_RETRY, fără reauth."""
    mock_api.get_tolls.side_effect = exc

    await setup_entry(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
    assert not list(mock_config_entry.async_get_active_flows(hass, {"reauth"}))


async def test_setup_auth_failure_starts_reauth(
    hass: HomeAssistant,
    mock_api: SimpleNamespace,
    mock_config_entry: MockConfigEntry,
) -> None:
    mock_api.get_tolls.side_effect = EtollAuthError("401")

    await setup_entry(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = list(mock_config_entry.async_get_active_flows(hass, {"reauth"}))
    assert len(flows) == 1
    assert flows[0]["context"]["source"] == config_entries.SOURCE_REAUTH


async def test_options_change_reloads_exactly_once(
    hass: HomeAssistant,
    mock_api: SimpleNamespace,
    mock_config_entry: MockConfigEntry,
) -> None:
    await setup_entry(hass, mock_config_entry)
    assert mock_api.get_tolls.await_count == 1

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"scan_interval": 30}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options == {"scan_interval": 30}
    # un singur reload => încă un get_tolls (2 în total, nu 3)
    assert mock_api.get_tolls.await_count == 2
    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert mock_config_entry.runtime_data.update_interval == timedelta(minutes=30)
