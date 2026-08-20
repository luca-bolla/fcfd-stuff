"""
Python interface to the USB-to-I2C Professional adapter, via its Windows DLL
(USBtoI2Cpro.dll), using ctypes. Replaces the earlier raw-serial USB-ISS
I2C_DIRECT implementation with calls into the manufacturer's own DLL, which
handles all START/RESTART/STOP sequencing and ACK checking internally.

Must be run on Windows, with USBtoI2Cpro.dll installed (it's placed in
Windows\\System32 by the USB-to-I2C Professional installer).

NOTE ON BITNESS: if WinDLL() fails to load, the DLL and your Python
interpreter probably don't match (32-bit DLL needs 32-bit Python, or vice
versa). Check which one the installer put on your system.
"""


# DLL manual: https://www.i2ctools.com/Downloads/USBtoI2Cpro/USB-to-I2C_Professional_DLL_Users_Manual.pdf?_ga=2.199680493.2144211942.1787064435-1263041868.1787064435


import ctypes
import time


dll = ctypes.WinDLL("USBtoI2Cpro.dll")


# Error handling from dll manual -----------------------------------------------


ERROR_CODES = {
    0x00: "No error",
    0x01: "Address not Acknowledged",
    0x02: "Data not Acknowledged",
    0x07: "Arbitration lost",
    0x08: "I2C Time Out",
    0x09: "I2C Time Out with no START condition (check bus / pull-ups)",
    0x0A: "Transmission aborted",
    0x0B: "Message sent but a Nack was encountered",
    0x80: "Unsupported function (check firmware version)",
    0xFF: "Hardware not detected or USB error",
}

def _describe_error(code: int) -> str:
    return ERROR_CODES.get(code, f"Unknown error code 0x{code:02X}")


# Functions from dll manual ----------------------------------------------------


# Returns the firmware version in BCD format: 0x12 = 1.2
dll.GetFirmwareRevision.argtypes = []
dll.GetFirmwareRevision.restype = ctypes.c_ubyte

# Returns the number of usb-to-i2c dongles enumerated on the pc
dll.GetNumberOfDevices.argtypes = []
dll.GetNumberOfDevices.restype = ctypes.c_int

# Sets the i2c clock freq to the paramater passed int, the real freq set by the fct is returned
# Max at 1000 kHz and min at 15.7 kHz, discrete values between
dll.SetI2CFrequency.argtypes = [ctypes.c_int]
dll.SetI2CFrequency.restype = ctypes.c_int

# No arguments and returns the i2c clock freq
dll.GetI2CFrequency.argtypes = []
dll.GetI2CFrequency.restype = ctypes.c_int

# uchar I2CReadArrayDB(uchar board_address, uchar subaaddress_High, uchar subaddress_Low, short int number of Bytes, uchar *ReadData)
# Number of bytes is capped at 256
dll.I2CReadArrayDB.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, ctypes.c_ubyte, ctypes.c_short, ctypes.POINTER(ctypes.c_ubyte)]
dll.I2CReadArrayDB.restype = ctypes.c_ubyte

# Same as i2creadarraydb()
# Number of bytes capped at 500
dll.I2CWriteArrayDB.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, ctypes.c_ubyte, ctypes.c_short, ctypes.POINTER(ctypes.c_ubyte)]
dll.I2CWriteArrayDB.restype = ctypes.c_ubyte

# Call whenever the application using the DLL is closed
dll.ShutdownProcedure.argtypes = []
dll.ShutdownProcedure.restype = None


# FCFD1.2 specific -------------------------------------------------------------


# Default values (table 4) from FCFD_manual.pdf
# Registers not present in the table are not defined in the dict
# Sergey said 0x25 is a better default for channels 0 and 1 because 'the signal level at the input of the chip is a little more natural than 5'
defaults = {0: 0x25, 1: 0x25, 3: 0x06, 4: 0x06, 5: 0x06, 6: 0x06, 8: 0x00, #RW various
            9: 0x00, 10: 0x00, 11: 0x00, 12: 0x00, 13: 0x00, 14: 0x00, # RW ADC thresholds
            17: 0x09, 18: 0x08, 19: 0x20, 20: 0x00, 21: 0x00, #RW various
            **{i: 0x00 for i in range(22, 74)}, #RO I2C readout data buffer
            74: 0x00, 75: 0x00} #RO various

# Board address: CHANGE FOR NEW BOARD
board_address = 0x72

# The writeable registers are 0-21, but 2, 7,and 15 are missing from the table, and 16 is WO
writeable = [0, 1, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13, 14, 17, 18, 19, 20, 21]


# Basic read and write functions -----------------------------------------------


def read_fcfd(board_address: int, address: int, n: int):
    # Read n bytes starting at register 'address', board address is 1 byte, register address is 2
    # Returns bytes on success, or None on error (prints the reason)
    buf = (ctypes.c_ubyte * n)()
    sa_high = (address >> 8) & 0xFF
    sa_low = address & 0xFF

    err = dll.I2CReadArrayDB(board_address, sa_high, sa_low, n, buf)
    if err != 0x00:
        print(f"Read error on register {address}: {_describe_error(err)}")
        return None
    return bytes(buf)

def write_fcfd(board_address: int, address: int, data) -> bool:
    # Write an int or a list of ints into registers starting at the two byte register address 'address'
    # Returns True on success, False on error (prints the reason).
    if isinstance(data, int) : data = bytes([data])
    else: data = bytes(data)
    n= len(data)
    buf = (ctypes.c_ubyte * n)(*data)
    sa_high = (address >> 8) & 0xFF
    sa_low = address & 0xFF

    err = dll.I2CWriteArrayDB(board_address, sa_high, sa_low, n, buf)
    if err != 0x00:
        print(f"Write error on register {address}: {_describe_error(err)}")
        return False
    return True


# Compositions of read and write commands for other purposes -------------------


# Check that a register matches the desired value
def check_reg(board_address: int, address: int, data: int) -> bool:
    check = read_fcfd(board_address, address, 1)
    if check == bytes([data]): return True
    else: return False

# Set writeable registers to default
def set_default(board_address: int, defaults: list, writeable: list) -> None:
    for i in writeable:
        check = False
        while not check:
            write_fcfd(board_address, i, defaults.get(i))
            check = check_reg(board_address, i, defaults.get(i))
        print(f'Register {i}: set to it\'s default value.')

# Check if the chip is in default state
def check_default(board_address: int, defaults:list, writeable: list) -> bool:
    bad = []
    for i in writeable:
        counter = 0
        while counter < 100:
            if check_reg(board_address, i, defaults.get(i)):
                break
            else:
                counter +=1
        if counter == 100: bad.append(i)
    if len(bad) == 0:
        print('All registers are in their default state')
        return True
    else:
        print(f'Registers {bad} are not in their default states')
        return False

# Find dongle NACK rate by reading all registers
def test_NACK_rate(board_address: int, n: int) -> None:
    counter = 0
    for j in range(n):
        for i in range(76):
            data = read_fcfd(board_address, i, 1)
            if data == None: counter += 1
    print(f'The NACK rate is {counter / (n*76)}')

# Test set and check default functions
def test_default(board_address: int, data: int) -> None:
    # Write data into the registers
    for i in range(22):
        print(f'Writing into register {i}')
        if i in writeable:
            check = False
            while not check:
                write_fcfd(board_address, i, data)
                check = check_reg(board_address, i, data)
    # Read out the registers to see that data was written into all writeable regs
    for i in range(22):
        value = read_fcfd(board_address, i, 1)
        if i in writeable:
            print(f'Register {i} reads {value}, expected {bytes([defaults.get(i)])}')
        else:
            print(f'Register {i} is not writeable, reads {value}')
    set_default(board_address, defaults, writeable)
    check_default(board_address, defaults, writeable)


# Clock test
# Registers of import: 20 bits 3 (test_out_sel) and [5:4] (clock_divider_config), 16 bit 4 (skip_ck40_strobe), 74 (clk40_phase)
# clock_divider_config: 0 is the TDC test mode, 1 is the external 40MHz mode, 2 is the BCR pulse mode, 3 is the external trigger mode
# 2.022 ns shift when 74 reads 00, but .978 ns shift when it reads 01

# Example use ------------------------------------------------------------------


if __name__ == "__main__":
    time.sleep(1)
    print("Devices found:", dll.GetNumberOfDevices())
    # print("Firmware rev (BCD):", hex(dll.GetFirmwareRevision()))
    #
    # actual_khz = dll.SetI2CFrequency(100)  # request 100 kHz
    # print(f"I2C frequency set to ~{actual_khz} kHz")

    #test_NACK_rate(board_address, 100) # --> gave a rate of 0.0 for 10000 trials, seems NACKs dont happen
    set_default(board_address, defaults, writeable)
    write_fcfd(board_address, 20, 48)
    # print('Register 20 reads: ', read_fcfd(board_address, 20, 1))
    # print('CK40 relative phase: ', read_fcfd(board_address, 74, 1))
    # print('Shifting...')
    # write_fcfd(board_address, 16, 16)
    # print('CK40 relative phase: ', read_fcfd(board_address, 74, 1))
    # for i in range(8):
    #     print('CK40 relative phase: ', read_fcfd(board_address, 74, 1))
    #     print('Shifting...')
    #     write_fcfd(board_address, 16, 16)
    #     time.sleep(2)
    #check_default(board_address, defaults, writeable)

    dll.ShutdownProcedure()
