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


class _ProcessEntry(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]


_SNAP_PROCESSES = 2                       # TH32CS_SNAPPROCESS
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


def _memory_status() -> _MemoryStatus | None:
    status = _MemoryStatus()
    status.dwLength = ctypes.sizeof(_MemoryStatus)
    return status if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)) else None


def available_gb() -> float | None:
    """Memory usable right now without paging, or None if unreadable. Windows counts its
    standby cache as available: it hands that over at once."""
    status = _memory_status()
    return round(status.ullAvailPhys / GB, 1) if status else None


def pressure_critical() -> bool:
    return False              # the free memory is what is watched here


def ram_gb() -> float:
    # Installed memory, not what Windows has left after hardware reservations: a
    # "32 GB" laptop reports 31.5 GB usable, and the tiers are written in sold sizes.
    installed_kb = ctypes.c_ulonglong()
    if ctypes.windll.kernel32.GetPhysicallyInstalledSystemMemory(ctypes.byref(installed_kb)):
        return round(installed_kb.value * 1024 / GB, 1)
    status = _memory_status()
    return round(status.ullTotalPhys / GB, 1) if status else 0.0


def process_table() -> list[tuple[int, int, str]]:
    """Every process as (id, parent id, program name), or [] if it cannot be read."""
    kernel32 = ctypes.WinDLL("kernel32")   # its own copy: the signatures below stay here
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    for step in (kernel32.Process32FirstW, kernel32.Process32NextW):
        step.restype = wintypes.BOOL
        step.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    snapshot = kernel32.CreateToolhelp32Snapshot(_SNAP_PROCESSES, 0)
    if snapshot in (None, wintypes.HANDLE(-1).value):
        return []
    table = []
    try:
        entry = _ProcessEntry()
        entry.dwSize = ctypes.sizeof(_ProcessEntry)
        more = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            table.append((entry.th32ProcessID, entry.th32ParentProcessID, entry.szExeFile))
            more = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return table


def _cpu_name() -> str:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
            return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
    except OSError:
        return ""


def fill(profile: SystemProfile) -> None:
    profile.ram_gb = ram_gb()
    profile.ram_available_gb = available_gb() or 0.0
    profile.cpu = _cpu_name()
    try:
        gpus = dxgi_gpus()
    except Exception as exc:
        gpus = []
        profile.notes.append(f"Graphics details unavailable (DXGI: {exc})")
    profile.gpus = merge_nvidia(gpus, nvidia_gpus())
