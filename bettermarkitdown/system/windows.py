"""Windows: standard library only (ctypes and winreg), no WMI.

WMI's Win32_VideoController.AdapterRAM is a 32-bit number: it caps at 4 GB and
reported 128 MB for an Intel Arc chip that borrows 16 GB. DXGI, the layer games
use to pick a graphics card, reports dedicated and shared memory as 64-bit sizes
for every vendor.
"""

from __future__ import annotations

import ctypes
import winreg
from ctypes import wintypes

from . import GB, GPU, VENDORS, SystemProfile, is_integrated, merge_nvidia, nvidia_gpus


class _MemoryStatus(ctypes.Structure):
    _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


class _LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class _AdapterDesc1(ctypes.Structure):
    _fields_ = [("Description", ctypes.c_wchar * 128),
                ("VendorId", ctypes.c_uint), ("DeviceId", ctypes.c_uint),
                ("SubSysId", ctypes.c_uint), ("Revision", ctypes.c_uint),
                ("DedicatedVideoMemory", ctypes.c_size_t),
                ("DedicatedSystemMemory", ctypes.c_size_t),
                ("SharedSystemMemory", ctypes.c_size_t),
                ("AdapterLuid", _LUID), ("Flags", ctypes.c_uint)]


_IID_IDXGIFactory1 = _GUID(0x770AAE78, 0xF26F, 0x4DBA,
                           (ctypes.c_ubyte * 8)(0xA8, 0x29, 0x25, 0x3C, 0x83, 0xD1, 0xB3, 0x87))
_NOT_FOUND = 0x887A0002 - (1 << 32)       # DXGI_ERROR_NOT_FOUND as a signed HRESULT
_SOFTWARE_ADAPTER = 2                     # DXGI_ADAPTER_FLAG_SOFTWARE
# COM vtable slots: IUnknown::Release, IDXGIFactory1::EnumAdapters1, IDXGIAdapter1::GetDesc1
_RELEASE, _ENUM_ADAPTERS1, _GET_DESC1 = 2, 12, 10


def _method(obj, index, restype, *argtypes):
    vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtable[index])


def dxgi_gpus() -> list[GPU]:
    factory = ctypes.c_void_p()
    if ctypes.windll.dxgi.CreateDXGIFactory1(ctypes.byref(_IID_IDXGIFactory1),
                                             ctypes.byref(factory)) != 0:
        return []
    gpus = []
    try:
        enum = _method(factory, _ENUM_ADAPTERS1, ctypes.c_long, ctypes.c_uint,
                       ctypes.POINTER(ctypes.c_void_p))
        index = 0
        while True:
            adapter = ctypes.c_void_p()
            if enum(factory, index, ctypes.byref(adapter)) == _NOT_FOUND:
                break
            index += 1
            desc = _AdapterDesc1()
            _method(adapter, _GET_DESC1, ctypes.c_long,
                    ctypes.POINTER(_AdapterDesc1))(adapter, ctypes.byref(desc))
            _method(adapter, _RELEASE, ctypes.c_ulong)(adapter)
            if desc.Flags & _SOFTWARE_ADAPTER:
                continue                  # "Microsoft Basic Render Driver": not a GPU
            vendor = VENDORS.get(desc.VendorId, f"0x{desc.VendorId:04x}")
            dedicated = round(desc.DedicatedVideoMemory / GB, 2)
            name = desc.Description.strip()
            gpus.append(GPU(name=name, vendor=vendor, dedicated_gb=dedicated,
                            shared_gb=round(desc.SharedSystemMemory / GB, 2),
                            integrated=is_integrated(vendor, name, dedicated), source="DXGI"))
    finally:
        _method(factory, _RELEASE, ctypes.c_ulong)(factory)
    return gpus


def _ram(profile: SystemProfile) -> None:
    status = _MemoryStatus()
    status.dwLength = ctypes.sizeof(_MemoryStatus)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    profile.ram_available_gb = round(status.ullAvailPhys / GB, 1)
    # Installed memory, not what Windows has left after hardware reservations: a
    # "32 GB" laptop reports 31.5 GB usable, and the tiers are written in sold sizes.
    installed_kb = ctypes.c_ulonglong()
    if ctypes.windll.kernel32.GetPhysicallyInstalledSystemMemory(ctypes.byref(installed_kb)):
        profile.ram_gb = round(installed_kb.value * 1024 / GB, 1)
    else:
        profile.ram_gb = round(status.ullTotalPhys / GB, 1)


def _cpu_name() -> str:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
            return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
    except OSError:
        return ""


def fill(profile: SystemProfile) -> None:
    _ram(profile)
    profile.cpu = _cpu_name()
    try:
        gpus = dxgi_gpus()
    except Exception as exc:
        gpus = []
        profile.notes.append(f"Graphics details unavailable (DXGI: {exc})")
    profile.gpus = merge_nvidia(gpus, nvidia_gpus())
