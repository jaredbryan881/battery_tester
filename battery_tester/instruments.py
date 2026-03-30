import pyvisa
import serial

class VisaDevice:
	# Devices controlled via the Virtual Instrument Software Architecture (VISA) API
	def __init__(self, resource_name: str, backend: str = "@py", timeout_ms: int = 5000):
		self.rm = pyvisa.ResourceManager(backend)
		self.inst = self.rm.open_resource(resource_name)
		self.inst.timeout = timeout_ms
		self.inst.write_termination = "\n"
		self.inst.read_termination = "\n"

	def write(self, cmd: str) -> None:
		self.inst.write(cmd)

	def query(self, cmd: str) -> str:
		return self.inst.query(cmd).strip()

	def close(self) -> None:
		try:
			self.inst.close()
		finally:
			self.rm.close()

class SerialDevice:
	# Devices controlled over a serial connection
	def __init__(self, port: str, baudrate: int = 9600, timeout: float = 1.0):
		self.ser = serial.Serial(
			port=port,
			baudrate=baudrate,
			bytesize=8,
			parity="N",
			stopbits=1,
			timeout=timeout,
		)

	def write_bytes(self, data: bytes) -> None:
		self.ser.write(data)
		self.ser.flush()

	def read_all(self) -> bytes:
		return self.ser.read_all()

	def reset_input_buffer(self) -> None:
		self.ser.reset_input_buffer()

	def close(self) -> None:
		self.ser.close()
		
class SDM3055:
	# Siglent 5.5 digit DMM
	def __init__(self, dev: VisaDevice):
		self.dev = dev

	def identify(self) -> str:
		# Identify the instrument
		return self.dev.query("*IDN?")

	def reset(self) -> None:
		# Reset the instrument
		self.dev.write(f"*RST")

	def configure_voltage_dc(self, range_v: float | str = "AUTO", nplc: float = 10) -> None:
		self.dev.write(f"CONF:VOLT:DC {range_v}")
		self.dev.write(f"VOLT:DC:NPLC {nplc}")

	def measure_voltage_dc(self, range_v: float | str = 20, nplc: float = 10) -> float:
		self.configure_voltage_dc(range_v=range_v, nplc=nplc)
		return float(self.dev.query("READ?"))

	def configure_fres(self, range_ohm: float | str = 200) -> None:
		self.dev.write(f"CONF:FRES {range_ohm}")

	def measure_fres(self, range_ohm: float | str = 200) -> float:
		self.configure_fres(range_ohm=range_ohm)
		return float(self.dev.query("READ?"))

	def set_sample_count(self, count: int) -> None:
		self.dev.write(f"SAMP:COUN {count}")

	def set_trigger_count(self, count: int) -> None:
		self.dev.write(f"TRIG:COUN {count}")

	def set_trigger_source_immediate(self) -> None:
		self.dev.write("TRIG:SOUR IMM")

	def read(self) -> str:
		# Trigger the measurement sequence and return readings
		return self.dev.query("READ?")

	def fetch(self) -> str:
		# Read back stored measurements from reading memory
		return self.dev.query("FETCh?")

class DL3021:
	# Rigol DC electronic load
	def __init__(self, dev: VisaDevice):
		self.dev = dev

	def identify(self) -> str:
		# Identify the instrument
		return self.dev.query("*IDN?")

	def reset(self) -> None:
		# Reset the instrument
		self.dev.write(f"*RST")

	def input_on(self) -> None:
		# Enable load input so the instrument begins sinking power
		self.dev.write(":SOUR:INP:STAT 1")

	def input_off(self) -> None:
		# Disable load input so the instrument becomes high Z
		self.dev.write(":SOUR:INP:STAT 0")

	def input_state(self) -> bool:
		# True if input is on
		return bool(int(self.dev.query(":SOUR:INP:STAT?")))

	##################
	# MODE SELECTION # 
	##################
	def set_fixed_mode(self) -> None:
		# Put the load in fixed static mode (rather than list, wave, or battery)
		self.dev.write(":SOUR:FUNC:MODE FIX")

	def mode(self) -> str:
		# Check the mode
		return self.dev.query(":SOUR:FUNC?")

	def set_mode_cc(self) -> None:
		# Constant-current mode
		self.set_fixed_mode()
		self.dev.write(":SOUR:FUNC CURR")

	def set_mode_cv(self) -> None:
		# Constant-voltage mode
		self.set_fixed_mode()
		self.dev.write(":SOUR:FUNC VOLT")

	def set_mode_cr(self) -> None:
		# Constant-resistance mode
		self.set_fixed_mode()
		self.dev.write(":SOUR:FUNC RES")

	def set_mode_cp(self) -> None:
		# Constant-power mode
		self.set_fixed_mode()
		self.dev.write(":SOUR:FUNC POW")

	####################
	# CC MODE COMMANDS # 
	####################
	def set_cc_current(self, current_a: float, current_range_a: float | None = None) -> None:
		self.set_mode_cc()
		# program the sink current [A]
		if current_range_a is not None:
			self.dev.write(f":SOUR:CURR:RANG {current_range_a}")
		self.dev.write(f":SOUR:CURR:LEV:IMM {current_a}")

	def get_cc_current(self) -> float:
		# Return the CC setpoint [A]
		return float(self.dev.query(":SOUR:CURR:LEV:IMM?"))

	def set_cc_voltage_limit(self, volts: float) -> None:
		self.dev.write(f":SOUR:CURR:VLIM {volts}")

	def get_cc_voltage_limit(self) -> float:
		return float(self.dev.query(":SOUR:CURR:VLIM?"))

	def set_cc_current_limit(self, amps: float) -> None:
		self.dev.write(f":SOUR:CURR:ILIM {amps}")

	def get_cc_current_limit(self) -> float:
		return float(self.dev.query(":SOUR:CURR:ILIM?"))

	####################
	# CV MODE COMMANDS # 
	####################
	def set_cv_voltage(self, volts: float, voltage_range_v: float | None = None) -> None:
		self.set_mode_cv()
		# program target voltage [V]
		if voltage_range_v is not None:
			self.dev.write(f":SOUR:VOLT:RANG {voltage_range_v}")
		self.dev.write(f":SOUR:VOLT:LEV:IMM {volts}")

	def get_cv_voltage(self) -> float:
		return float(self.dev.query(":SOUR:VOLT:LEV:IMM?"))

	def set_cv_voltage_limit(self, volts: float) -> None:
		self.dev.write(f":SOUR:VOLT:VLIM {volts}")

	def get_cv_voltage_limit(self) -> float:
		return float(self.dev.query(":SOUR:VOLT:VLIM?"))

	def set_cv_current_limit(self, amps: float) -> None:
		self.dev.write(f":SOUR:VOLT:ILIM {amps}")

	def get_cv_current_limit(self) -> float:
		return float(self.dev.query(":SOUR:VOLT:ILIM?"))

	####################
	# CR MODE COMMANDS # 
	####################
	def set_cr_resistance(self, ohms: float, resistance_range_ohm: float | None = None) -> None:
		self.set_mode_cr()
		# program target resistance [Ohms]
		if resistance_range_ohm is not None:
			self.dev.write(f":SOUR:RES:RANG {resistance_range_ohm}")
		self.dev.write(f":SOUR:RES:LEV:IMM {ohms}")

	def get_cr_resistance(self) -> float:
		return float(self.dev.query(":SOUR:RES:LEV:IMM?"))

	def set_cr_voltage_limit(self, volts: float) -> None:
		self.dev.write(f":SOUR:RES:VLIM {volts}")

	def get_cr_voltage_limit(self) -> float:
		return float(self.dev.query(":SOUR:RES:VLIM?"))

	def set_cr_current_limit(self, amps: float) -> None:
		self.dev.write(f":SOUR:RES:ILIM {amps}")

	def get_cr_current_limit(self) -> float:
		return float(self.dev.query(":SOUR:RES:ILIM?"))

	####################
	# CP MODE COMMANDS # 
	####################
	def set_cp_power(self, watts: float) -> None:
		self.set_mode_cp()
		# program target power [W]
		self.dev.write(f":SOUR:POW:LEV:IMM {watts}")

	def get_cp_power(self) -> float:
		return float(self.dev.query(":SOUR:POW:LEV:IMM?"))

	def set_cp_voltage_limit(self, volts: float) -> None:
		self.dev.write(f":SOUR:POW:VLIM {volts}")

	def get_cp_voltage_limit(self) -> float:
		return float(self.dev.query(":SOUR:POW:VLIM?"))

	def set_cp_current_limit(self, amps: float) -> None:
		self.dev.write(f":SOUR:POW:ILIM {amps}")

	def get_cp_current_limit(self) -> float:
		return float(self.dev.query(":SOUR:POW:ILIM?"))

	################
	# MEASUREMENTS # 
	################
	def measure_voltage(self) -> float:
		# Return terminal voltage [V]
		return float(self.dev.query(":MEASure:VOLTage?"))

	def measure_current(self) -> float:
		# Return sink current [A]
		return float(self.dev.query(":MEASure:CURRent?"))

	def measure_resistance(self) -> float:
		# Return effective resistance [Ohms]
		return float(self.dev.query(":MEASure:RESistance?"))

	def measure_power(self) -> float:
		# Return power absorption [W]
		return float(self.dev.query(":MEASure:POWer?"))

	def measure_capacity_ah(self) -> float:
		# Return accumulated discharged capacity [Ah]
		return float(self.dev.query(":MEASure:CAPability?"))

	def measure_energy_wh(self) -> float:
		# Return accumulated discharged energy [Wh]
		return float(self.dev.query(":MEASure:WATThours?"))

	def measure_discharge_time_s(self) -> float:
		# Return elapsed discharge time [s]
		return float(self.dev.query(":MEASure:DISChargingTime?"))

class SPD3303X:
	# Siglent DC power supply
	def __init__(self, dev: VisaDevice, channel: int = 1):
		self.dev = dev
		self.channel = channel
		self.select_channel(channel)

	@staticmethod
	def _validate_programmable_channel(channel: int) -> str:
		# guard against attempts to program channel 3
		if channel not in (1, 2):
			raise ValueError("Programmable channel must be 1 or 2.")
		return f"CH{channel}"

	@staticmethod
	def _validate_output_channel(channel: int) -> str:
		# make sure this is a real channel
		if channel not in (1, 2, 3):
			raise ValueError("Output channel must be 1, 2, or 3.")
		return f"CH{channel}"

	def identify(self) -> str:
		return self.dev.query("*IDN?")

	def reset(self) -> None:
		# Reset the instrument
		self.dev.write(f"*RST")

	def save(self, slot: int) -> None:
		# Save the current instrument state to memory
		if slot not in (1, 2, 3, 4, 5):
			raise ValueError("Save slot must be 1-5.")
		self.dev.write(f"*SAV {slot}")

	def recall(self, slot: int) -> None:
		# Recall a saved instrument state
		if slot not in (1, 2, 3, 4, 5):
			raise ValueError("Recall slot must be 1-5.")
		self.dev.write(f"*RCL {slot}")

	##################
	# CHANNEL SELECT #
	##################
	def select_channel(self, channel: int) -> None:
		# Select CH1 or CH2 as the current channel
		ch = self._validate_programmable_channel(channel)
		self.dev.write(f"INSTrument {ch}")
		self.channel = channel

	def get_selected_channel(self) -> str:
		# Return the currently selected channel
		return self.dev.query("INSTrument?")

	##########
	# ON/OFF #
	##########
	def output_on(self, channel: int) -> None:
		ch = self._validate_output_channel(channel)
		self.dev.write(f"OUTPut {ch},ON")

	def output_off(self, channel: int) -> None:
		ch = self._validate_output_channel(channel)
		self.dev.write(f"OUTPut {ch},OFF")

	def all_outputs_off(self) -> None:
		self.output_off(1)
		self.output_off(2)
		self.output_off(3)

	#############
	# SETPOINTS #
	#############
	def set_voltage(self, volts: float, channel: int | None = None) -> None:
		ch = self._validate_programmable_channel(channel or self.channel)
		self.dev.write(f"{ch}:VOLTage {volts}")

	def get_voltage(self, channel: int | None = None) -> float:
		ch = self._validate_programmable_channel(channel or self.channel)
		return float(self.dev.query(f"{ch}:VOLTage?"))

	def set_current(self, amps: float, channel: int | None = None) -> None:
		ch = self._validate_programmable_channel(channel or self.channel)
		self.dev.write(f"{ch}:CURRent {amps}")

	def get_current(self, channel: int | None = None) -> float:
		ch = self._validate_programmable_channel(channel or self.channel)
		return float(self.dev.query(f"{ch}:CURRent?"))

	##############
	# TRACK MODE #
	##############
	def set_track_mode(self, mode: str) -> None:
		# Set CH1/CH2 operating relationship.
		mapping = {
			"independent": 0,
			"series": 1,
			"parallel": 2,
		}
		if mode not in mapping:
			raise ValueError("mode must be 'independent', 'series', or 'parallel'")
		self.dev.write(f"OUTPut:TRACK {mapping[mode]}")

	################
	# MEASUREMENTS #
	################
	def measure_voltage(self, channel: int | None = None) -> float:
		ch = self._validate_programmable_channel(channel or self.channel)
		return float(self.dev.query(f"MEASure:VOLTage? {ch}"))

	def measure_current(self, channel: int | None = None) -> float:
		ch = self._validate_programmable_channel(channel or self.channel)
		return float(self.dev.query(f"MEASure:CURRent? {ch}"))

	def measure_power(self, channel: int | None = None) -> float:
		ch = self._validate_programmable_channel(channel or self.channel)
		return float(self.dev.query(f"MEASure:POWEr? {ch}"))

class NoyitoRelay2:
	# Noyito 2-channel USB relay
	def __init__(self, dev: SerialDevice):
		self.dev = dev
		self.ch1 = False
		self.ch2 = False

	def initialize(self) -> None:
		self.all_off()

	def _send_hex(self, s: str) -> None:
		self.dev.write_bytes(bytes.fromhex(s))

	def relay_on(self, channel: int) -> None:
		if channel == 1:
			self._send_hex("A0 01 01 A2")
			self.ch1 = True
		elif channel == 2:
			self._send_hex("A0 02 01 A3")
			self.ch2 = True
		else:
			raise ValueError("channel must be 1 or 2")

	def relay_off(self, channel: int) -> None:
		if channel == 1:
			self._send_hex("A0 01 00 A1")
			self.ch1 = False
		elif channel == 2:
			self._send_hex("A0 02 00 A2")
			self.ch2 = False
		else:
			raise ValueError("channel must be 1 or 2")

	def all_off(self) -> None:
		self.relay_off(1)
		time.sleep(0.05)
		self.relay_off(2)
		time.sleep(0.05)

	def query_raw(self) -> str:
		self.dev.reset_input_buffer()
		self.dev.write_bytes(bytes.fromhex("FF"))
		time.sleep(0.1)
		return self.dev.read_all().decode(errors="replace")

	def set_state(self, ch1: bool, ch2: bool) -> None:
		if ch1 and ch2:
			raise ValueError("Forbidden relay state: both relays cannot be ON.")
		
		# Already in the correct state
		if self.ch1 == ch1 and self.ch2 == ch2:
			return

		# Break-before-make
		self.all_off()

		if ch1:
			self.relay_on(1)
			time.sleep(0.05)
		elif ch2:
			self.relay_on(2)
			time.sleep(0.05)

	def set_mode(self, mode: str) -> None:
		# Basically just another line of defense against self.set_state(True, True)
		if mode == "safe":
			self.set_state(False, False)
		elif mode == "charge":
			self.set_state(True, False)
		elif mode == "discharge":
			self.set_state(False, True)
		else:
			raise ValueError(f"Unknown relay mode: {mode}")