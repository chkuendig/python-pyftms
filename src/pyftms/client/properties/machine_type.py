# Copyright 2024-2025, Sergey Dudanov
# SPDX-License-Identifier: Apache-2.0

import functools
import operator
from enum import Flag, auto

from bleak.backends.scanner import AdvertisementData
from bleak.uuids import normalize_uuid_str

from ..const import FTMS_UUID
from ..errors import NotFitnessMachineError


class MachineFlags(Flag):
    """
    Fitness Machine Flags.

    Included in the `Service Data AD Type`.

    Described in section `3.1.1: Flags Field`.
    """

    FITNESS_MACHINE = auto()
    """Fitness Machine Available"""


class MachineType(Flag):
    """
    Fitness Machine Type.

    Included in the Advertisement Service Data.

    Described in section **3.1.2: Fitness Machine Type Field**.
    """

    TREADMILL = auto()
    """Treadmill Machine."""
    CROSS_TRAINER = auto()
    """Cross Trainer Machine."""
    STEP_CLIMBER = auto()
    """Step Climber Machine."""
    STAIR_CLIMBER = auto()
    """Stair Climber Machine."""
    ROWER = auto()
    """Rower Machine."""
    INDOOR_BIKE = auto()
    """Indoor Bike Machine."""


# Known Sole treadmill model identifiers (may appear anywhere in device name)
SOLE_TREADMILL_MODELS = ("F65", "F63", "F80", "F85", "TT8", "ST90")


def _is_sole_treadmill(device_name: str | None) -> bool:
    """Check if device is a known Sole treadmill by model in name."""
    if not device_name:
        return False
    name_upper = device_name.upper()
    # Device name may be "F65", "MCHP F65 (00)", etc.
    return any(model in name_upper for model in SOLE_TREADMILL_MODELS)


def get_machine_type_from_service_data(
    adv_data: AdvertisementData,
) -> MachineType:
    """Returns fitness machine type from Bluetooth advertisement data.

    Parameters:
        adv_data: Bluetooth [advertisement data](https://bleak.readthedocs.io/en/latest/backends/index.html#bleak.backends.scanner.AdvertisementData).

    Returns:
        Fitness machine type.
    """

    data = adv_data.service_data.get(normalize_uuid_str(FTMS_UUID))

    if data is None or not (2 <= len(data) <= 3):
        # Auto-detect Sole treadmills by name - they advertise FTMS UUID
        # but don't include proper service_data
        if _is_sole_treadmill(adv_data.local_name):
            ftms_normalized = normalize_uuid_str(FTMS_UUID)
            if any(normalize_uuid_str(uuid) == ftms_normalized for uuid in adv_data.service_uuids):
                return MachineType.TREADMILL
        raise NotFitnessMachineError(data)

    # Reading mandatory `Flags` and `Machine Type`.
    # `Machine Type` bytes may be reversed on some machines or be a just one
    # byte (it's bug), so I logically ORed them.
    try:
        mt = functools.reduce(operator.or_, data[1:])
        mf, mt = MachineFlags(data[0]), MachineType(mt)

    except ValueError:
        raise NotFitnessMachineError(data)

    if mf and mt:
        return mt

    raise NotFitnessMachineError(data)
