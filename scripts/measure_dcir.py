#!/usr/bin/env python3

import argparse
import csv
import os
import sys
import time
from datetime import datetime

sys.path.append("../")

from battery_tester.config import load_config
from battery_tester.instruments import *

def write_csv_header(path: str) -> None:
	os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
	with open(path, "w", newline="") as f:
		writer = csv.writer(f)
		writer.writerow([
			"timestamp_iso",
			"phase",
			"elapsed_s",
			"battery_voltage_v",
			"load_voltage_v",
			"load_current_a",
			"dcir_ohm",
			"note",
		])

def append_row(
	path: str,
	phase: str,
	elapsed_s: float,
	battery_voltage_v: float,
	load_voltage_v: float,
	load_current_a: float,
	dcir_ohm: float | None,
	note: str = "",
) -> None:
	with open(path, "a", newline="") as f:
		writer = csv.writer(f)
		writer.writerow([
			datetime.now().isoformat(),
			phase,
			f"{elapsed_s:.3f}",
			f"{battery_voltage_v:.6f}",
			f"{load_voltage_v:.6f}",
			f"{load_current_a:.6f}",
			"" if dcir_ohm is None else f"{dcir_ohm:.8f}",
			note,
		])

def parse_args():
	p = argparse.ArgumentParser(
		description="Measure DCIR using a single discharge pulse."
	)
	p.add_argument("--config", default="../configs/instruments.example.yaml")
	p.add_argument("--out", required=True, help="Output CSV path")
	p.add_argument(
		"--capacity-ah",
		type=float,
		required=True,
		help="Nominal or measured cell capacity in Ah",
	)
	p.add_argument(
		"--pulse-c-rate",
		type=float,
		default=1.0,
		help="Pulse current in C-rate units, e.g. 1.0 = 1C",
	)
	p.add_argument(
		"--pulse-current-a",
		type=float,
		default=None,
		help="Override pulse current directly in amps",
	)
	p.add_argument(
		"--pulse-duration-s",
		type=float,
		default=1.0,
		help="Duration of the discharge pulse in seconds",
	)
	p.add_argument(
		"--evaluation-time-s",
		type=float,
		default=1.0,
		help="Time after pulse start at which to evaluate loaded voltage/current",
	)
	p.add_argument(
		"--pre-rest-s",
		type=float,
		default=5.0,
		help="Extra time to sit in safe mode before OCV sampling",
	)
	p.add_argument(
		"--post-rest-s",
		type=float,
		default=10.0,
		help="Recovery logging time after the pulse",
	)
	p.add_argument(
		"--sample-period-s",
		type=float,
		default=0.2,
		help="Logging period during pulse and recovery",
	)
	p.add_argument(
		"--ocv-samples",
		type=int,
		default=5,
		help="Number of OCV samples to average before the pulse",
	)
	p.add_argument(
		"--nplc",
		type=float,
		default=1.0,
		help="SDM3055 DCV NPLC setting",
	)
	p.add_argument(
		"--min-start-voltage",
		type=float,
		default=2.5,
		help="Abort if initial voltage is below this",
	)
	p.add_argument(
		"--max-start-voltage",
		type=float,
		default=4.25,
		help="Abort if initial voltage is above this",
	)
	return p.parse_args()

def measure_ocv_average(sdm: SDM3055, nplc: float, n_samples: int, dt_s: float) -> float:
	values = []
	for _ in range(n_samples):
		v = sdm.measure_voltage_dc(range_v=20, nplc=nplc)
		values.append(v)
		time.sleep(dt_s)
	return sum(values) / len(values)

def main():
	args = parse_args()
	cfg = load_config(args.config)

	pulse_current_a = (
		args.pulse_current_a
		if args.pulse_current_a is not None
		else args.pulse_c_rate * args.capacity_ah
	)

	if pulse_current_a <= 0:
		raise ValueError("Pulse current must be positive.")

	write_csv_header(args.out)

	sdm = None
	dl = None
	relay = None

	try:
		sdm = SDM3055(VisaDevice(cfg.sdm3055.resource, backend=cfg.visa_backend))
		dl = DL3021(VisaDevice(cfg.dl3021.resource, backend=cfg.visa_backend))
		relay = NoyitoRelay2(SerialDevice(cfg.relay.port, baudrate=cfg.relay.baudrate))

		print("Connected:")
		print("  SDM :", sdm.identify())
		print("  DL  :", dl.identify())

		dl.input_off()
		relay.set_mode("safe")
		time.sleep(0.5)

		print(f"Resting in safe mode for {args.pre_rest_s:.1f} s")
		time.sleep(args.pre_rest_s)

		ocv = measure_ocv_average(
			sdm=sdm,
			nplc=args.nplc,
			n_samples=args.ocv_samples,
			dt_s=args.sample_period_s,
		)

		append_row(
			args.out,
			phase="pre_ocv",
			elapsed_s=0.0,
			battery_voltage_v=ocv,
			load_voltage_v=0.0,
			load_current_a=0.0,
			dcir_ohm=None,
			note=f"ocv_avg_over_{args.ocv_samples}_samples",
		)

		print(f"OCV before pulse: {ocv:.6f} V")

		if not (args.min_start_voltage <= ocv <= args.max_start_voltage):
			raise RuntimeError(
				f"Initial OCV {ocv:.3f} V is outside allowed start window "
				f"[{args.min_start_voltage}, {args.max_start_voltage}] V."
			)

		# Program the load but do not enable yet
		dl.set_cc_current(pulse_current_a, current_range_a=6)

		# Start pulse
		relay.set_mode("discharge")
		time.sleep(0.2)
		dl.input_on()

		t0 = time.time()
		eval_v = None
		eval_i = None
		eval_t = None

		while True:
			now = time.time()
			elapsed = now - t0

			v_batt = sdm.measure_voltage_dc(range_v=20, nplc=args.nplc)
			v_load = dl.measure_voltage()
			i_load = dl.measure_current()

			append_row(
				args.out,
				phase="pulse",
				elapsed_s=elapsed,
				battery_voltage_v=v_batt,
				load_voltage_v=v_load,
				load_current_a=i_load,
				dcir_ohm=None,
			)

			print(
				f"[pulse] t={elapsed:6.3f}s  "
				f"Vbatt={v_batt:6.4f} V  "
				f"Vload={v_load:6.4f} V  "
				f"Iload={i_load:6.4f} A"
			)

			# Capture the first sample at or after the requested evaluation time
			if eval_v is None and elapsed >= args.evaluation_time_s:
				eval_v = v_batt
				eval_i = i_load
				eval_t = elapsed

			if elapsed >= args.pulse_duration_s:
				# Fallback in case evaluation_time_s > pulse_duration_s
				if eval_v is None:
					eval_v = v_batt
					eval_i = i_load
					eval_t = elapsed
				break

			time.sleep(args.sample_period_s)

		dl.input_off()
		time.sleep(0.2)
		relay.set_mode("safe")
		time.sleep(0.2)

		if eval_i is None or eval_i <= 0:
			raise RuntimeError("Pulse evaluation current was not valid.")

		dcir_ohm = (ocv - eval_v) / eval_i

		append_row(
			args.out,
			phase="dcir_result",
			elapsed_s=eval_t,
			battery_voltage_v=eval_v,
			load_voltage_v=eval_v,
			load_current_a=eval_i,
			dcir_ohm=dcir_ohm,
			note=f"ocv={ocv:.6f}",
		)

		print("")
		print("DCIR result")
		print(f"  OCV before pulse : {ocv:.6f} V")
		print(f"  Eval time        : {eval_t:.3f} s")
		print(f"  Loaded voltage   : {eval_v:.6f} V")
		print(f"  Loaded current   : {eval_i:.6f} A")
		print(f"  DCIR             : {dcir_ohm * 1000:.3f} mOhm")

		# Recovery logging
		print(f"\nLogging recovery for {args.post_rest_s:.1f} s")
		recovery_t0 = time.time()
		while True:
			elapsed = time.time() - recovery_t0
			if elapsed >= args.post_rest_s:
				break

			v_batt = sdm.measure_voltage_dc(range_v=20, nplc=args.nplc)
			append_row(
				args.out,
				phase="recovery",
				elapsed_s=elapsed,
				battery_voltage_v=v_batt,
				load_voltage_v=0.0,
				load_current_a=0.0,
				dcir_ohm=dcir_ohm,
			)

			print(f"[recovery] t={elapsed:6.3f}s  Vbatt={v_batt:6.4f} V")
			time.sleep(args.sample_period_s)

		print(f"\nCSV output: {args.out}")

	finally:
		try:
			if dl is not None:
				dl.input_off()
		except Exception:
			pass
		try:
			if relay is not None:
				relay.set_mode("safe")
		except Exception:
			pass
		try:
			if sdm is not None:
				sdm.dev.close()
		except Exception:
			pass
		try:
			if dl is not None:
				dl.dev.close()
		except Exception:
			pass
		try:
			if relay is not None:
				relay.dev.close()
		except Exception:
			pass

if __name__ == "__main__":
	try:
		main()
	except KeyboardInterrupt:
		print("\nInterrupted by user; bench returned to safe state.")
		sys.exit(1)