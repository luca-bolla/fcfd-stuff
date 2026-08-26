"""
Bridge between FCFD_I2C_register.py (field-level bookkeeping/validation)
and fcfd_windows.py (raw byte-level I2C read/write via the DLL).

FCFD_I2C_register knows *where* each named field lives (which byte(s),
which bits) and validates values against that layout, but it never talks
to hardware. fcfd_windows.py talks to hardware but only in terms of whole
bytes at fixed addresses, with no idea that e.g. byte 0 is actually five
different fields packed together (clk_enable, clk_inv_data, clk_en_term,
clk_eq, clk_common_mode).

This module adds the missing piece: given a field name from the JSON map,
figure out which bits of which byte(s) it occupies, and do a proper
read-modify-write so that writing one field doesn't clobber its neighbors
in the same byte.

Run only on the Windows machine with USBtoI2Cpro.dll installed, since it
imports fcfd_windows.py (which loads the DLL at import time).
"""

import logging
from FCFD_I2C_register import FCFD_I2C_register
from fcfd_windows import read_fcfd, write_fcfd, board_address as DEFAULT_BOARD_ADDRESS


def _field_bit_layout(properties: dict):
    """
    Return a list of (byte_offset, lsb, msb) tuples describing, for a given
    field's properties dict (as stored in FCFD_I2C_register._registers),
    exactly which bits of which byte(s) belong to it.

    byte_offset is 0-based, relative to the field's own starting address
    (properties['address'][0]) -- NOT the absolute chip register address.
    """
    address = properties["address"]
    bit_range = properties["bit_range"]
    LSA, MSA = address[0], address[-1]
    n_bytes = MSA - LSA + 1

    if len(address) == 1:
        # Single-byte field. bit_range is [bit] or [lsb, msb].
        if len(bit_range) == 1:
            lsb = msb = bit_range[0]
        else:
            lsb, msb = bit_range[0], bit_range[-1]
        return [(0, lsb, msb)]

    # Multi-byte field.
    if all(isinstance(entry, list) for entry in bit_range):
        # A distinct [lsb, msb] pair given for each byte in order.
        return [(i, entry[0], entry[-1]) for i, entry in enumerate(bit_range)]

    # One [lsb, msb] pair that applies identically to every byte
    # (e.g. the 8-byte TDC data fields, which are just plain byte-aligned).
    lsb, msb = bit_range[0], bit_range[-1]
    return [(i, lsb, msb) for i in range(n_bytes)]


class FCFD:
    """
    Ties an FCFD_I2C_register field map to the live hardware functions in
    fcfd_windows.py, so you can read/write registers *by field name*
    (e.g. 'clk_eq', 'ser_drive_str') instead of hand-computing byte values
    and bit shifts yourself.
    """

    def __init__(self, json_file: str, board_address: int = DEFAULT_BOARD_ADDRESS):
        self.regmap = FCFD_I2C_register(json_file)
        self.board_address = board_address

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def read_field(self, name: str):
        """
        Read a named field straight from the chip and return it as a
        single Python int (already assembled across bit/byte boundaries).
        Returns None on an I2C error or unknown field.
        """
        if name not in self.regmap._registers:
            logging.debug(f"[FCFD.read_field] Unknown field: {name!r}")
            return None

        properties = self.regmap._registers[name]
        LSA, MSA = properties["address"][0], properties["address"][-1]
        n_bytes = MSA - LSA + 1

        raw = read_fcfd(self.board_address, LSA, n_bytes)
        if raw is None:
            return None

        value = 0
        shift = 0
        for byte_offset, lsb, msb in _field_bit_layout(properties):
            width = msb - lsb + 1
            mask = (1 << width) - 1
            extracted = (raw[byte_offset] >> lsb) & mask
            value |= extracted << shift
            shift += width

        # Keep the in-memory copy in sync with what's actually on the chip.
        properties["value"] = raw
        return value

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    def write_field(self, name: str, value: int) -> bool:
        """
        Write a single named field on the chip, without disturbing any
        other field that happens to share the same byte(s).

        This does a read-modify-write: it reads the current byte(s) for
        this field's address range, patches in just this field's bits,
        then writes the whole byte(s) back.
        """
        if name not in self.regmap._registers:
            logging.debug(f"[FCFD.write_field] Unknown field: {name!r}")
            return False

        properties = self.regmap._registers[name]
        if properties["access"] == self.regmap.access_type.READ_ONLY:
            logging.debug(f"[FCFD.write_field] Field {name!r} is read-only")
            return False

        layout = _field_bit_layout(properties)
        total_width = sum(msb - lsb + 1 for _, lsb, msb in layout)
        if value < 0 or value >= (1 << total_width):
            logging.debug(
                f"[FCFD.write_field] Value {value} does not fit in "
                f"{total_width}-bit field {name!r}"
            )
            return False

        LSA, MSA = properties["address"][0], properties["address"][-1]
        n_bytes = MSA - LSA + 1

        # Write-only strobe bits (default 'N/A') have nothing meaningful to
        # preserve, so skip the read-back and just start from zero bytes.
        if properties["access"] == self.regmap.access_type.WRITE_ONLY:
            current = bytearray(n_bytes)
        else:
            existing = read_fcfd(self.board_address, LSA, n_bytes)
            if existing is None:
                logging.debug(
                    f"[FCFD.write_field] Could not read back byte(s) for "
                    f"{name!r} before patching; aborting to avoid clobbering "
                    f"neighboring fields"
                )
                return False
            current = bytearray(existing)

        shift = 0
        for byte_offset, lsb, msb in layout:
            width = msb - lsb + 1
            mask = (1 << width) - 1
            piece = (value >> shift) & mask
            current[byte_offset] = (current[byte_offset] & ~(mask << lsb) & 0xFF) | (piece << lsb)
            shift += width

        ok = write_fcfd(self.board_address, LSA, bytes(current))
        if ok:
            # Also validate/update FCFD_I2C_register's own cache so the two
            # stay consistent. Its write() wants one byte-sized value per
            # element of `current`, checked against this field's bit_range,
            # which is exactly what `current` already is here.
            self.regmap.write(name, bytearray(current))
        return ok

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def dump_field(self, name: str) -> None:
        """Print a field's live chip value next to its description."""
        properties = self.regmap._registers.get(name)
        if properties is None:
            print(f"Unknown field: {name!r}")
            return
        value = self.read_field(name)
        print(f"{name} = {value}  ({properties['description']})")


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")

    fcfd = FCFD("./FCFD_I2C_register_map.json")

    # Example: change just the clock receiver equalizer setting (2 bits,
    # address 0, bits [3:4]) without touching clk_enable / clk_inv_data /
    # clk_en_term / clk_common_mode, which live in the same byte.
    fcfd.write_field("clk_eq", 2)
    fcfd.dump_field("clk_eq")

    # Example: bump the serializer driver strength (address 3, bits [1:3]),
    # leaving ser_inv_data / ser_emph_mode / ser_emph_width in byte 3 alone.
    fcfd.write_field("ser_drive_str", 5)
    fcfd.dump_field("ser_drive_str")

    # Example: read a read-only status field spanning a bit boundary.
    fcfd.dump_field("clk40_phase")

    # Example: fire a write-only strobe bit (reset the readout logic).
    fcfd.write_field("reset_readout", 1)
