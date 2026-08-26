from fcfd_bridge import FCFD

fcfd = FCFD("./FCFD_I2C_register_map.json")
fcfd.write_field("clk_eq", 2)
value = fcfd.read_field("clk40_phase")
print(value)