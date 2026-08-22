# Drive Skill v2 Verification

Classification: `PASS_DRIVE_SKILL_V2`

## Stage A - Parser/Unit Tests

- PASS - GPS parser valid decimal coordinate: {'utc': '2026-08-12T00:00:00+00:00', 'router_gps_time': None, 'valid': True, 'gps_valid': True, 'gps_valid_reason': None, 'latitude': 59.123456, 'longitude': 24.123456, 'altitude_m': None, 'speed_mps': 0.1, 'course_deg': None, 'satellites': None, 'hdop': None}
- PASS - GPS parser invalid/no-fix output: {'utc': '2026-08-12T00:00:01+00:00', 'router_gps_time': None, 'valid': False, 'gps_valid': False, 'gps_valid_reason': 'NO_NUMERIC_COORDINATE', 'latitude': None, 'longitude': None, 'altitude_m': None, 'speed_mps': None, 'course_deg': None, 'satellites': None, 'hdop': None}
- PASS - GPS parser alternate DMS formatting: {'utc': '2026-08-12T00:00:02+00:00', 'router_gps_time': None, 'valid': True, 'gps_valid': True, 'gps_valid_reason': None, 'latitude': 59.123456, 'longitude': 24.123456, 'altitude_m': None, 'speed_mps': None, 'course_deg': None, 'satellites': None, 'hdop': None}
- PASS - GPS parser RouterOS compact ddmm.mmmm formatting: {'utc': '2026-08-12T00:00:03+00:00', 'router_gps_time': None, 'valid': True, 'gps_valid': True, 'gps_valid_reason': None, 'latitude': 59.36693166666667, 'longitude': 24.92032, 'altitude_m': None, 'speed_mps': 2.0, 'course_deg': None, 'satellites': None, 'hdop': None}
- PASS - LTE parser B1: {'utc': '2026-08-14T19:31:48.024+00:00', 'interface': 'lte1', 'modem_id': None, 'operator': 'Elisa', 'operator_source': 'network', 'network_operator': 'Elisa', 'sim_id': None, 'status': 'registered', 'registered': True, 'primary_band': 'B1', 'primary_band_raw': 'B1@10Mhz earfcn: 300 phy-cellid: 11', 'bandwidth_mhz': 10, 'earfcn': 300, 'enb_id': None, 'cell_id': None, 'sector_id': None, 'pci': 11, 'ca_bands': [], 'rssi_dbm': None, 'rsrp_dbm': -95.0, 'rsrq_db': None, 'sinr_db': None, 'cqi': None, 'ri': None, 'tx_bytes': None, 'tx_packets': None, 'tx_queue_drops': None, 'raw_parse': {'status': 'registered', 'current-operator': 'Elisa EE', 'primary-band': 'B1@10Mhz earfcn: 300 phy-cellid: 11', 'rsrp': '-95dBm'}}
- PASS - LTE parser B3: {'utc': '2026-08-14T19:31:48.025+00:00', 'interface': 'lte1', 'modem_id': None, 'operator': 'Elisa', 'operator_source': 'network', 'network_operator': 'Elisa', 'sim_id': None, 'status': 'registered', 'registered': True, 'primary_band': 'B3', 'primary_band_raw': 'B3@15Mhz earfcn: 1875 phy-cellid: 69', 'bandwidth_mhz': 15, 'earfcn': 1875, 'enb_id': None, 'cell_id': None, 'sector_id': None, 'pci': 69, 'ca_bands': [], 'rssi_dbm': None, 'rsrp_dbm': -95.0, 'rsrq_db': None, 'sinr_db': None, 'cqi': None, 'ri': None, 'tx_bytes': None, 'tx_packets': None, 'tx_queue_drops': None, 'raw_parse': {'status': 'registered', 'current-operator': 'Elisa EE', 'primary-band': 'B3@15Mhz earfcn: 1875 phy-cellid: 69', 'rsrp': '-95dBm'}}
- PASS - LTE parser B7: {'utc': '2026-08-14T19:31:48.025+00:00', 'interface': 'lte1', 'modem_id': None, 'operator': 'Elisa', 'operator_source': 'network', 'network_operator': 'Elisa', 'sim_id': None, 'status': 'registered', 'registered': True, 'primary_band': 'B7', 'primary_band_raw': 'B7', 'bandwidth_mhz': None, 'earfcn': None, 'enb_id': None, 'cell_id': None, 'sector_id': None, 'pci': None, 'ca_bands': [], 'rssi_dbm': None, 'rsrp_dbm': -95.0, 'rsrq_db': None, 'sinr_db': None, 'cqi': None, 'ri': None, 'tx_bytes': None, 'tx_packets': None, 'tx_queue_drops': None, 'raw_parse': {'status': 'registered', 'current-operator': 'Elisa EE', 'primary-band': 'B7', 'rsrp': '-95dBm'}}
- PASS - LTE parser B20: {'utc': '2026-08-14T19:31:48.025+00:00', 'interface': 'lte1', 'modem_id': None, 'operator': 'Elisa', 'operator_source': 'network', 'network_operator': 'Elisa', 'sim_id': None, 'status': 'registered', 'registered': True, 'primary_band': 'B20', 'primary_band_raw': 'B20', 'bandwidth_mhz': None, 'earfcn': None, 'enb_id': None, 'cell_id': None, 'sector_id': None, 'pci': None, 'ca_bands': [], 'rssi_dbm': None, 'rsrp_dbm': -95.0, 'rsrq_db': None, 'sinr_db': None, 'cqi': None, 'ri': None, 'tx_bytes': None, 'tx_packets': None, 'tx_queue_drops': None, 'raw_parse': {'status': 'registered', 'current-operator': 'Elisa EE', 'primary-band': 'B20', 'rsrp': '-95dBm'}}
- PASS - LTE parser B38: {'utc': '2026-08-14T19:31:48.025+00:00', 'interface': 'lte1', 'modem_id': None, 'operator': 'Elisa', 'operator_source': 'network', 'network_operator': 'Elisa', 'sim_id': None, 'status': 'registered', 'registered': True, 'primary_band': 'B38', 'primary_band_raw': 'B38', 'bandwidth_mhz': None, 'earfcn': None, 'enb_id': None, 'cell_id': None, 'sector_id': None, 'pci': None, 'ca_bands': [], 'rssi_dbm': None, 'rsrp_dbm': -95.0, 'rsrq_db': None, 'sinr_db': None, 'cqi': None, 'ri': None, 'tx_bytes': None, 'tx_packets': None, 'tx_queue_drops': None, 'raw_parse': {'status': 'registered', 'current-operator': 'Elisa EE', 'primary-band': 'B38', 'rsrp': '-95dBm'}}
- PASS - LTE parser deregistered state: {'utc': '2026-08-14T19:31:48.025+00:00', 'interface': 'lte1', 'modem_id': None, 'operator': None, 'operator_source': None, 'network_operator': None, 'sim_id': None, 'status': 'searching', 'registered': False, 'primary_band': None, 'primary_band_raw': None, 'bandwidth_mhz': None, 'earfcn': None, 'enb_id': None, 'cell_id': None, 'sector_id': None, 'pci': None, 'ca_bands': [], 'rssi_dbm': None, 'rsrp_dbm': None, 'rsrq_db': None, 'sinr_db': None, 'cqi': None, 'ri': None, 'tx_bytes': None, 'tx_packets': None, 'tx_queue_drops': None, 'raw_parse': {'status': 'searching'}}
- PASS - Event detector B3 -> B20: ['BAND_CHANGE', 'CELL_CHANGE', 'REGISTRATION_LOST', 'REGISTRATION_RESTORED']
- PASS - Event detector cell A -> B: ['BAND_CHANGE', 'CELL_CHANGE', 'REGISTRATION_LOST', 'REGISTRATION_RESTORED']
- PASS - Event detector registration loss/recovery: ['BAND_CHANGE', 'CELL_CHANGE', 'REGISTRATION_LOST', 'REGISTRATION_RESTORED']
- PASS - Timeline nearest sample selection: ({'utc': '2026-08-12T00:00:00+00:00', 'v': 1}, 1.0)
- PASS - Timeline stale-data cutoff: None
- PASS - Diversity analyzer all categories: {'both_good': 1, 'elisa_impaired_telia_good': 1, 'telia_impaired_elisa_good': 1, 'both_impaired': 1, 'longest_both_impaired_interval_s': 1, 'percentage_with_at_least_one_good_path': 75.0, 'criteria': 'normal'}
- PASS - Regression analyzer labels first drive as legacy/coarse: {"session_id": "drive-20260811-213442-seedri-smarten-seedri", "state": "COMPLETE", "started_utc": "2026-08-11T18:34:42+00:00", "completed_utc": "2026-08-11T19:03:32+00:00", "epochs": 27, "path_summary": {"lte1": {"epochs": 27, "successful_epochs": 26, "avg_mbps": 5.78079845039106, "avg_udp_loss_percent": 3.2115897435897436, "max_udp_loss_percent": 38.904, "avg_ping_p95_ms": 1007.7148148148148, "max_ping_p95_ms": 5392.0, "bands_seen": ["B1@15Mhz earfcn: 523 phy-cellid: 207", "B1@15Mhz earfcn: 523 phy-cellid: 208", "B1@15Mhz earfcn: 523 phy-cellid: 276", "B1@15Mhz earfcn: 523 phy-cellid: 277", "B1@15Mhz earfcn: 523 phy-cellid: 278", "B1@15Mhz earfcn: 523 phy-cellid: 306", "B1@15Mhz earfcn: 523 phy-cellid: 324", "B1@15Mhz earfcn: 523 phy-cellid: 439", "B1@15Mhz earfcn: 523 phy-cellid: 446", "B1@15Mhz earfcn: 523 phy-cellid: 69", "B1@15Mhz earfcn: 523 phy-cellid: 70", "B1@15Mhz earfcn: 523 phy-cellid: 71", "B20@10Mhz earfcn: 6200 phy-cellid: 278", "B20@10Mhz earfcn: 6200 phy-cellid: 439", "B20@10Mhz earfcn: 6200 phy-cellid: 69", "B20@10Mhz earfcn: 6200 phy-cellid: 7", "B20@10Mhz earfcn: 6200 phy-cellid: 71", "B38@20Mhz earfcn: 38098 phy-cellid: 3", "B3@15Mhz earfcn: 1875 phy-cellid: 276", "B3@15Mhz earfcn: 1875 phy-cellid: 278", "B3@15Mhz earfcn: 1875 phy-cellid: 298", "B3@15Mhz earfcn: 1875 phy-cellid: 299", "B3@15Mhz earfcn: 1875 phy-cellid: 306", "B3@15Mhz earfcn: 1875 phy-cellid: 435", "B3@15Mhz earfcn: 1875 phy-cellid: 446", "B3@15Mhz earfcn: 1875 phy-cellid: 69", "B3@15Mhz earfcn: 1875 phy-cellid: 7", "B3@15Mhz earfcn: 1875 phy-cellid: 70", "B3@15Mhz earfcn: 1875 phy-cellid: 71", "B7@20Mhz earfcn: 2850 phy-cellid: 69", "B7@20Mhz earfcn: 2850 phy-cellid: 70"], "ca_seen": ["B38@20Mhz earfcn: 37900 phy-cellid: 3"], "normal_good_epochs": 7, "strict_good_epochs": 0}, "lte2": {"epochs": 27, "successful_epochs": 26, "avg_mbps": 5.957882382375647, "avg_udp_loss_percent": 0.48717948717948717, "max_udp_loss_percent": 7.850666666666666, "avg_ping_p95_ms": 215.0074074074074, "max_ping_p95_ms": 2248.0, "bands_seen": ["B20@10Mhz earfcn: 6300 phy-cellid: 108", "B20@10Mhz earfcn: 6300 phy-cellid: 113", "B20@10Mhz earfcn: 6300 phy-cellid: 248", "B20@10Mhz earfcn: 6300 phy-cellid: 272", "B20@10Mhz earfcn: 6300 phy-cellid: 329", "B20@10Mhz earfcn: 6300 phy-cellid: 342", "B20@10Mhz earfcn: 6300 phy-cellid: 364", "B20@10Mhz earfcn: 6300 phy-cellid: 369", "B20@10Mhz earfcn: 6300 phy-cellid: 433", "B20@10Mhz earfcn: 6300 phy-cellid: 473", "B20@10Mhz earfcn: 6300 phy-cellid: 52", "B20@10Mhz earfcn: 6300 phy-cellid: 58", "B20@10Mhz earfcn: 6300 phy-cellid: 97", "B3@20Mhz earfcn: 1344 phy-cellid: 184", "B3@20Mhz earfcn: 1344 phy-cellid: 214", "B3@20Mhz earfcn: 1344 phy-cellid: 219", "B3@20Mhz earfcn: 1344 phy-cellid: 227", "B3@20Mhz earfcn: 1344 phy-cellid: 253", "B3@20Mhz earfcn: 1344 phy-cellid: 365", "B3@20Mhz earfcn: 1344 phy-cellid: 440", "B3@20Mhz earfcn: 1344 phy-cellid: 453", "B3@20Mhz earfcn: 1344 phy-cellid: 477", "B3@20Mhz earfcn: 1344 phy-cellid: 66", "B3@20Mhz earfcn: 1344 phy-cellid: 82", "B3@20Mhz earfcn: 1344 phy-cellid: 84", "B7@20Mhz earfcn: 3050 phy-cellid: 156", "B7@20Mhz earfcn: 3050 phy-cellid: 314", "B7@20Mhz earfcn: 3248 phy-cellid: 171", "B7@20Mhz earfcn: 3248 phy-cellid: 373", "B7@20Mhz earfcn: 3248 phy-cellid: 407", "B7@20Mhz earfcn: 3248 phy-cellid: 412", "B7@20Mhz earfcn: 3248 phy-cellid: 430", "B7@20Mhz earfcn: 3248 phy-cellid: 73"], "ca_seen": ["B20@10Mhz earfcn: 6300 phy-cellid: 103", "B20@10Mhz earfcn: 6300 phy-cellid: 211", "B20@10Mhz earfcn: 6300 phy-cellid: 224", "B20@10Mhz earfcn: 6300 phy-cellid: 248", "B20@10Mhz earfcn: 6300 phy-cellid: 337", "B20@10Mhz earfcn: 6300 phy-cellid: 364", "B20@10Mhz earfcn: 6300 phy-cellid: 369", "B20@10Mhz earfcn: 6300 phy-cellid: 38", "B20@10Mhz earfcn: 6300 phy-cellid: 433", "B3@20Mhz earfcn: 1344 phy-cellid: 217", "B3@20Mhz earfcn: 1344 phy-cellid: 250", "B3@20Mhz earfcn: 1344 phy-cellid: 310", "B3@20Mhz earfcn: 1344 phy-cellid: 43", "B3@20Mhz earfcn: 1344 phy-cellid: 440", "B3@20Mhz earfcn: 1344 phy-cellid: 442", "B3@20Mhz earfcn: 1344 phy-cellid: 453", "B3@20Mhz earfcn: 1344 phy-cellid: 477", "B3@20Mhz earfcn: 1344 phy-cellid: 56", "B3@20Mhz earfcn: 1344 phy-cellid: 66", "B3@20Mhz earfcn: 1344 phy-cellid: 84", "B7@20Mhz earfcn: 3050 phy-cellid: 156", "B7@20Mhz earfcn: 3050 phy-cellid: 251", "B7@20Mhz earfcn: 3050 phy-cellid: 298", "B7@20Mhz earfcn: 3050 phy-cellid: 314", "B7@20Mhz earfcn: 3050 phy-cellid: 437", "B7@20Mhz earfcn: 3050 phy-cellid: 495", "B7@20Mhz earfcn: 3050 phy-cellid: 78", "B7@20Mhz earfcn: 3248 phy-cellid: 110", "B7@20Mhz earfcn: 3248 phy-cellid: 144", "B7@20Mhz earfcn: 3248 phy-cellid: 171", "B7@20Mhz earfcn: 3248 phy-cellid: 257", "B7@20Mhz earfcn: 3248 phy-cellid: 34", "B7@20Mhz earfcn: 3248 phy-cellid: 353", "B7@20Mhz earfcn: 3248 phy-cellid: 407", "B7@20Mhz earfcn: 3248 phy-cellid: 412", "B7@20Mhz earfcn: 3248 phy-cellid: 430", "B7@20Mhz earfcn: 3248 phy-cellid: 481"], "normal_good_epochs": 20, "strict_good_epochs": 16}}, "operator_diversity_epoch_counts_normal": {"both_good": 7, "lte1_impaired_lte2_good": 13, "lte2_impaired_lte1_good": 0, "both_impaired": 7}, "operator_diversity_epoch_counts_strict": {"both_good": 0, "lte1_impaired_lte2_good": 16, "lte2_impaired_lte1_good": 0, "both_impaired": 11}, "approx_seconds_per_epoch": 60, "gps_valid_fixes": 0, "location_data_present": false, "limitations": ["Post-stop report generated from per-epoch collector summaries; sub-second synchronized impairment analysis was not available from this worker version.", "LTE operator names were not resolved in this quick report; paths are lte1/lte2."], "skill": "elmo-lte-drive-test", "skill_version": "2.0", "resolution": "LEGACY_COARSE_EPOCH_DATA", "note": "Old run preserved; continuous GPS/LTE/ping streams were not collected."}

## Stage B - Live/Stationary Validation

```json
{
  "iperf3": {
    "available": true,
    "version": "iperf 3.16 (cJSON 1.7.15)",
    "json_stream_supported": false,
    "forceflush_supported": true
  },
  "critical_pass": true,
  "legacy_regression": {
    "session_id": "drive-20260811-213442-seedri-smarten-seedri",
    "state": "COMPLETE",
    "started_utc": "2026-08-11T18:34:42+00:00",
    "completed_utc": "2026-08-11T19:03:32+00:00",
    "epochs": 27,
    "path_summary": {
      "lte1": {
        "epochs": 27,
        "successful_epochs": 26,
        "avg_mbps": 5.78079845039106,
        "avg_udp_loss_percent": 3.2115897435897436,
        "max_udp_loss_percent": 38.904,
        "avg_ping_p95_ms": 1007.7148148148148,
        "max_ping_p95_ms": 5392.0,
        "bands_seen": [
          "B1@15Mhz earfcn: 523 phy-cellid: 207",
          "B1@15Mhz earfcn: 523 phy-cellid: 208",
          "B1@15Mhz earfcn: 523 phy-cellid: 276",
          "B1@15Mhz earfcn: 523 phy-cellid: 277",
          "B1@15Mhz earfcn: 523 phy-cellid: 278",
          "B1@15Mhz earfcn: 523 phy-cellid: 306",
          "B1@15Mhz earfcn: 523 phy-cellid: 324",
          "B1@15Mhz earfcn: 523 phy-cellid: 439",
          "B1@15Mhz earfcn: 523 phy-cellid: 446",
          "B1@15Mhz earfcn: 523 phy-cellid: 69",
          "B1@15Mhz earfcn: 523 phy-cellid: 70",
          "B1@15Mhz earfcn: 523 phy-cellid: 71",
          "B20@10Mhz earfcn: 6200 phy-cellid: 278",
          "B20@10Mhz earfcn: 6200 phy-cellid: 439",
          "B20@10Mhz earfcn: 6200 phy-cellid: 69",
          "B20@10Mhz earfcn: 6200 phy-cellid: 7",
          "B20@10Mhz earfcn: 6200 phy-cellid: 71",
          "B38@20Mhz earfcn: 38098 phy-cellid: 3",
          "B3@15Mhz earfcn: 1875 phy-cellid: 276",
          "B3@15Mhz earfcn: 1875 phy-cellid: 278",
          "B3@15Mhz earfcn: 1875 phy-cellid: 298",
          "B3@15Mhz earfcn: 1875 phy-cellid: 299",
          "B3@15Mhz earfcn: 1875 phy-cellid: 306",
          "B3@15Mhz earfcn: 1875 phy-cellid: 435",
          "B3@15Mhz earfcn: 1875 phy-cellid: 446",
          "B3@15Mhz earfcn: 1875 phy-cellid: 69",
          "B3@15Mhz earfcn: 1875 phy-cellid: 7",
          "B3@15Mhz earfcn: 1875 phy-cellid: 70",
          "B3@15Mhz earfcn: 1875 phy-cellid: 71",
          "B7@20Mhz earfcn: 2850 phy-cellid: 69",
          "B7@20Mhz earfcn: 2850 phy-cellid: 70"
        ],
        "ca_seen": [
          "B38@20Mhz earfcn: 37900 phy-cellid: 3"
        ],
        "normal_good_epochs": 7,
        "strict_good_epochs": 0
      },
      "lte2": {
        "epochs": 27,
        "successful_epochs": 26,
        "avg_mbps": 5.957882382375647,
        "avg_udp_loss_percent": 0.48717948717948717,
        "max_udp_loss_percent": 7.850666666666666,
        "avg_ping_p95_ms": 215.0074074074074,
        "max_ping_p95_ms": 2248.0,
        "bands_seen": [
          "B20@10Mhz earfcn: 6300 phy-cellid: 108",
          "B20@10Mhz earfcn: 6300 phy-cellid: 113",
          "B20@10Mhz earfcn: 6300 phy-cellid: 248",
          "B20@10Mhz earfcn: 6300 phy-cellid: 272",
          "B20@10Mhz earfcn: 6300 phy-cellid: 329",
          "B20@10Mhz earfcn: 6300 phy-cellid: 342",
          "B20@10Mhz earfcn: 6300 phy-cellid: 364",
          "B20@10Mhz earfcn: 6300 phy-cellid: 369",
          "B20@10Mhz earfcn: 6300 phy-cellid: 433",
          "B20@10Mhz earfcn: 6300 phy-cellid: 473",
          "B20@10Mhz earfcn: 6300 phy-cellid: 52",
          "B20@10Mhz earfcn: 6300 phy-cellid: 58",
          "B20@10Mhz earfcn: 6300 phy-cellid: 97",
          "B3@20Mhz earfcn: 1344 phy-cellid: 184",
          "B3@20Mhz earfcn: 1344 phy-cellid: 214",
          "B3@20Mhz earfcn: 1344 phy-cellid: 219",
          "B3@20Mhz earfcn: 1344 phy-cellid: 227",
          "B3@20Mhz earfcn: 1344 phy-cellid: 253",
          "B3@20Mhz earfcn: 1344 phy-cellid: 365",
          "B3@20Mhz earfcn: 1344 phy-cellid: 440",
          "B3@20Mhz earfcn: 1344 phy-cellid: 453",
          "B3@20Mhz earfcn: 1344 phy-cellid: 477",
          "B3@20Mhz earfcn: 1344 phy-cellid: 66",
          "B3@20Mhz earfcn: 1344 phy-cellid: 82",
          "B3@20Mhz earfcn: 1344 phy-cellid: 84",
          "B7@20Mhz earfcn: 3050 phy-cellid: 156",
          "B7@20Mhz earfcn: 3050 phy-cellid: 314",
          "B7@20Mhz earfcn: 3248 phy-cellid: 171",
          "B7@20Mhz earfcn: 3248 phy-cellid: 373",
          "B7@20Mhz earfcn: 3248 phy-cellid: 407",
          "B7@20Mhz earfcn: 3248 phy-cellid: 412",
          "B7@20Mhz earfcn: 3248 phy-cellid: 430",
          "B7@20Mhz earfcn: 3248 phy-cellid: 73"
        ],
        "ca_seen": [
          "B20@10Mhz earfcn: 6300 phy-cellid: 103",
          "B20@10Mhz earfcn: 6300 phy-cellid: 211",
          "B20@10Mhz earfcn: 6300 phy-cellid: 224",
          "B20@10Mhz earfcn: 6300 phy-cellid: 248",
          "B20@10Mhz earfcn: 6300 phy-cellid: 337",
          "B20@10Mhz earfcn: 6300 phy-cellid: 364",
          "B20@10Mhz earfcn: 6300 phy-cellid: 369",
          "B20@10Mhz earfcn: 6300 phy-cellid: 38",
          "B20@10Mhz earfcn: 6300 phy-cellid: 433",
          "B3@20Mhz earfcn: 1344 phy-cellid: 217",
          "B3@20Mhz earfcn: 1344 phy-cellid: 250",
          "B3@20Mhz earfcn: 1344 phy-cellid: 310",
          "B3@20Mhz earfcn: 1344 phy-cellid: 43",
          "B3@20Mhz earfcn: 1344 phy-cellid: 440",
          "B3@20Mhz earfcn: 1344 phy-cellid: 442",
          "B3@20Mhz earfcn: 1344 phy-cellid: 453",
          "B3@20Mhz earfcn: 1344 phy-cellid: 477",
          "B3@20Mhz earfcn: 1344 phy-cellid: 56",
          "B3@20Mhz earfcn: 1344 phy-cellid: 66",
          "B3@20Mhz earfcn: 1344 phy-cellid: 84",
          "B7@20Mhz earfcn: 3050 phy-cellid: 156",
          "B7@20Mhz earfcn: 3050 phy-cellid: 251",
          "B7@20Mhz earfcn: 3050 phy-cellid: 298",
          "B7@20Mhz earfcn: 3050 phy-cellid: 314",
          "B7@20Mhz earfcn: 3050 phy-cellid: 437",
          "B7@20Mhz earfcn: 3050 phy-cellid: 495",
          "B7@20Mhz earfcn: 3050 phy-cellid: 78",
          "B7@20Mhz earfcn: 3248 phy-cellid: 110",
          "B7@20Mhz earfcn: 3248 phy-cellid: 144",
          "B7@20Mhz earfcn: 3248 phy-cellid: 171",
          "B7@20Mhz earfcn: 3248 phy-cellid: 257",
          "B7@20Mhz earfcn: 3248 phy-cellid: 34",
          "B7@20Mhz earfcn: 3248 phy-cellid: 353",
          "B7@20Mhz earfcn: 3248 phy-cellid: 407",
          "B7@20Mhz earfcn: 3248 phy-cellid: 412",
          "B7@20Mhz earfcn: 3248 phy-cellid: 430",
          "B7@20Mhz earfcn: 3248 phy-cellid: 481"
        ],
        "normal_good_epochs": 20,
        "strict_good_epochs": 16
      }
    },
    "operator_diversity_epoch_counts_normal": {
      "both_good": 7,
      "lte1_impaired_lte2_good": 13,
      "lte2_impaired_lte1_good": 0,
      "both_impaired": 7
    },
    "operator_diversity_epoch_counts_strict": {
      "both_good": 0,
      "lte1_impaired_lte2_good": 16,
      "lte2_impaired_lte1_good": 0,
      "both_impaired": 11
    },
    "approx_seconds_per_epoch": 60,
    "gps_valid_fixes": 0,
    "location_data_present": false,
    "limitations": [
      "Post-stop report generated from per-epoch collector summaries; sub-second synchronized impairment analysis was not available from this worker version.",
      "LTE operator names were not resolved in this quick report; paths are lte1/lte2."
    ],
    "skill": "elmo-lte-drive-test",
    "skill_version": "2.0",
    "resolution": "LEGACY_COARSE_EPOCH_DATA",
    "note": "Old run preserved; continuous GPS/LTE/ping streams were not collected."
  },
  "session_summary": {
    "skill": "elmo-lte-drive-test",
    "skill_version": "2.0",
    "resolution": "V2_CONTINUOUS_TIMELINE",
    "session_id": "drive-20260812-084251-skill-v2-validation-only",
    "timeline_rows": 187,
    "gps_valid_fixes": 180,
    "lte1_samples": 169,
    "lte2_samples": 169,
    "ping_lte1_samples": 361,
    "ping_lte2_samples": 374,
    "traffic_loss_resolution_s": 10,
    "diversity_normal": {
      "both_good": 67,
      "elisa_impaired_telia_good": 119,
      "telia_impaired_elisa_good": 0,
      "both_impaired": 1,
      "longest_both_impaired_interval_s": 1,
      "percentage_with_at_least_one_good_path": 99.47,
      "criteria": "normal"
    },
    "diversity_strict": {
      "both_good": 55,
      "elisa_impaired_telia_good": 131,
      "telia_impaired_elisa_good": 0,
      "both_impaired": 1,
      "longest_both_impaired_interval_s": 1,
      "percentage_with_at_least_one_good_path": 99.47,
      "criteria": "strict"
    }
  },
  "mid_epoch_stop_preserved": true
}
```
