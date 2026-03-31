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
			"psu_voltage_v",
			"psu_current_a",
			"target_voltage_v",
			"target_current_a",
			"taper_current_a",
			"note",
		])

def append_row(
	path: str,
	phase: str,
	elapsed_s: float,
	battery_voltage_v: float,
	psu_voltage_v: float,
	psu_current_a: float,
	target_voltage_v: float,
	target_current_a: float,
	taper_current_a: float,
	note: str = "",
) -> None:
	with open(path, "a", newline="") as f:
		writer = csv.writer(f)
		writer.writerow([
			datetime.now().isoformat(),
			phase,
			f"{elapsed_s:.3f}",
			f"{battery_voltage_v:.6f}",
			f"{psu_voltage_v:.6f}",
			f"{psu_current_a:.6f}",
			f"{target_voltage_v:.6f}",
			f"{target_current_a:.6f}",
			f"{taper_current_a:.6f}",
			note,
		])

def parse_args():
	p = argparse.ArgumentParser(
		description="Standard 18650 CC/CV charge: 4.2 V at 0.5C, terminate at C/20, then rest."
	)
	p.add_argument("--config", default="../configs/instruments.example.yaml")
	p.add_argument("--out", required=True, help="Output CSV path")
	p.add_argument(
		"--capacity-ah",
		type=float,
		required=True,
		help="Nominal cell capacity in Ah, e.g. 3.0 for a 3000 mAh cell",
	)
	p.add_argument("--channel", type=int, default=1, help="PSU channel to use (default: 1)")
	p.add_argument("--target-voltage", type=float, default=4.20)
	p.add_argument(
		"--sample-period-s",
		type=float,
		default=2.0,
		help="Logging period during charge phase",
	)
	p.add_argument(
		"--rest-seconds",
		type=float,
		default=3600.0,
		help="Post-charge rest time in seconds (default: 3600 = 1 hour)",
	)
	p.add_argument(
		"--rest-log-period-s",
		type=float,
		default=60.0,
		help="Logging period during the rest phase",
	)
	p.add_argument(
		"--min-charge-seconds",
		type=float,
		default=300.0,
		help="Minimum charge time before allowing taper termination",
	)
	p.add_argument(
		"--cv-close-margin-v",
		type=float,
		default=0.05,
		help="Require battery voltage to be within this margin of target before taper termination",
	)
	p.add_argument(
		"--termination-streak",
		type=int,
		default=3,
		help="Require this many consecutive taper-qualifying samples before stopping",
	)
	p.add_argument(
		"--min-start-voltage",
		type=float,
		default=2.5,
		help="Abort if initial battery voltage is below this",
	)
	p.add_argument(
		"--max-start-voltage",
		type=float,
		default=4.25,
		help="Abort if initial battery voltage is above this",
	)
	p.add_argument(
		"--nplc",
		type=float,
		default=1.0,
		help="SDM3055 DCV NPLC during logging",
	)
	return p.parse_args()

def main():
	args = parse_args()

	cfg = load_config(args.config)

	charge_current_a = 0.5 * args.capacity_ah # C/2
	taper_current_a = args.capacity_ah / 20.0 # C/20

	sdm = None
	psu = None
	dl = None
	relay = None

	write_csv_header(args.out)

	try:
		# Connect instruments
		sdm = SDM3055(VisaDevice(cfg.sdm3055.resource, backend=cfg.visa_backend))
		psu = SPD3303X(VisaDevice(cfg.spd3303x.resource, backend=cfg.visa_backend))
		dl = DL3021(VisaDevice(cfg.dl3021.resource, backend=cfg.visa_backend))
		relay = NoyitoRelay2(SerialDevice(cfg.relay.port, baudrate=cfg.relay.baudrate))

		print("Connected:")
		print("  SDM :", sdm.identify())
		print("  PSU :", psu.identify())
		print("  DL  :", dl.identify())

		# startup state
		dl.input_off()
		psu.output_off(1)
		relay.set_mode("safe")
		time.sleep(0.5)

		# Initial OCV check
		v0 = sdm.measure_voltage_dc(range_v=20, nplc=args.nplc)
		append_row(
			args.out,
			phase="precheck",
			elapsed_s=0.0,
			battery_voltage_v=v0,
			psu_voltage_v=0.0,
			psu_current_a=0.0,
			target_voltage_v=args.target_voltage,
			target_current_a=charge_current_a,
			taper_current_a=taper_current_a,
			note="initial_ocv",
		)
		print(f"Initial battery voltage: {v0:.6f} V")

		if not (args.min_start_voltage <= v0 <= args.max_start_voltage):
			raise RuntimeError(
				f"Initial battery voltage {v0:.3f} V is outside the allowed start window "
				f"[{args.min_start_voltage}, {args.max_start_voltage}] V."
			)

		# Program PSU
		psu.set_track_mode("independent")
		psu.set_voltage(args.target_voltage, channel=args.channel)
		psu.set_current(charge_current_a, channel=args.channel)

		# Route to charge path, then enable PSU
		relay.set_mode("charge")
		time.sleep(0.2)
		psu.output_on(args.channel)

		print(
			f"Charging started: target={args.target_voltage:.3f} V, "
			f"I_limit={charge_current_a:.3f} A, terminate at <= {taper_current_a:.3f} A"
		)

		t0 = time.time()
		streak = 0

		# Charge phase
		while True:
			elapsed = time.time() - t0

			v_batt = sdm.measure_voltage_dc(range_v=20, nplc=args.nplc)
			v_psu = psu.measure_voltage(args.channel)
			i_psu = psu.measure_current(args.channel)

			append_row(
				args.out,
				phase="charge",
				elapsed_s=elapsed,
				battery_voltage_v=v_batt,
				psu_voltage_v=v_psu,
				psu_current_a=i_psu,
				target_voltage_v=args.target_voltage,
				target_current_a=charge_current_a,
				taper_current_a=taper_current_a,
			)

			print(
				f"[charge] t={elapsed:8.1f}s  "
				f"Vbatt={v_batt:6.4f} V  "
				f"Vpsu={v_psu:6.4f} V  "
				f"Ipsu={i_psu:6.4f} A"
			)

			close_to_cv = v_batt >= (args.target_voltage - args.cv_close_margin_v)
			below_taper = i_psu <= taper_current_a
			long_enough = elapsed >= args.min_charge_seconds

			if long_enough and close_to_cv and below_taper:
				streak += 1
			else:
				streak = 0

			if streak >= args.termination_streak:
				print("Charge termination condition met.")
				break

			time.sleep(args.sample_period_s)

		# Stop charging and go safe
		psu.output_off(args.channel)
		time.sleep(0.2)
		relay.set_mode("safe")
		time.sleep(0.5)

		v_end = sdm.measure_voltage_dc(range_v=20, nplc=args.nplc)
		append_row(
			args.out,
			phase="charge_end",
			elapsed_s=time.time() - t0,
			battery_voltage_v=v_end,
			psu_voltage_v=0.0,
			psu_current_a=0.0,
			target_voltage_v=args.target_voltage,
			target_current_a=charge_current_a,
			taper_current_a=taper_current_a,
			note="charge_terminated",
		)
		print(f"Charge ended. Immediate post-charge voltage: {v_end:.6f} V")

		# Rest phase
		print(f"Resting for {args.rest_seconds:.0f} s ...")
		rest_t0 = time.time()
		next_log = 0.0

		while True:
			rest_elapsed = time.time() - rest_t0
			if rest_elapsed >= args.rest_seconds:
				break

			if rest_elapsed >= next_log:
				v_rest = sdm.measure_voltage_dc(range_v=20, nplc=args.nplc)
				append_row(
					args.out,
					phase="rest",
					elapsed_s=rest_elapsed,
					battery_voltage_v=v_rest,
					psu_voltage_v=0.0,
					psu_current_a=0.0,
					target_voltage_v=args.target_voltage,
					target_current_a=charge_current_a,
					taper_current_a=taper_current_a,
				)
				print(f"[rest]   t={rest_elapsed:8.1f}s  Vbatt={v_rest:6.4f} V")
				next_log += args.rest_log_period_s

			time.sleep(1.0)

		v_final = sdm.measure_voltage_dc(range_v=20, nplc=args.nplc)
		append_row(
			args.out,
			phase="rest_end",
			elapsed_s=args.rest_seconds,
			battery_voltage_v=v_final,
			psu_voltage_v=0.0,
			psu_current_a=0.0,
			target_voltage_v=args.target_voltage,
			target_current_a=charge_current_a,
			taper_current_a=taper_current_a,
			note="rest_complete",
		)

		print("Done.")
		print(f"Final rested voltage: {v_final:.6f} V")
		print(f"CSV written to: {args.out}")
	except Exception as ex:
		print(ex)

	finally:
		# Best-effort safe shutdown
		try:
			if dl is not None:
				dl.input_off()
		except Exception:
			pass
		try:
			if psu is not None:
				psu.output_off(1)
		except Exception:
			pass
		try:
			if relay is not None:
				relay.set_mode("safe")
		except Exception:
			pass

		# Close transports
		try:
			if sdm is not None:
				sdm.dev.close()
		except Exception:
			pass
		try:
			if psu is not None:
				psu.dev.close()
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