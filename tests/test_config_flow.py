"""Teste pentru config flow: user, duplicat, reauth, options."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.etoll_cnair.api import (
    EtollAuthError,
    EtollConnectionError,
)
from custom_components.etoll_cnair.const import DOMAIN

from .conftest import PASSWORD, USERNAME

USER_INPUT = {"username": USERNAME, "password": PASSWORD}


@pytest.fixture(autouse=True)
def _no_real_setup():
    """Fluxurile de configurare nu trebuie să încarce integrarea."""
    with patch("custom_components.etoll_cnair.async_setup_entry", return_value=True):
        yield


async def test_user_flow_success(
    hass: HomeAssistant, mock_api: SimpleNamespace
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"username": f"  {USERNAME}  ", "password": PASSWORD}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "CNAIR eToll 2026"
    assert result["data"] == USER_INPUT  # spațiile din email sunt eliminate
    assert result["result"].unique_id == USERNAME
    mock_api.login.assert_awaited_once()


@pytest.mark.parametrize(
    ("exc", "error"),
    [
        (EtollAuthError("bad"), "invalid_auth"),
        (EtollConnectionError("down"), "cannot_connect"),
    ],
)
async def test_user_flow_errors_then_recovers(
    hass: HomeAssistant, mock_api: SimpleNamespace, exc: Exception, error: str
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    mock_api.login.side_effect = exc
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    mock_api.login.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_duplicate_aborts(
    hass: HomeAssistant,
    mock_api: SimpleNamespace,
    mock_config_entry: MockConfigEntry,
) -> None:
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    # unique_id e emailul cu litere mici: aceeași adresă scrisă altfel e duplicat
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"username": USERNAME.upper(), "password": PASSWORD},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    mock_api.login.assert_not_awaited()


async def test_reauth_success(
    hass: HomeAssistant,
    mock_api: SimpleNamespace,
    mock_config_entry: MockConfigEntry,
) -> None:
    mock_config_entry.add_to_hass(hass)

    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"password": "new-test-password"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data["password"] == "new-test-password"
    assert mock_config_entry.data["username"] == USERNAME


async def test_reauth_invalid_auth_keeps_form(
    hass: HomeAssistant,
    mock_api: SimpleNamespace,
    mock_config_entry: MockConfigEntry,
) -> None:
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reauth_flow(hass)

    mock_api.login.side_effect = EtollAuthError("bad")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"password": "wrong-test-password"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert mock_config_entry.data["password"] == PASSWORD  # neschimbată


@pytest.mark.parametrize("value", [14, 1441, 0])
async def test_options_flow_rejects_out_of_range(
    hass: HomeAssistant,
    mock_api: SimpleNamespace,
    mock_config_entry: MockConfigEntry,
    value: int,
) -> None:
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)

    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {"scan_interval": value}
        )
