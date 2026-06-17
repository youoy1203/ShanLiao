import torch
print("CUDA Available:", torch.cuda.is_available())
if torch.cuda.is_available():
    print("Device Name:", torch.cuda.get_device_name(0))
    print("CUDA Arch List:", torch.cuda.get_arch_list())
else:
    print("WARNING: CUDA is NOT available. PyTorch cannot use GPU!")
