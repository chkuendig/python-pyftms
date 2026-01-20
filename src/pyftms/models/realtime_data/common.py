# Copyright 2024, Sergey Dudanov
# SPDX-License-Identifier: Apache-2.0
#
# PATCHED: Handle truncated data streams gracefully for non-compliant FTMS devices
# =================================================================================
#
# ISSUE: Sole treadmills (F65, F80, F63, etc.) advertise FTMS service and send
# Treadmill Data notifications, but the data packets are truncated - they don't
# contain all the fields indicated by the flags bitmask. The standard deserializer
# throws EOFError when trying to read beyond the end of the data.
#
# Additionally, some devices send extra trailing bytes that cause assertion failures.
#
# SOURCES/REFERENCES:
#   - GitHub PR: https://github.com/dudanov/python-pyftms/pull/49
#     "Some devices advertise FTMS but don't fully comply with the spec"
#
#   - qdomyos-zwift: src/solef80treadmill.cpp
#     Shows that Sole treadmills have quirky/partial FTMS implementations
#     https://github.com/cagnulein/qdomyos-zwift
#
#   - treadonme: Go library for Sole BLE treadmills
#     Documents Sole's hybrid FTMS + proprietary protocol approach
#     https://github.com/AJGherber/treadonme
#
# PATCH BEHAVIOR:
#   1. Catches EOFError when parsing fields, logs debug message, returns partial data
#   2. Removed assert for remaining bytes - logs extra data instead of crashing
#

import dataclasses as dc
import io
import logging
from typing import Any, cast, override

from ...serializer import BaseModel, get_serializer, model_meta

_LOGGER = logging.getLogger(__name__)


@dc.dataclass(frozen=True)
class RealtimeData(BaseModel):
    mask: dc.InitVar[int]

    @override
    @classmethod
    def _deserialize_asdict(cls, src: io.IOBase) -> dict[str, Any]:
        mask, kwargs = cast(int, get_serializer("u2").deserialize(src)), {}
        kwargs["mask"] = mask
        mask ^= 1

        for field, serializer in cls._iter_fields_serializers():
            if mask & 1:
                # PATCH: Catch EOFError for truncated data streams
                try:
                    kwargs[field.name] = serializer.deserialize(src)
                except EOFError:
                    _LOGGER.debug(
                        "Truncated data stream: missing field '%s'. "
                        "Device may not be fully FTMS compliant.",
                        field.name
                    )
                    break

            mask >>= 1

            if not mask:
                break

        # PATCH: Don't assert on remaining data - some devices send extra bytes
        remaining = src.read()
        if remaining:
            _LOGGER.debug("Extra bytes in data stream ignored: %s", remaining.hex())

        return kwargs

    @override
    @classmethod
    def _calc_size(cls) -> int:
        return super()._calc_size() + 2


@dc.dataclass(frozen=True)
class RealtimeSpeedData(RealtimeData):
    speed_instant: float | None = dc.field(
        default=None,
        metadata=model_meta(
            format="u2.01",
        ),
    )
    """Instantaneous Speed"""

    speed_average: float | None = dc.field(
        default=None,
        metadata=model_meta(
            format="u2.01",
            features_bit=0,
        ),
    )
    """Average Speed"""


@dc.dataclass(frozen=True)
class InclinationData(BaseModel):
    inclination: float | None = dc.field(
        default=None,
        metadata=model_meta(
            format="s2.1",
        ),
    )
    """Inclination"""

    ramp_angle: float | None = dc.field(
        default=None,
        metadata=model_meta(
            format="s2.1",
        ),
    )
    """Ramp Angle"""


@dc.dataclass(frozen=True)
class EnergyData(BaseModel):
    energy_total: int | None = dc.field(
        default=None,
        metadata=model_meta(
            format="u2",
        ),
    )
    """Total Energy"""

    energy_per_hour: int | None = dc.field(
        default=None,
        metadata=model_meta(
            format="u2",
        ),
    )
    """Per Hour Energy"""

    energy_per_minute: int | None = dc.field(
        default=None,
        metadata=model_meta(
            format="u1",
        ),
    )
    """Per Minute Energy"""
