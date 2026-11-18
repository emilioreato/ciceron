"""Windows power status shared by the center and the native browser host."""
import ctypes
from ctypes import wintypes
import os


class PowerStatus(ctypes.Structure):
    _fields_ = [('ac', wintypes.BYTE), ('flags', wintypes.BYTE), ('percentage', wintypes.BYTE),
                ('saving', wintypes.BYTE), ('seconds', wintypes.DWORD), ('total_seconds', wintypes.DWORD)]


get_power = None
if os.name == 'nt':
    get_power = ctypes.windll.kernel32.GetSystemPowerStatus
    get_power.argtypes = [ctypes.POINTER(PowerStatus)]
    get_power.restype = wintypes.BOOL


def low_power():
    status = PowerStatus()
    return bool(get_power and get_power(ctypes.byref(status)) and (
        status.saving == 1 or (status.ac == 0 and status.percentage <= 20)))
