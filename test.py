
import ctypes
import time

dll = ctypes.WinDLL(
    r"C:\Windows\System32\USBtoI2Cpro.dll",
    winmode=0
)

dll.GetNumberOfDevices.argtypes = []
dll.GetNumberOfDevices.restype = ctypes.c_int

dll.GetSerialNumbers.argtypes = [ctypes.POINTER(ctypes.c_int)]
dll.GetSerialNumbers.restype = ctypes.c_int

serials = (ctypes.c_int * 10)()

print("BEFORE:", dll.GetNumberOfDevices())

n = dll.GetSerialNumbers(serials)

print("SERIAL COUNT:", n)
print("SERIALS:", list(serials)[:max(n, 1)])

print("AFTER:", dll.GetNumberOfDevices())

n = dll.GetSerialNumbers(serials)
print("SERIAL COUNT:", n)
print("SERIALS:", list(serials)[:max(n, 1)])
