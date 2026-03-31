import sys
sys.path.append("../")
from battery_tester.config import load_config
from battery_tester.instruments import VisaDevice, SDM3055

cfg = load_config("../configs/instruments.example.yaml")

dmm = SDM3055(VisaDevice(cfg.sdm3055.resource, cfg.visa_backend, cfg.sdm3055.timeout_ms))

try:
	print("IDN:", dmm.identify())
	v = dmm.measure_voltage_dc(range_v=20, nplc=10)
	print(f"OCV = {v:.6f} V")
finally:
	dmm.dev.close()