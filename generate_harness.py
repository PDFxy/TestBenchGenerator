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
parser.add_argument('--trace', action="store_true", help="Dump a .vcd using verilator")
parser.add_argument('--trace-file-name', default="top_tb.vcd")
parser.add_argument('--quiet', action="store_true", help="Silence cycle counter")

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
verify_config = ""
run_test = ""
clk_switch = ""
stall = ""
unstall = ""


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
#include "printf.h"
"""

if args.trace:
    step_command = f"step({wrapper_name}, time_step, tfp);"
else:
    step_command = f"step({wrapper_name});"

if args.trace:
    next_command = f"next({wrapper_name}, time_step, tfp);"
else:
    next_command = f"next({wrapper_name});"

trace_setup = ""
if args.trace:
    includes += "#include \"verilated_vcd_c.h\"\n"
    trace_setup += f"""
        Verilated::traceEverOn(true);
        VerilatedVcdC* tfp = new VerilatedVcdC;
        top->trace(tfp, 99); // What is 99?  I don't know!  FIXME
        tfp->open(\"{args.trace_file_name}\");
        uint32_t time_step = 0;
    """
    file_close += "tfp->close();\n"

if (args.use_jtag):
    includes += '#include "jtagdriver.h"\n'
    if args.trace:
        jtag_setup += f"""
            JTAGDriver jtag({wrapper_name}, tfp, &time_step);
        """
    else:
        jtag_setup += f"""
            JTAGDriver jtag({wrapper_name});
        """


chip_init += f"""
    {wrapper_name}->clk_pad = 0;
    {wrapper_name}->reset_pad = 0;
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
    {wrapper_name}->reset_pad = 1;
    {wrapper_name}->eval();
    {wrapper_name}->reset_pad = 0;
    {wrapper_name}->eval();
"""

if (args.use_jtag):
    chip_reset += f"""
    jtag.reset();
    jtag.tck_bringup();
    """

########################################
#     "reset_in_pad": {
#         "pad_bus" : "pads_N_0",
#         "bits": {
#             "0": { "pad_bit":"0" }
#         },
#         "mode": "in",
#         "width": 1
reset_in_pad = None
for module in io_collateral:
    if module == "reset_in_pad":
        reset_in_pad = io_collateral[module]["pad_bus"]
        for bit, pad_info in io_collateral[module]["bits"].items():
            pad_bit = pad_info["pad_bit"]
            break;
assert reset_in_pad != None, "No reset_pad_in in io_config file"    


if (args.use_jtag):
    stall += f"""
        jtag.stall();
    """
else:
    stall += f"""\
{wrapper_name}->{reset_in_pad}_in = (1 << {pad_bit}); // STALL"""

if (args.use_jtag):
    unstall += f"""
        jtag.unstall();
    """
else:
    unstall += f"""\
{wrapper_name}->{reset_in_pad}_in = (0 << {pad_bit}); // UNSTALL"""

# print(stall); print(unstall); exit()

if (args.use_jtag):
    run_config += f"""
        jtag.write_config(config_addr_arr[i],config_data_arr[i]);
    """
else :
    run_config += f"""
        {wrapper_name}->config_data_in = config_data_arr[i];
        {wrapper_name}->config_addr_in = config_addr_arr[i];
        {next_command}
    """


if (args.use_jtag and args.verify_config):
    verify_config += f"""
        std::cout << "reading configuration" << std::endl;
        bool config_error = false;
        for (int i = 0; i < {len(config_data_arr)}; i++) {{
            uint32_t read_data = jtag.read_config(config_addr_arr[i]);
            if (read_data != config_data_arr[i]) {{
                printf("ERROR - Iteration=%d, read_data=0x%08x, config_data_arr[i]=0x%08x, config_addr_arr[i]=0x%08x\\n", i, read_data, config_data_arr[i], config_addr_arr[i]);
                config_error = true;
            }};
        }}
        if (config_error) {{
            std::cout << "error in configuration" << std::endl;
            // FIXME: 1-bit IO pads are flipped (bit0 and bit1) causing an error
            // exit(1);
        }}
    """


if (args.use_jtag):
    clk_switch += f"""
    jtag.switch_to_fast();
    {wrapper_name}->clk_pad = 1;
    {wrapper_name}->eval();
    for (int i = 0; i < 5; i++) {{
        {next_command}
    }}
    """

# for entry in IOs:
for module in io_collateral:
    if module == "reset_in_pad": continue   # (already processed, above)
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
        pad_bus = io_collateral[module]["pad_bus"]
        if "bits" in io_collateral[module]:
            #    "io16in_in_arg_1_0_0": {
            #        "pad_bus" : "pads_W_0",
            #        "bits": {
            #             "0": { "pad_bit":"0" },
            #             "1": { "pad_bit":"1" },
            #             ...
            #            "15": { "pad_bit":"15" }
            #        "mode": "in",
            #        "width": 16
            input_body += f"""
        {wrapper_name}->{pad_bus}_in = 0;"""
            for bit, pad_info in io_collateral[module]["bits"].items():
                pad_bit = pad_info["pad_bit"]
                input_body += f"""
        {wrapper_name}->{pad_bus}_in |= get_bit({bit:>2s}, {module}_in) << {pad_bit:>2s};"""
        else:
            # "io16in_in_arg_1_0_0": {
            #     "bus" : "pads_W_0",
            #     "mode": "in",
            #     "width": 16
            input_body += f"""
        {wrapper_name}->{pad_bus}_in = {module}_in;"""
        # print(input_body);

    else: # mode == "out"
        pad_bus = io_collateral[module]["pad_bus"]
        assert mode == "out"
        if "bits" in io_collateral[module]:
            output_body += f"""\n
        {module}_out = 0;"""
            for bit, pad_info in io_collateral[module]["bits"].items():
                pad_bit = pad_info["pad_bit"]
                output_body += f"""
        set_bit( (({wrapper_name}->{pad_bus}_out >> {pad_bit:>2s}) & 0x1), {bit:>2s}, {module}_out);"""
        else:
            output_body += f"""
        {module}_out = {wrapper_name}->{pad_bus}_out;"""

        output_body += f"""
        {module}_file.write((char *)&{module}_out, sizeof(uint{args.chunk_size}_t));"""
        # print(output_body); exit();


    file_close += f"""
        {module}_file.close();
    """

step_trace_args = ""
step_trace_body = ""
if args.trace:
    step_trace_args = ", uint32_t &time_step, VerilatedVcdC* tfp"
    step_trace_body = f"""
        tfp->dump(time_step);
        time_step++;
    """

step_def = f"""\
void step(V{wrapper_name} *{wrapper_name}{step_trace_args}) {{
    {wrapper_name}->clk_pad ^= 1;
    {wrapper_name}->eval();
    {step_trace_body}
}}
"""

next_step_args = ""
next_step_params = ""
if args.trace:
    next_step_args = ", (time_step), (tfp)"
    next_step_params = ", time_step, tfp"

log = ""
if not args.quiet:
    log = "if (i % 10 == 0) std::cout << \"Cycle: \" << i << std::endl;\n"

next_def = f"""\
#define next(circuit{next_step_params}) \\
        do {{ step((circuit){next_step_args}); step((circuit){next_step_args}); }} while (0)
"""

harness = f"""\
{includes}

{next_def}

static const uint32_t config_data_arr[] = {config_data_arr_str};
static const uint32_t config_addr_arr[] = {config_addr_arr_str};

// TODO: How many cycles do we actually need to hold reset down?
static const uint32_t NUM_RESET_CYCLES = 5;

{step_def}

uint8_t get_bit(uint8_t bit_position, uint{args.chunk_size}_t bit_vector) {{
    return (bit_vector >> bit_position) & 1;
}}

void set_bit(uint8_t value, uint8_t bit_position, uint{args.chunk_size}_t &bit_vector) {{
    bit_vector |= (value << bit_position);
}}

int main(int argc, char **argv) {{
    Verilated::commandArgs(argc, argv);
    V{wrapper_name}* {wrapper_name} = new V{wrapper_name};
    {trace_setup}

    {file_setup}

    //Intialize jtag driver
    {jtag_setup}

    //Initialize all inputs to known values
    {chip_init}

    //Reset the chip
    {chip_reset}
    std::cout << "Done resetting" << std::endl;

    {stall}

    // Start clock at 1
    {wrapper_name}->clk_pad = 1;
    {wrapper_name}->eval();

    std::cout << "Beginning configuration" << std::endl;
    for (int i = 0; i < {len(config_data_arr)}; i++) {{
      {run_config}
    }}

    {verify_config}

    std::cout << "Done configuring" << std::endl;

    {clk_switch}

    {unstall}

    std::cout << "Running test" << std::endl;
    for (int i = 0; i < {args.max_clock_cycles}; i++) {{
        {input_body}
        {step_command}  // clk_pad = 0
        {output_body}
        {step_command}  // clk_pad = 1
        {log}
    }}
    std::cout << "Done testing" << std::endl;

    {file_close}

    delete {wrapper_name};
}}
"""

with open(args.output_file_name, "w") as harness_file:
    harness_file.write(harness)
