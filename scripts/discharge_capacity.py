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
			"load_power_w",
			"psu_voltage_v",
			"psu_current_a",
			"cap_ah",
			"cap_wh",
			"note",
		])

def append_row(
	path: str,
	phase: str,
	elapsed_s: float,
	battery_voltage_v: float,
	load_voltage_v: float,
	load_current_a: float,
	load_power_w: float,
	psu_voltage_v: float,
	psu_current_a: float,
	cap_ah: float,
	cap_wh: float,
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
			f"{load_power_w:.6f}",
			f"{psu_voltage_v:.6f}",
			f"{psu_current_a:.6f}",
			f"{cap_ah:.8f}",
			f"{cap_wh:.8f}",
			note,
		])

def parse_args():
	p = argparse.ArgumentParser(
		description="Discharge a cell at 0.5C to 3.2 V, log Ah/Wh, then recharge to ~3.75 V and rest 1 hour."
	)
	p.add_argument("--config", default="../configs/instruments.example.yaml")
	p.add_argument("--out", required=True, help="Output CSV path")
	p.add_argument(
		"--capacity-ah",
		type=float,
		required=True,
		help="Nominal cell capacity in Ah, e.g. 3.0 for a 3000 mAh cell",
	)
	p.add_argument("--psu-channel", type=int, default=1)
	p.add_argument("--cutoff-v", type=float, default=3.20)
	p.add_argument("--storage-v", type=float, default=3.75)
	p.add_argument("--sample-period-s", type=float, default=2.0)
	p.add_argument("--rest-seconds", type=float, default=3600.0)
	p.add_argument("--rest-log-period-s", type=float, default=60.0)
	p.add_argument("--nplc", type=float, default=1.0)
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
		"--storage-termination-current-a",
		type=float,
		default=None,
		help="Current taper threshold for the 3.75 V recharge. Defaults to C/20.",
	)
	p.add_argument(
		"--storage-termination-streak",
		type=int,
		default=3,
		help="Require this many consecutive taper-qualifying samples before ending storage recharge.",
	)
	p.add_argument(
		"--skip-storage-recharge",
		action="store_true",
		help="Skip recharge-to-storage phase.",
	)
	return p.parse_args()

def run_discharge_phase(
	csv_path: str,
	sdm: SDM3055,
	dl: DL3021,
	relay: NoyitoRelay2,
	discharge_current_a: float,
	cutoff_v: float,
	sample_period_s: float,
	nplc: float,
):
	cap_ah = 0.0
	cap_wh = 0.0

	dl.set_cc_current(discharge_current_a, current_range_a=6)
	relay.set_mode("discharge")
	time.sleep(0.2)
	dl.input_on()

	t0 = time.time()
	prev_t = None
	prev_i = None
	prev_v = None

	while True:
		now = time.time()
		elapsed = now - t0

		v_batt = sdm.measure_voltage_dc(range_v=20, nplc=nplc)
		i_load = dl.measure_current()
		v_load = dl.measure_voltage()
		p_load = v_batt * i_load

		if prev_t is not None:
			dt_h = (now - prev_t) / 3600.0
			# Trapezoidal integration
			i_avg = 0.5 * (prev_i + i_load)
			p_avg = 0.5 * (prev_v * prev_i + v_batt * i_load)
			cap_ah += i_avg * dt_h
			cap_wh += p_avg * dt_h

		append_row(
			csv_path,
			phase="discharge",
			elapsed_s=elapsed,
			battery_voltage_v=v_batt,
			load_voltage_v=v_load,
			load_current_a=i_load,
			load_power_w=p_load,
			psu_voltage_v=0.0,
			psu_current_a=0.0,
			cap_ah=cap_ah,
			cap_wh=cap_wh,
		)

		print(
			f"[discharge] t={elapsed:8.1f}s  "
			f"Vbatt={v_batt:6.4f} V  "
			f"Iload={i_load:6.4f} A  "
			f"Cap={cap_ah:7.4f} Ah  "
			f"Energy={cap_wh:7.4f} Wh"
		)

		if v_batt <= cutoff_v:
			break

		prev_t = now
		prev_i = i_load
		prev_v = v_batt
		time.sleep(sample_period_s)

	dl.input_off()
	time.sleep(0.2)
	relay.set_mode("safe")
	time.sleep(0.5)

	v_post = sdm.measure_voltage_dc(range_v=20, nplc=nplc)
	append_row(
		csv_path,
		phase="discharge_end",
		elapsed_s=time.time() - t0,
		battery_voltage_v=v_post,
		load_voltage_v=0.0,
		load_current_a=0.0,
		load_power_w=0.0,
		psu_voltage_v=0.0,
		psu_current_a=0.0,
		cap_ah=cap_ah,
		cap_wh=cap_wh,
		note="cutoff_reached",
	)

	return {
		"cap_ah": cap_ah,
		"cap_wh": cap_wh,
		"post_discharge_v": v_post,
	}

def run_storage_recharge_phase(
	csv_path: str,
	sdm: SDM3055,
	psu: SPD3303X,
	relay: NoyitoRelay2,
	channel: int,
	charge_current_a: float,
	target_v: float,
	taper_current_a: float,
	sample_period_s: float,
	nplc: float,
	termination_streak: int,
):
	psu.set_track_mode("independent")
	psu.set_voltage(target_v, channel=channel)
	psu.set_current(charge_current_a, channel=channel)

	relay.set_mode("charge")
	time.sleep(0.2)
	psu.output_on(channel)

	t0 = time.time()
	streak = 0

	while True:
		elapsed = time.time() - t0
		v_batt = sdm.measure_voltage_dc(range_v=20, nplc=nplc)
		v_psu = psu.measure_voltage(channel)
		i_psu = psu.measure_current(channel)

		append_row(
			csv_path,
			phase="storage_recharge",
			elapsed_s=elapsed,
			battery_voltage_v=v_batt,
			load_voltage_v=0.0,
			load_current_a=0.0,
			load_power_w=0.0,
			psu_voltage_v=v_psu,
			psu_current_a=i_psu,
			cap_ah=0.0,
			cap_wh=0.0,
		)

		print(
			f"[storage]   t={elapsed:8.1f}s  "
			f"Vbatt={v_batt:6.4f} V  "
			f"Vpsu={v_psu:6.4f} V  "
			f"Ipsu={i_psu:6.4f} A"
		)

		close_to_target = v_batt >= (target_v - 0.02)
		below_taper = i_psu <= taper_current_a

		if close_to_target and below_taper:
			streak += 1
		else:
			streak = 0

		if streak >= termination_streak:
			break

		time.sleep(sample_period_s)

	psu.output_off(channel)
	time.sleep(0.2)
	relay.set_mode("safe")
	time.sleep(0.5)

	v_post = sdm.measure_voltage_dc(range_v=20, nplc=nplc)
	append_row(
		csv_path,
		phase="storage_recharge_end",
		elapsed_s=time.time() - t0,
		battery_voltage_v=v_post,
		load_voltage_v=0.0,
		load_current_a=0.0,
		load_power_w=0.0,
		psu_voltage_v=0.0,
		psu_current_a=0.0,
		cap_ah=0.0,
		cap_wh=0.0,
		note="storage_target_reached",
	)

	return {"post_storage_recharge_v": v_post}

def run_rest_phase(
	csv_path: str,
	sdm: SDM3055,
	rest_seconds: float,
	rest_log_period_s: float,
	nplc: float,
):
	t0 = time.time()
	next_log = 0.0

	while True:
		elapsed = time.time() - t0
		if elapsed >= rest_seconds:
			break

		if elapsed >= next_log:
			v_batt = sdm.measure_voltage_dc(range_v=20, nplc=nplc)
			append_row(
				csv_path,
				phase="rest",
				elapsed_s=elapsed,
				battery_voltage_v=v_batt,
				load_voltage_v=0.0,
				load_current_a=0.0,
				load_power_w=0.0,
				psu_voltage_v=0.0,
				psu_current_a=0.0,
				cap_ah=0.0,
				cap_wh=0.0,
			)
			print(f"[rest]      t={elapsed:8.1f}s  Vbatt={v_batt:6.4f} V")
			next_log += rest_log_period_s

		time.sleep(1.0)

	v_final = sdm.measure_voltage_dc(range_v=20, nplc=nplc)
	append_row(
		csv_path,
		phase="rest_end",
		elapsed_s=rest_seconds,
		battery_voltage_v=v_final,
		load_voltage_v=0.0,
		load_current_a=0.0,
		load_power_w=0.0,
		psu_voltage_v=0.0,
		psu_current_a=0.0,
		cap_ah=0.0,
		cap_wh=0.0,
		note="rest_complete",
	)
	return {"rested_voltage_v": v_final}

def main():
	args = parse_args()

	cfg = load_config(args.config)

	discharge_current_a = 0.5 * args.capacity_ah # C/2
	storage_charge_current_a = 0.5 * args.capacity_ah # C/2
	taper_current_a = (
		args.storage_termination_current_a
		if args.storage_termination_current_a is not None
		else (args.capacity_ah / 20.0)
	)

	sdm = None
	psu = None
	dl = None
	relay = None

	write_csv_header(args.out)

	try:
		sdm = SDM3055(VisaDevice(cfg.sdm3055.resource, backend=cfg.visa_backend))
		psu = SPD3303X(VisaDevice(cfg.spd3303x.resource, backend=cfg.visa_backend))
		dl = DL3021(VisaDevice(cfg.dl3021.resource, backend=cfg.visa_backend))
		relay = NoyitoRelay2(SerialDevice(cfg.relay.port, baudrate=cfg.relay.baudrate))

		print("Connected:")
		print("  SDM :", sdm.identify())
		print("  PSU :", psu.identify())
		print("  DL  :", dl.identify())

		dl.input_off()
		psu.output_off(1)
		relay.set_mode("safe")
		time.sleep(0.5)

		v0 = sdm.measure_voltage_dc(range_v=20, nplc=args.nplc)
		append_row(
			args.out,
			phase="precheck",
			elapsed_s=0.0,
			battery_voltage_v=v0,
			load_voltage_v=0.0,
			load_current_a=0.0,
			load_power_w=0.0,
			psu_voltage_v=0.0,
			psu_current_a=0.0,
			cap_ah=0.0,
			cap_wh=0.0,
			note="initial_ocv",
		)
		print(f"Initial battery voltage: {v0:.6f} V")

		if not (args.min_start_voltage <= v0 <= args.max_start_voltage):
			raise RuntimeError(
				f"Initial battery voltage {v0:.3f} V is outside allowed start window "
				f"[{args.min_start_voltage}, {args.max_start_voltage}] V."
			)

		print(
			f"Starting discharge at {discharge_current_a:.3f} A (0.5C) "
			f"to cutoff {args.cutoff_v:.3f} V"
		)
		discharge_summary = run_discharge_phase(
			csv_path=args.out,
			sdm=sdm,
			dl=dl,
			relay=relay,
			discharge_current_a=discharge_current_a,
			cutoff_v=args.cutoff_v,
			sample_period_s=args.sample_period_s,
			nplc=args.nplc,
		)

		print(
			f"Discharge complete: {discharge_summary['cap_ah']:.5f} Ah, "
			f"{discharge_summary['cap_wh']:.5f} Wh"
		)

		if not args.skip_storage_recharge:
			print(
				f"Recharging to ~{args.storage_v:.3f} V at up to "
				f"{storage_charge_current_a:.3f} A, terminate at "
				f"{taper_current_a:.3f} A"
			)
			run_storage_recharge_phase(
				csv_path=args.out,
				sdm=sdm,
				psu=psu,
				relay=relay,
				channel=args.psu_channel,
				charge_current_a=storage_charge_current_a,
				target_v=args.storage_v,
				taper_current_a=taper_current_a,
				sample_period_s=args.sample_period_s,
				nplc=args.nplc,
				termination_streak=args.storage_termination_streak,
			)

		print(f"Resting for {args.rest_seconds:.0f} s")
		rest_summary = run_rest_phase(
			csv_path=args.out,
			sdm=sdm,
			rest_seconds=args.rest_seconds,
			rest_log_period_s=args.rest_log_period_s,
			nplc=args.nplc,
		)

		print("Done.")
		print(f"Capacity   : {discharge_summary['cap_ah']:.5f} Ah")
		print(f"Energy     : {discharge_summary['cap_wh']:.5f} Wh")
		print(f"Rested V   : {rest_summary['rested_voltage_v']:.6f} V")
		print(f"CSV output : {args.out}")

	finally:
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