# ❯ python generate_harness.py --pnr-io-collateral pointwise.io.json --bitstream pointwise.bs && astyle harness.cpp

import argparse
import json

parser = argparse.ArgumentParser(description='Test the cgra')
# parser.add_argument('--IO', metavar='<IO_FILE>', help='File containing mapping between IO ports and files', dest="pnr_io_collateral")
parser.add_argument('--pnr-io-collateral', metavar='<collateral_file>.io.json', help='Collateral file generated by SMT-PNR', required=True)
parser.add_argument('--bitstream', metavar='<BITSTREAM_FILE>', help='Bitstream file containing the CGRA configuration', required=True)
parser.add_argument('--trace-file', help='Trace file', default=None)
parser.add_argument('--max-clock-cycles', help='Max number of clock cyles to run', default=40, type=int)
parser.add_argument('--wrapper-module-name', help='Name of the wrapper module', default='top')
parser.add_argument('--chunk-size', help="Size in bits of the data in the input/output files", default=8, type=int)
parser.add_argument('--output-file-name', help="Name of the generated harness file", default="harness.cpp")
parser.add_argument('--use-jtag', help="Should this test harness use JTAG to write config", default=False, action="store_true")
parser.add_argument('--verify-config', help="Should this test harness read back all the config after writing", default=False, action="store_true")

args = parser.parse_args()

config_data_arr = []
config_addr_arr = []

with open(args.bitstream, "r") as bitstream_file:
    for line in bitstream_file:
        if line[0] == "#" or line == "\n":
            continue  # Skip comment or empty lines from serpent bistream
        config_addr, config_data = line.split()
        config_addr_arr.append(f"0x{config_addr}")
        config_data_arr.append(f"0x{config_data}")

config_data_arr_str = "{" + ", ".join(config_data_arr) + "}"
config_addr_arr_str = "{" + ", ".join(config_addr_arr) + "}"

with open(args.pnr_io_collateral, "r") as pnr_collateral:
    io_collateral = json.load(pnr_collateral)

# with open(args.IO, "r") as IO_file:
#     """
#     { 
#         "<module_name>": "<file_name>",
#         "<module_name>": "<file_name>",
#         "<module_name>": "<file_name>"
#         ...
#     }
#     """
#     IOs = json.load(IO_file)


includes = ""
file_setup = ""
jtag_setup = ""
chip_init = ""
chip_reset = ""
run_config = ""
read_config = ""
run_test = ""
clk_switch = ""

input_body = ""
output_body = ""
file_close = ""
wrapper_name = args.wrapper_module_name


includes = f"""
#include "V{wrapper_name}.h"
#include "verilated.h"
#include <iostream>
#include "stdint.h"
#include <fstream>
"""

if (args.use_jtag):
    includes += '#include "jtagdriver.h"'
    jtag_setup += f"""
    JTAGDriver jtag({wrapper_name});
    """


chip_init += f"""
    {wrapper_name}->clk_in = 0;
    {wrapper_name}->reset_in = 0;
"""
if (args.use_jtag):
    chip_init += f"""
    jtag.init();
    """
else:

    chip_init += f"""
        {wrapper_name}->config_addr_in = 0;
        {wrapper_name}->config_data_in = 0;
    """
chip_init += f"""
    {wrapper_name}->eval();
"""

chip_reset = f"""
    {wrapper_name}->reset_in = 1;
    {wrapper_name}->eval();
    {wrapper_name}->reset_in = 0;
    {wrapper_name}->eval();
    {wrapper_name}->clk_in = 1;
    {wrapper_name}->eval();
"""
if (args.use_jtag):
    chip_reset += f"""
    jtag.reset();
    jtag.tck_bringup();
    """


if (args.use_jtag):
    run_config += f"""
        jtag.write_config(config_addr_arr[i],config_data_arr[i]);
    """
else :
    run_config += f"""
        {wrapper_name}->config_data_in = config_data_arr[i];
        {wrapper_name}->config_addr_in = config_addr_arr[i];
        next({wrapper_name}); // clk_in = 1
    """


if (args.use_jtag and args.verify_config):
    read_config += f"""
        uint32_t read_data = jtag.read_config(config_addr_arr[i]);
        assert(read_data == config_data_arr[i]);
    """


if (args.use_jtag):
    clk_switch += f"""
    jtag.switch_to_fast();
    """

# for entry in IOs:
for module in io_collateral:
    file_name = f"{module}.raw"
    mode = io_collateral[module]["mode"]
    if mode == "inout":
        raise NotImplementedError()
    file_setup += f"""
        std::fstream {module}_file("{file_name}", ios::{mode} | ios::binary);
        if (!{module}_file.is_open()) {{
            std::cout << "Could not open file {file_name}" << std::endl;
            return 1;
        }}
        uint{args.chunk_size}_t {module}_{mode} = 0;
    """

    if mode == 'in':
        input_body += f"""
            {module}_file.read((char *)&{module}_in, sizeof(uint{args.chunk_size}_t));
            if ({module}_file.eof()) {{
                std::cout << "Reached end of file {file_name}" << std::endl;
                break;
            }}
        """
        for bit, pad in io_collateral[module]["bits"].items():
            input_body += f"""
            {wrapper_name}->{pad}_in = get_bit({bit}, {module}_in);
        """
    else:
        output_body += f"{module}_out = 0;\n"
        for bit, pad in io_collateral[module]["bits"].items():
            output_body += f"""
                set_bit({wrapper_name}->{pad}_out, {bit}, {module}_out);
            """
        output_body += f"""
            {module}_file.write((char *)&{module}_out, sizeof(uint{args.chunk_size}_t));
        """

    file_close += f"""
        {module}_file.close();
    """

harness = f"""\
{includes}

#define next(circuit) \\
    do {{ step((circuit)); step((circuit)); }} while (0)

static const uint32_t config_data_arr[] = {config_data_arr_str};
static const uint32_t config_addr_arr[] = {config_addr_arr_str};

// TODO: How many cycles do we actually need to hold reset down?
static const uint32_t NUM_RESET_CYCLES = 5;

void step(V{wrapper_name} *{wrapper_name}) {{
    {wrapper_name}->clk_in ^= 1;
    {wrapper_name}->eval();
}}

uint8_t get_bit(uint8_t bit_position, uint{args.chunk_size}_t bit_vector) {{
    return (bit_vector >> bit_position) & 1;
}}

void set_bit(uint8_t value, uint8_t bit_position, uint{args.chunk_size}_t &bit_vector) {{
    bit_vector |= (value << bit_position);
}}

int main(int argc, char **argv) {{
    Verilated::commandArgs(argc, argv);
    V{wrapper_name}* {wrapper_name} = new V{wrapper_name};

    {file_setup}
    
    //Intialize jtag driver
    {jtag_setup}

    //Initialize all inputs to known values
    {chip_init}

    //Reset the chip
    {chip_reset}
    std::cout << "Done resetting" << std::endl;

    std::cout << "Beginning configuration" << std::endl;
    for (int i = 0; i < {len(config_data_arr)}; i++) {{
      {run_config}
    }}
    
    std::cout << "reading configuration" << std::endl;
    for (int i = 0; i < {len(config_data_arr)}; i++) {{
      {read_config}
    }}
    
    std::cout << "Done configuring" << std::endl;
    
    {clk_switch}

    std::cout << "Running test" << std::endl;
    for (int i = 0; i < {args.max_clock_cycles}; i++) {{
        {input_body}
        step({wrapper_name}); // clk_in = 0
        {output_body}
        step({wrapper_name}); // clk_in = 1
        if (i % 10 == 0) std::cout << "Cycle: " << i << std::endl;
    }}
    std::cout << "Done testing" << std::endl;

    {file_close}

    delete {wrapper_name};
}}
"""

with open(args.output_file_name, "w") as harness_file:
    harness_file.write(harness)
