import json
from enum import Enum
from typing import Type
import logging
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




class FCFD_I2C_register:
    """
    This class defines the register structure for the FCFD I2C interface. It provides 
    methods to read from and write to the registers, as well as to configure the I2C 
    settings. The class encapsulates the register addresses and their corresponding 
    values, allowing for easy manipulation of the I2C interface.
    """
    class access_type(Enum):
        READ_ONLY = 0
        WRITE_ONLY = 1
        READ_WRITE = 2
    
    def __init__(self, board_address: int, json_file:str = None):
        time.sleep(1)
        print("Devices found:", dll.GetNumberOfDevices())

        self._registers = {}
        self.board_address = board_address
        if json_file is None:
            return
        with open(json_file, 'r') as f:
            input_json = json.load(f)

        for register, properties in input_json.items():
            if not isinstance(properties, dict):
                continue

            access_type_str = properties['access'].lower()
            access_types = {
                'ro': self.access_type.READ_ONLY,
                'wo': self.access_type.WRITE_ONLY,
                'rw': self.access_type.READ_WRITE,
            }
            try:
                access_type = access_types[access_type_str]
            except KeyError as error:
                raise ValueError(
                    f"Unsupported access type {access_type_str!r} for {register!r}"
                )

            address = properties['address']
            # Address can either be a list with 
            # 1 element for individual registers
            # or 2 elements marking the starting and ending address bytes for grouped registers

            # Each register has a 2 byte address and 1 byte of data, the 8 data bits are allocated as in the json,
            # some portions of the register map have sequential registers that save the same purpose hence motivating the 'grouped registers'
            if (not isinstance(address, list) 
                or (len(address)!= 1 and len(address)!=2)):
                raise ValueError(
                    f"Address for {register!r} must be list of 1 or 2 elements, currently being {address}"
                )

            LSA = properties["address"][0]
            MSA = properties["address"][-1]
            byte_width = MSA - LSA +1 
            bit_range = properties['bit_range']
            # If it is a single byte register bit_range can be
            # 1-d list have 1 element being the bit of the register
            # 1-d list have 2 element marking the start and end bit of the register 
            if len(address)==1:
                if (not isinstance(bit_range, list)
                    or (len(bit_range)!=1 and len(bit_range)!=2)):
                    raise TypeError(
                        f"Bit_range for {register!r} must be a list of 1 or 2 elements, currently being {bit_range}"
                    )
            # If it is a mulit-byte register bit_range can be
            # 1-d list have 2 element for the same bits in all bytes
            # 2-d list [n][2], marking the start and end bit of the register in each byte repectively
            else:
                byte_width = MSA - LSA + 1
                if not isinstance(bit_range, list) or (
                    len(bit_range) != 2 and not (
                        all(isinstance(entry, list) and len(entry) == 2 for entry in bit_range)
                    )
                ):
                    raise TypeError(
                        f"Bit_range for {register!r} must be a 1-d list of 2 elements or a 2-d list [n][2] for a multi-byte register, currently being {bit_range}"
                    )

            # default must be N/A or single integer
            if properties['default'] == 'N/A':
                default = None
                value = [None] * byte_width
            elif not isinstance(properties['default'], int):
                raise TypeError(
                    f"Address and bit_range for {register!r} must be lists"
                )
            else:
                default = properties['default']
                value = bytearray([default]) * byte_width
            self._registers[register] = {
                'address': address,
                'bit_range': bit_range,
                'access': access_type,
                'default': default,
                'value': value
            }

    def _per_byte_ranges(self, bit_range, byte_width):
        # Normalize bit_range into a list of (lsb, msb) tuples, one per byte in the register
        # Used by both read and write
        
        # For a field that covers a single byte
        if byte_width == 1:
            # For a field that covers one bit on one byte
            if len(bit_range) == 1:
                return [(bit_range[0], bit_range[0])]
            # For a field that covers several bits on one byte
            return [(bit_range[0], bit_range[-1])]
        # For a field that covers multiple bytes
        if all(isinstance(entry, list) for entry in bit_range):
            # For a field of multiple bytes where the bit_range is a list of lists eg 'hit_trig_bcid'
            return [(entry[0], entry[-1]) for entry in bit_range]
        # For a field of multiple bytes where each byte uses the same range of bits eg 'ch5_TDC_data'
        return [(bit_range[0], bit_range[-1])] * byte_width

    def write(self, register: str, value: bytearray=bytearray() ) -> bool:
        # Write byte array to the register
        # If you want to write 0 to register 'write_test' you would do FCFD_I2C_register.write('write_test', [0])
        # Accepts an integer or a byte array-like payload and validates it against the configured bit range before storing the result
        
        # Register must exist
        if register not in self._registers:
            logging.debug(f"[FCFD_I2C_register.write] Unknown register: {register!r}")
            return False

        # Register must be writable
        properties = self._registers[register]
        if properties['access'] == self.access_type.READ_ONLY:
            logging.debug(f"[FCFD_I2C_register.write] Register {register!r} is read-only")
            return False

        LSA = properties["address"][0]
        MSA = properties["address"][-1]
        # Number of bytes the register covers
        byte_width = MSA - LSA +1 

        if(len(value) != byte_width):
            logging.debug(f"[FCFD_I2C_register.write] Mismatch in register size and value size")
            logging.debug(f"[FCFD_I2C_register.write] Register {register} has {byte_width} bytes")
            logging.debug(f"[FCFD_I2C_register.write] Value has {len(value)} bytes")
            return False

        # Establish the bit ranges per byte of the register
        bit_range = properties["bit_range"]
        per_byte = self._per_byte_ranges(bit_range, byte_width)

        # Bit-width check between the input value and the available bits
        for byte_val, (lsb, msb) in zip(value, per_byte):
            bit_width = msb - lsb + 1
            if byte_val >= ((0b1) << bit_width):
                logging.debug(f"[FCFD_I2C_register.write] Mismatch in register size and value size")
                logging.debug(f"[FCFD_I2C_register.write] Register {register} has {bit_width} bits")
                logging.debug(f"[FCFD_I2C_register.write] Cannot contain 0b{byte_val:b}")
                return False
 
        # Fields can share a byte with other fields (e.g. clk_enable, clk_inv_data, clk_eq etc. are all packed into byte 0)
        # So read the current byte(s) first, patch in only this field's bits, and write the whole byte(s) back
        if properties['access'] == self.access_type.WRITE_ONLY:
            # Strobe bits have no meaningful state to preserve
            current = bytearray(byte_width)
        else:
            existing = read_fcfd(self.board_address, LSA, byte_width)
            if existing is None:
                logging.debug(f"[FCFD_I2C_register.write] Could not read back current value of {register!r} before writing; aborting")
                return False
            current = bytearray(existing)
 
        for i, (byte_val, (lsb, msb)) in enumerate(zip(value, per_byte)):
            width = msb - lsb + 1
            mask = (1 << width) - 1
            current[i] = (current[i] & ~(mask << lsb) & 0xFF) | ((byte_val & mask) << lsb)

        # Actually write the values to the chip
        if not write_fcfd(self.board_address, LSA, bytes(current)):
            return False

        properties['value'] = value
        return True

    def read(self, register: str) -> bytearray:
        # Read the register from hardware and return the field's value(s) as a bytearray
        # Returns None on an unknown register, a write-only register, or an I2C error.
        
        # Check that the register exists
        if register not in self._registers:
            logging.debug(f"[FCFD_I2C_register.read] Unknown register: {register!r}")
            return None

        # Check that the register can be read from
        properties = self._registers[register]
        if properties['access'] == self.access_type.WRITE_ONLY:
            logging.debug(f"[FCFD_I2C_register.read] Register {register!r} is write-only")
            return None
 
        LSA = properties["address"][0]
        MSA = properties["address"][-1]
        # How many bytes the register spans
        byte_width = MSA - LSA + 1

        # Read the byte values of the register's span
        raw = read_fcfd(self.board_address, LSA, byte_width)
        if raw is None:
            return None

        # Create the bit range per byte in the field's byte span
        per_byte = self._per_byte_ranges(properties['bit_range'], byte_width)
        extracted = bytearray(byte_width)
        # Split the raw read values into the values for the register
        for i, (byte_val, (lsb, msb)) in enumerate(zip(raw, per_byte)):
            width = msb - lsb + 1
            mask = (1 << width) - 1
            extracted[i] = (byte_val >> lsb) & mask
 
        properties['value'] = extracted
        return extracted

    # Check that a register matches the desired value
    def check_reg(self, register: str, data: bytearray=bytearray()) -> bool:
        check = self.read(register)
        if check == bytes(data): return True
        else: return False

    # Set writeable registers to default values
    def set_default(self) -> None:
        for register in self._registers:
            if self._registers[register]['access'] == self.access_type.READ_ONLY: 
                print(f'Register {register}: this register is read only.')
                continue
            if self._registers[register]['access'] == self.access_type.WRITE_ONLY: 
                print(f'Register {register}: this register is write only.')
                continue
            check = False
            while not check:
                value = [self._registers[register]['default']]
                self.write(register, value)
                check = self.check_reg(register, value)
            print(f'Register {register}: has been set to it\'s default value.')
    
    def __str__(self):
        rtn = ""
        for register, properties in self._registers.items():
            rtn += f"Register: {register}\n"
            for key, value in properties.items():
                rtn+=f"\t{key}:{value}\n"
        return rtn

if __name__ == "__main__":
    # Always run these first two lines first to ensure the computer sees the dongle
    time.sleep(1)
    print("Devices found:", dll.GetNumberOfDevices())

    i2c = FCFD_I2C_register(0x72, './FCFD_I2C_register_map.json')
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
    logging.debug(i2c)
    # Now show some error/correct example
    logging.debug(i2c.write('sadfasfd',[1])) # register doesn't exist
    logging.debug(i2c.write('wb_error_count')) # read-only
    logging.debug(i2c.write('clk_enable')) # mis-match
    logging.debug(i2c.write('clk_enable',[1,1])) # mis-match
    logging.debug(i2c.write('clk_enable',[11])) # mis-match
    logging.debug(i2c.write('clk_enable',[1])) # correct, now also hits hardware
    logging.debug(i2c.read('clk_eq'))


