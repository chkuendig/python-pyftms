# Copyright 2024-2025, Sergey Dudanov & Christian Kündig
# SPDX-License-Identifier: Apache-2.0
#
# Sole Treadmill FTMS Support
#
# Sole treadmills (F65, F80, F63, TT8, etc.) advertise FTMS UUID but require
# a proprietary initialization command (0xe9) to start sending FTMS data.
# They don't support standard FTMS Control Point commands for control.
#
# This implementation provides PASSIVE MONITORING ONLY via standard FTMS.
# Control commands (start, stop, speed, incline) are NOT supported as they
# would require Sole's proprietary UART protocol which locks the console.
#
# References:
# - Sole+ iOS app packet capture analysis
# - qdomyos-zwift: https://github.com/cagnulein/qdomyos-zwift
#
# Tested on: Sole F65

from __future__ import annotations

import logging
from typing import ClassVar

from ..const import CONTROL_POINT_UUID
from ..properties import MachineType
from .treadmill import Treadmill

_LOGGER = logging.getLogger(__name__)


# Known Sole treadmill name prefixes
SOLE_TREADMILL_NAMES = ("F63", "F65", "F80", "F85", "F89", "S77", "TT8", "ST90", "TRX")


def is_sole_treadmill(device_name: str | None) -> bool:
    """Check if device name matches a known Sole treadmill."""
    if not device_name:
        return False
    name_upper = device_name.upper()
    return any(name_upper.startswith(prefix) for prefix in SOLE_TREADMILL_NAMES)


class TreadmillSole(Treadmill):
    """
    Sole Treadmill with FTMS-only passive monitoring.

    Sole treadmills require a proprietary 0xe9 command to the FTMS Control Point
    to start sending FTMS data. This command is non-standard (FTMS spec defines
    opcodes 0x00-0x13 and 0x80 only).

    IMPORTANT: This class provides PASSIVE MONITORING ONLY.
    Sole treadmills do NOT respond to standard FTMS Control Point commands
    (start, stop, speed, incline). They have a separate proprietary UART
    protocol for control, which is intentionally NOT implemented here to:
    1. Keep the implementation minimal for upstream acceptance
    2. Avoid locking the treadmill's physical console controls

    Supported features (via FTMS Treadmill Data):
    - Speed (instant)
    - Inclination
    - Distance (total)
    - Elapsed time
    - Expended energy (calories)
    - Heart rate (when sensor connected)
    """

    # Sole-specific FTMS initialization command (non-standard opcode)
    _SOLE_FTMS_START_CMD: ClassVar[bytes] = bytes([0xe9])

    @property
    def protocol_variant(self) -> str:
        """Return 'sole' to identify this as a Sole treadmill."""
        return "sole"

    @property
    def supported_settings(self) -> tuple[str, ...]:
        """
        Sole treadmills do not support FTMS Control Point commands.

        They ignore standard FTMS commands (start, stop, set_speed, etc.).
        Control would require the proprietary UART protocol.
        """
        return ()

    async def _connect(self) -> None:
        """Connect and send Sole-specific FTMS initialization command."""
        # Standard FTMS connection (subscribes to notifications, reads features)
        await super()._connect()

        if not self.is_connected:
            return

        # Send Sole-specific initialization command to start FTMS data flow.
        # Without this 0xe9 command, Sole treadmills won't send any data
        # even though they advertise FTMS UUID.
        #
        # This is based on packet capture analysis of the official Sole+ iOS app.
        try:
            control_char = self._cli.services.get_characteristic(CONTROL_POINT_UUID)
            if control_char:
                _LOGGER.debug("TreadmillSole: Sending FTMS initialization (0xe9)")
                await self._cli.write_gatt_char(
                    control_char,
                    self._SOLE_FTMS_START_CMD,
                    response=False  # Sole doesn't send indication for this
                )
                _LOGGER.info("TreadmillSole: FTMS passive monitoring initialized")
            else:
                _LOGGER.warning("TreadmillSole: FTMS Control Point not found")
        except Exception as e:
            # Don't fail connection if init command fails - device may still work
            _LOGGER.warning("TreadmillSole: FTMS initialization failed: %s", e)
