import serial
import time
from collections import Counter

#open serial port of device
ser = serial.Serial("/dev/ttyACM1", baudrate = 19200, timeout = 1)

#to send bytes you need to format them into byte format via bytes()
#serial object has a function write() that pushes sequences of bytes over the usb
#it also has a read(n: int) function that can read off a specific number of integers

# Default values (table 4) from /./FCFD_manual.pdf
defaults = {0: 0x05, 1: 0x05, 3: 0x06, 4: 0x06, 5: 0x06, 6: 0x06, 8: 0x00, #RW various
            9: 0x00, 10: 0x00, 11: 0x00, 12: 0x00, 13: 0x00, 14: 0x00, # RW ADC thresholds
            17: 0x09, 18: 0x08, 19: 0x20, 20: 0x00, 21: 0x00, #RW various
            **{i: 0x00 for i in range(22, 74)}, #RO I2C readout data buffer
            74: 0x00, 75: 0x00} #RO various

board_address = 0x39

#the writeable registers are 0-21, but 2, 7,and 15 are missing from the table, and 16 is WO
writeable = [0, 1, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13, 14, 17, 18, 19, 20, 21]


#from https://www.robot-electronics.co.uk/htm/usb_iss_i2c_tech.htm
I2C_DIRECT = 0x57
I2C_START = 0x01
I2C_RESTART = 0x02
I2C_STOP = 0x03
I2C_NACK = 0x04

USB_ISS = 0x5A
ISS_MODE = 0x02
I2C_S_100KHZ = 0x40

# I2C_Read sub-commands: 0x20-0x2F, n=1..16 bytes -> 0x20 + (n-1)
# I2C_Write sub-commands: 0x30-0x3F, n=1..16 bytes -> 0x30 + (n-1)

def _read_cmd(n: int) -> int:
    if not 1 <= n <= 16:
        raise ValueError("I2C_DIRECT read supports 1-16 bytes at a time")
    return 0x20 + (n - 1)


def _write_cmd(n: int) -> int:
    if not 1 <= n <= 16:
        raise ValueError("I2C_DIRECT write supports 1-16 bytes at a time")
    return 0x30 + (n - 1)


#write one byte into a FCFD register
def write_fcfd(board_address: int, address: int, data: int) -> bytes:
    board_address_write = board_address << 1 #lsb is a 0 for write
    sequence = bytes([I2C_DIRECT, I2C_START, _write_cmd(4), board_address_write, 0x00, address, data, I2C_STOP])
    ser.write(sequence)
    status = ser.read(2) #read if ACK [0]=0xFF or NACK [0]=0x00, [1]=count or error code
    return status


#read n bytes with a staring register
def read_fcfd(board_address: int, address: int, n: int) -> bytes:
    board_address_write = board_address << 1 #lsb is a 0 for write
    board_address_read = (board_address << 1)|1 #lsb is a 1 for read
    sequence = bytes([I2C_DIRECT, I2C_START,  _write_cmd(3), board_address_write, 0x00, address, I2C_RESTART, _write_cmd(1), board_address_read, _read_cmd(n), I2C_STOP])
    ser.write(sequence)
    status = ser.read(2) #read if ACK [0]=0xFF or NACK [0]=0x00
    if status[0] == 0x00:
        #print(f'Register {address}: got a NACK')
        return None
    data = ser.read(status[1])
    return data

#read several times and take the mode to avoid flipped bit reads also avoids NACKs
def read_robust(board_address: int, address: int, n: int, attempts: int = 30, rate: float = .5) -> bytes:
    results = []
    for i in range(attempts):
        data = read_fcfd(board_address, address, n)
        if data is not None:
            results.append(data)
    if not results:
        print(f'Register {address}: all {attempts} attempts NACKed, trying again...')
        return read_robust(board_address, address, n, attempts, rate)
    counts = Counter(results)
    value, count = counts.most_common(1)[0]
    if count < rate * attempts:
        #print(f'Register {address}: leading count too small, trying again...')
        return read_robust(board_address, address, n, attempts, rate)
    return value


#read until ACK
def read_until_ACK(board_address: int, address: int, n: int) -> bytes:
    #run it until one result hits a threshold satisfaction
    success = False
    while not success:
        list = []
        output = read_fcfd(board_address, address, n)
        if len(list) == 0: success = True
        else:
            print(f'Register {address}: got a NACK, trying again...')
    return output


#write until ACK
def write_until_ACK(board_address: int, address: int, data: int) -> bytes:
    success = False
    while not success:
        write_fcfd(board_address, address, data)
        if check_reg_until_ACK(board_address, address, data): success = True
        else: print(f'Register {address}: write unsuccessful, trying again...')


#write with read_robust
def write_robust(board_address: int, address: int, data: int) -> bytes:
    success = False
    while not success:
        write_fcfd(board_address, address, data)
        if check_reg_robust(board_address, address, data): success = True
        else: print(f'Register {address}: write unsuccessful, trying again...')


#check that a register matches the desired value
def check_reg_until_ACK(board_address: int, address: int, data: int) -> bool:
    #CAN GENERATE FALSE POSITIVES if reg holds a and we compare to b but the read returns b
    #happens sometimes if a and b are close together, made less likely by having two checks
    check_1 = read_until_ACK(board_address, address, 1)
    check_2 = read_until_ACK(board_address, address, 1)
    if check_1 == bytes([data]) and check_2 == bytes([data]): return True
    else: return False


#check that a register matches the desired value
def check_reg_robust(board_address: int, address: int, data: int) -> bool:
    check = read_robust(board_address, address, 1)
    if check == bytes([data]): return True
    else: return False


#set W registers to default
def set_default_robust(board_address: int, defaults: list, writeable: list) -> None:
    for i in writeable:
        check = False
        while not check:
            write_robust(board_address, i, defaults.get(i))
            check = check_reg_robust(board_address, i, defaults.get(i))
        print(f'Register {i}: set to it\'s default value.')


#check if the chip is in default state
def check_default_robust(board_address: int, defaults:list, writeable: list) -> bool:
    #see comment in check_reg for bugs
    bad = []
    for i in writeable:
        counter = 0
        while counter < 100:
            if check_reg_robust(board_address, i, defaults.get(i)):
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


#test write and read until ack
def test_1(board_address: int, address: int, data: int) -> None:
    print(read_until_ACK(board_address, 0, 1))
    write_until_ACK(board_address, address, data)
    print(read_until_ACK(board_address, 0, 1))
    print(f'The write worked: {check_reg_until_ACK(board_address, 0, data)}')


#Find dongle NACK rate by reading all registers
def NACK_rate(board_address: int, n: int) -> None:
    counter = 0
    for j in range(n):
        for i in range(76):
            data = read_fcfd(board_address, i, 1)
            if data == None: counter += 1
    print(f'The NACK rate is {counter / (n*76)}')


#check read_robust function
def test_2(board_address: int, address: int, n: int) -> None:
    other_counter = 0
    for i in range(n):
        data = read_robust(board_address, address, 1)
        if data != bytes([defaults.get(address)]): other_counter += 1
    print(f'read_robust has a success rate of {(n - other_counter) / n} on register {address}')


#test set and check default functions
def test_default(board_address: int, data: int) -> None:
    #write 2 = 0x02 into the registers
    for i in range(22):
        if i in writeable:
            check = False
            while not check:
                write_robust(board_address, i, data)
                check = check_reg_robust(board_address, i, data)
    #read out the registers to see that 10 was written into all writeable regs
    for i in range(22):
        value = read_robust(board_address, i, 1)
        if i in writeable:
            print(f'Register {i} reads {value}, expected {bytes([defaults.get(i)])}')
        else:
            print(f'Register {i} is not writeable, reads {value}')
    set_default_robust(board_address, defaults, writeable)
    check_default_robust(board_address, defaults, writeable)


def main():

    test_1(board_address, 0, 0x02)

    NACK_rate(board_address, 100)

    test_2(board_address, 0, 100)

    test_default(board_address, 0x02)



if __name__ == "__main__":
    main()
