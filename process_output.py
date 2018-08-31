import json
import sys
import shutil
import os
dir_path = os.path.dirname(os.path.abspath(__file__))


with open(sys.argv[1], "r") as file:
    info = json.load(file)

target_file_name = sys.argv[2]
app = sys.argv[3]
delay_in, delay_out = [int(x) for x in sys.argv[4].split(",")]

name = None
for key in info:
    if info[key]["mode"] == "out":
        # TODO: Hack to ignore 1 bit output that doesn't need to be post processed
        if info[key]["width"] == 1:
            continue
        assert name is None, "This only works for one output"
        name = key

assert name is not None, "We need at least one output"

if delay_in:
    print(delay_in)
    with open(f"{name}.raw", "rb") as output_file:
        output_file.seek(delay_in)
        output_data = output_file.read()
    with open(f"{name}.raw", "wb") as output_file:
        output_file.write(output_data)

# TODO: Why do we we do this post processing for these apps?
if app == "conv_1_2":
    import delegator
    print(f"bin/conv_1_2_convert < {name}.raw > {target_file_name}")
    convert = os.path.join(dir_path, "bin/conv_1_2_convert")
# Get credentials.py in parent folder
    assert delegator.run(f"{convert} < {name}.raw > {target_file_name}").return_code
elif app == "conv_bw":
    import delegator
    convert = os.path.join(dir_path, "bin/crop31")
    assert delegator.run(f"{convert} < {name}.raw > {target_file_name}").return_code
else:
    shutil.copy(f"{name}.raw", target_file_name)
