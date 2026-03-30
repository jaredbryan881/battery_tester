# Battery Test Suite

This is a collection of scripts for testing and screening 18650 lithium-ion cells. The goal is to document how to connect to a set of standard lab instruments, route a cell between charge and discharge modes, log data during testing, and compute a useful set of battery metrics for cell selection and pack assembly.

## Intended Measurements and Outputs

The main quantities I want to estimate from this test suite include:

- open-circuit voltage
- discharge capacity
- charge capacity
- apparent DC internal resistance from current pulses
- voltage sag under load
- cycle-to-cycle repeatability
- simple batch statistics for groups of cells

For representative cells, I may later expand the workflow to include more involved tests such as:

- differential capacity style analyses
- longer-form charge/discharge cycling

## Hardware Used

This repository is currently built around the following bench instruments:

- Siglent SDM3055 digital multimeter
- Siglent SPD3303X-E DC power supply
- Rigol DL3021 DC electronic load
- [NOYITO 5V 2-channel micro-USB relay module](https://www.amazon.com/dp/B081RM7PMY?ref=ppx_yo2ov_dt_b_fed_asin_title)

## Test Fixture

The physical battery interface is a [4-wire battery fixture for 18650 cells](https://www.aliexpress.us/item/2251832638685411.html?spm=a2g0o.order_list.order_list_main.5.5abb18028e2MdD&gatewayAdapt=glo2usa).
