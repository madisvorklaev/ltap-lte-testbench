# ELMO LTE Drive Test Report

Session: `drive-20260811-213442-seedri-smarten-seedri`
State: COMPLETE
Started UTC: 2026-08-11T18:34:42+00:00
Completed UTC: 2026-08-11T19:03:32+00:00
Profile: AUTO_DUAL_6M
Traffic: UDP upload, 6 Mbit/s per LTE path, rolling 60 s epochs
Location data: not present

## Overview

Collected 27 paired epochs. GPS produced 0 valid fixes. This quick report is generated from per-epoch summaries after STOP; it is good for coarse comparison but not a full sub-second synchronized analysis.

## Path Summary

| Path | OK epochs | Avg Mbps | Avg UDP loss % | Max UDP loss % | Avg ping p95 ms | Max ping p95 ms | Normal-good epochs | Strict-good epochs |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| lte1 | 26/27 | 5.78 | 3.21 | 38.90 | 1007.71 | 5392.00 | 7 | 0 |
| lte2 | 26/27 | 5.96 | 0.49 | 7.85 | 215.01 | 2248.00 | 20 | 16 |

## Bands Seen

LTE1 primary: B1@15Mhz earfcn: 523 phy-cellid: 207, B1@15Mhz earfcn: 523 phy-cellid: 208, B1@15Mhz earfcn: 523 phy-cellid: 276, B1@15Mhz earfcn: 523 phy-cellid: 277, B1@15Mhz earfcn: 523 phy-cellid: 278, B1@15Mhz earfcn: 523 phy-cellid: 306, B1@15Mhz earfcn: 523 phy-cellid: 324, B1@15Mhz earfcn: 523 phy-cellid: 439, B1@15Mhz earfcn: 523 phy-cellid: 446, B1@15Mhz earfcn: 523 phy-cellid: 69, B1@15Mhz earfcn: 523 phy-cellid: 70, B1@15Mhz earfcn: 523 phy-cellid: 71, B20@10Mhz earfcn: 6200 phy-cellid: 278, B20@10Mhz earfcn: 6200 phy-cellid: 439, B20@10Mhz earfcn: 6200 phy-cellid: 69, B20@10Mhz earfcn: 6200 phy-cellid: 7, B20@10Mhz earfcn: 6200 phy-cellid: 71, B38@20Mhz earfcn: 38098 phy-cellid: 3, B3@15Mhz earfcn: 1875 phy-cellid: 276, B3@15Mhz earfcn: 1875 phy-cellid: 278, B3@15Mhz earfcn: 1875 phy-cellid: 298, B3@15Mhz earfcn: 1875 phy-cellid: 299, B3@15Mhz earfcn: 1875 phy-cellid: 306, B3@15Mhz earfcn: 1875 phy-cellid: 435, B3@15Mhz earfcn: 1875 phy-cellid: 446, B3@15Mhz earfcn: 1875 phy-cellid: 69, B3@15Mhz earfcn: 1875 phy-cellid: 7, B3@15Mhz earfcn: 1875 phy-cellid: 70, B3@15Mhz earfcn: 1875 phy-cellid: 71, B7@20Mhz earfcn: 2850 phy-cellid: 69, B7@20Mhz earfcn: 2850 phy-cellid: 70

LTE2 primary: B20@10Mhz earfcn: 6300 phy-cellid: 108, B20@10Mhz earfcn: 6300 phy-cellid: 113, B20@10Mhz earfcn: 6300 phy-cellid: 248, B20@10Mhz earfcn: 6300 phy-cellid: 272, B20@10Mhz earfcn: 6300 phy-cellid: 329, B20@10Mhz earfcn: 6300 phy-cellid: 342, B20@10Mhz earfcn: 6300 phy-cellid: 364, B20@10Mhz earfcn: 6300 phy-cellid: 369, B20@10Mhz earfcn: 6300 phy-cellid: 433, B20@10Mhz earfcn: 6300 phy-cellid: 473, B20@10Mhz earfcn: 6300 phy-cellid: 52, B20@10Mhz earfcn: 6300 phy-cellid: 58, B20@10Mhz earfcn: 6300 phy-cellid: 97, B3@20Mhz earfcn: 1344 phy-cellid: 184, B3@20Mhz earfcn: 1344 phy-cellid: 214, B3@20Mhz earfcn: 1344 phy-cellid: 219, B3@20Mhz earfcn: 1344 phy-cellid: 227, B3@20Mhz earfcn: 1344 phy-cellid: 253, B3@20Mhz earfcn: 1344 phy-cellid: 365, B3@20Mhz earfcn: 1344 phy-cellid: 440, B3@20Mhz earfcn: 1344 phy-cellid: 453, B3@20Mhz earfcn: 1344 phy-cellid: 477, B3@20Mhz earfcn: 1344 phy-cellid: 66, B3@20Mhz earfcn: 1344 phy-cellid: 82, B3@20Mhz earfcn: 1344 phy-cellid: 84, B7@20Mhz earfcn: 3050 phy-cellid: 156, B7@20Mhz earfcn: 3050 phy-cellid: 314, B7@20Mhz earfcn: 3248 phy-cellid: 171, B7@20Mhz earfcn: 3248 phy-cellid: 373, B7@20Mhz earfcn: 3248 phy-cellid: 407, B7@20Mhz earfcn: 3248 phy-cellid: 412, B7@20Mhz earfcn: 3248 phy-cellid: 430, B7@20Mhz earfcn: 3248 phy-cellid: 73

LTE2 CA: B20@10Mhz earfcn: 6300 phy-cellid: 103, B20@10Mhz earfcn: 6300 phy-cellid: 211, B20@10Mhz earfcn: 6300 phy-cellid: 224, B20@10Mhz earfcn: 6300 phy-cellid: 248, B20@10Mhz earfcn: 6300 phy-cellid: 337, B20@10Mhz earfcn: 6300 phy-cellid: 364, B20@10Mhz earfcn: 6300 phy-cellid: 369, B20@10Mhz earfcn: 6300 phy-cellid: 38, B20@10Mhz earfcn: 6300 phy-cellid: 433, B3@20Mhz earfcn: 1344 phy-cellid: 217, B3@20Mhz earfcn: 1344 phy-cellid: 250, B3@20Mhz earfcn: 1344 phy-cellid: 310, B3@20Mhz earfcn: 1344 phy-cellid: 43, B3@20Mhz earfcn: 1344 phy-cellid: 440, B3@20Mhz earfcn: 1344 phy-cellid: 442, B3@20Mhz earfcn: 1344 phy-cellid: 453, B3@20Mhz earfcn: 1344 phy-cellid: 477, B3@20Mhz earfcn: 1344 phy-cellid: 56, B3@20Mhz earfcn: 1344 phy-cellid: 66, B3@20Mhz earfcn: 1344 phy-cellid: 84, B7@20Mhz earfcn: 3050 phy-cellid: 156, B7@20Mhz earfcn: 3050 phy-cellid: 251, B7@20Mhz earfcn: 3050 phy-cellid: 298, B7@20Mhz earfcn: 3050 phy-cellid: 314, B7@20Mhz earfcn: 3050 phy-cellid: 437, B7@20Mhz earfcn: 3050 phy-cellid: 495, B7@20Mhz earfcn: 3050 phy-cellid: 78, B7@20Mhz earfcn: 3248 phy-cellid: 110, B7@20Mhz earfcn: 3248 phy-cellid: 144, B7@20Mhz earfcn: 3248 phy-cellid: 171, B7@20Mhz earfcn: 3248 phy-cellid: 257, B7@20Mhz earfcn: 3248 phy-cellid: 34, B7@20Mhz earfcn: 3248 phy-cellid: 353, B7@20Mhz earfcn: 3248 phy-cellid: 407, B7@20Mhz earfcn: 3248 phy-cellid: 412, B7@20Mhz earfcn: 3248 phy-cellid: 430, B7@20Mhz earfcn: 3248 phy-cellid: 481

## Operator Diversity

Normal criterion: UDP loss <2%, ping p95 <100 ms, collector success.

- Both good: 7 epochs
- LTE1 impaired while LTE2 good: 13 epochs
- LTE2 impaired while LTE1 good: 0 epochs
- Both impaired: 7 epochs, about 420 seconds

Strict criterion: UDP loss <1%, ping p95 <60 ms, collector success.

- Both good: 0 epochs
- LTE1 impaired while LTE2 good: 16 epochs
- LTE2 impaired while LTE1 good: 0 epochs
- Both impaired: 11 epochs, about 660 seconds

## Limitations

This worker version did not produce continuous LTE telemetry JSONL or automatic full synchronized analysis. The quick analyzer uses per-epoch collector summaries, so short events inside an epoch may be smoothed out. Location/time specificity applies; do not generalize beyond this route and drive.
