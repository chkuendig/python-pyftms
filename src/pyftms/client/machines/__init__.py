# Copyright 2024, Sergey Dudanov
# SPDX-License-Identifier: Apache-2.0

from bleak.backends.device import BLEDevice

from ..client import FitnessMachine
from ..properties import MachineType
from .cross_trainer import CrossTrainer
from .indoor_bike import IndoorBike
from .rower import Rower
from .treadmill import Treadmill
from .treadmill_sole import TreadmillSole, is_sole_treadmill


def get_machine(mt: MachineType, ble_device: BLEDevice | None = None) -> type[FitnessMachine]:
    """
    Returns Fitness Machine class by type.
    
    If a BLEDevice is provided, may return a device-specific subclass
    (e.g., TreadmillSole for Sole treadmills).
    """
    assert len(mt) == 1

    match mt:
        case MachineType.TREADMILL:
            # Check for Sole treadmill by device name
            if ble_device and is_sole_treadmill(ble_device.name):
                return TreadmillSole
            return Treadmill

        case MachineType.CROSS_TRAINER:
            return CrossTrainer

        case MachineType.ROWER:
            return Rower

        case MachineType.INDOOR_BIKE:
            return IndoorBike

    raise NotImplementedError("This Fitness Machine type is not supported.")


__all__ = [
    "CrossTrainer",
    "IndoorBike",
    "Rower",
    "Treadmill",
    "TreadmillSole",
    "get_machine",
    "is_sole_treadmill",
]
