from FCFD_I2C_register import FCFD_I2C_register

fcfd = FCFD_I2C_register("./FCFD_I2C_register_map.json")

def successful_write_rate(fcfd, register: str, n: int):
    og_val = fcfd.read(register)
    success_counter = 0
    if fcfd._registers[register]['access'] == fcfd.access_type.READ_ONLY: 
        print(f'Register {register} is read only.')
        return None
    for i in range(n):
        if fcfd.write(register, 0): success_counter+=1
    fcfd.write(register, og_val)
    rate = success_counter / n
    return rate

if __name__ == "__main__":
    print(successful_write_rate)