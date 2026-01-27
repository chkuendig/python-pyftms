# Copyright 2024-2025, Sergey Dudanov
# SPDX-License-Identifier: Apache-2.0
#
# Treadmill implementation with Sole F65 special handling
#
# The Sole F65 treadmill requires a proprietary 0xe9 command to start
# FTMS data flow. Without this, it won't send any data even though it
# advertises the FTMS UUID.
#
# References:
# - Sole+ iOS app packet capture analysis
# - qdomyos-zwift: https://github.com/cagnulein/qdomyos-zwift

from __future__ import annotations

import logging
from functools import cached_property
from typing import ClassVar

from ...models import RealtimeData, TreadmillData
from ..client import FitnessMachine
from .. import const as c
from ..properties import MachineType

_LOGGER = logging.getLogger(__name__)


class Treadmill(FitnessMachine):
    """
    Treadmill.

    Specific class of `FitnessMachine`.
    """

    _machine_type: ClassVar[MachineType] = MachineType.TREADMILL

    _data_model: ClassVar[type[RealtimeData]] = TreadmillData

    _data_uuid: ClassVar[str] = c.TREADMILL_DATA_UUID

    # Sole F65 FTMS initialization command (non-standard opcode)
    _SOLE_FTMS_START_CMD: ClassVar[bytes] = bytes([0xe9])

    @cached_property
    def _is_sole_f65(self) -> bool:
        """Check if this is a Sole F65 treadmill (device name contains 'F65')."""
        if not self._device.name:
            return False
        # Device name may be "F65", "MCHP F65 (00)", etc.
        return "F65" in self._device.name.upper()

    @property
    def supported_settings(self) -> tuple[str, ...]:
        """
        Supported settings.

        Sole F65 does not support FTMS Control Point commands.
        """
        if self._is_sole_f65:
            return ()
        # Standard FTMS behavior
        if not hasattr(self, "_m_settings"):
            return tuple()
        from ...models import ControlModel
        return tuple(ControlModel._get_features(self._m_settings))

    async def _connect(self) -> None:
        """
        Connect and initialize the treadmill.

        For Sole F65, sends the proprietary 0xe9 command to start
        FTMS data flow.
        """
        # Standard FTMS connection
        await super()._connect()

        if not self.is_connected:
            return

        # Sole F65 specific initialization
        if self._is_sole_f65:
            try:
                control_char = self._cli.services.get_characteristic(c.CONTROL_POINT_UUID)
                if control_char:
                    _LOGGER.debug("Sole F65: Sending FTMS initialization (0xe9)")
                    await self._cli.write_gatt_char(
                        control_char,
                        self._SOLE_FTMS_START_CMD,
                        response=False
                    )
                    _LOGGER.info("Sole F65: FTMS passive monitoring initialized")
                else:
                    _LOGGER.warning("Sole F65: FTMS Control Point not found")
            except Exception as e:
                _LOGGER.warning("Sole F65: FTMS initialization failed: %s", e)
