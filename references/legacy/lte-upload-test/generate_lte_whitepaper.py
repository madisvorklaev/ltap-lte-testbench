#!/usr/bin/env python3
import csv
import json
import math
import statistics
import textwrap
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages


BASE = Path(__file__).resolve().parent
RESULTS = BASE / "results"
OUT_DIR = RESULTS / "whitepaper"
OUT_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class Run:
    key: str
    label: str
    router: str
    placement: str
    pattern: str
    csv_path: Path
    caveat: str = ""


RUNS = [
    Run(
        "r99_indoor_6h",
        "R99 indoor 6h",
        "R99",
        "Indoor",
        "30 uploads, 12 min spacing",
        RESULTS / "R99/lte_upload_20260630_011839.csv",
        "Not directly equivalent to back-to-back runs.",
    ),
    Run(
        "r3_indoor_b2b",
        "R3 indoor b2b",
        "R3_7.6",
        "Indoor",
        "30 uploads, back-to-back",
        RESULTS / "R3_7.6/lte_upload_R3_7.6_20260630_081140.csv",
    ),
    Run(
        "r3_outdoor_evening",
        "R3 outdoor evening",
        "R3_7.6",
        "Outdoor",
        "30 uploads, back-to-back",
        RESULTS / "R3_7.6_outdoor-antennas/lte_upload_R3_7.6_outdoor-antennas_20260630_195249.csv",
    ),
    Run(
        "r99_outdoor_evening",
        "R99 outdoor evening",
        "R99",
        "Outdoor",
        "30 uploads, back-to-back",
        RESULTS / "R99_outdoor-antennas/lte_upload_R99_outdoor-antennas_20260630_213448.csv",
    ),
    Run(
        "r3_outdoor_night",
        "R3 outdoor night",
        "R3_7.6",
        "Outdoor",
        "30 uploads, 12 min spacing",
        RESULTS / "R3_7.6_outdoor-night-6h/lte_upload_R3_7.6_outdoor-night-6h_20260701_005646.csv",
        "Lower overnight load likely than evening back-to-back test.",
    ),
    Run(
        "r99_outdoor_morning",
        "R99 outdoor morning",
        "R99",
        "Outdoor",
        "30 uploads, back-to-back",
        RESULTS / "R99_outdoor-early-morning-b2b/lte_upload_R99_outdoor-early-morning-b2b_20260701_072758.csv",
        "Early-morning load likely lower than evening test.",
    ),
]

REFERENCE = {
    "label": "Teltonika RUT956 reference",
    "csv_path": RESULTS / "reference_non_mikrotik/non_mikrotik_reference_bounded_20260701_002346.csv",
    "speed_avg": 9.5830968,
    "speed_median": 9.453284,
    "runs": 10,
    "sinr": 14.0,
    "rsrq": -10.0,
    "rssi": -72.0,
    "rsrp": -102.0,
}

ROUTER_TECH = {
    "R99": {
        "routeros": "7.23.1 stable",
        "board": "LtAP-2HnD r2",
        "routerboard_fw": "7.23.1",
        "apn": "ELISA profile, apn=static",
        "lte_fw_note": "R11l-LTE7_V005, latest",
    },
    "R3_7.6": {
        "routeros": "7.6 stable",
        "board": "LtAP LTE6 kit / RBLtAP-2HnD",
        "routerboard_fw": "7.6",
        "apn": "ELISA profile, apn=static",
        "lte_fw_note": "FG621-EA latest seen: 16121.1034.00.01.01.10",
    },
    "Teltonika RUT956": {
        "routeros": "not captured",
        "board": "Teltonika RUT956",
        "routerboard_fw": "not captured",
        "apn": "not captured",
        "lte_fw_note": "not captured",
    },
}


def as_float(value):
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace("dB", "").replace("dBm", ""))
    except ValueError:
        return None


def mean(values):
    clean = [v for v in values if v is not None and not math.isnan(v)]
    return statistics.mean(clean) if clean else None


def median(values):
    clean = [v for v in values if v is not None and not math.isnan(v)]
    return statistics.median(clean) if clean else None


def fmt(value, digits=2):
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}"


def read_csv(path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def read_raw_lte_meta(csv_path):
    raw_path = csv_path.with_suffix(".jsonl")
    meta = {}
    if not raw_path.exists():
        return meta
    with raw_path.open() as f:
        for line in f:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            iface = item.get("interface")
            lte = item.get("sample", {}).get("lte", {})
            if iface and iface not in meta and lte:
                meta[iface] = {
                    "manufacturer": lte.get("manufacturer", ""),
                    "model": lte.get("model", ""),
                    "revision": lte.get("revision", ""),
                    "operator": lte.get("current-operator", ""),
                    "imei": lte.get("imei", ""),
                    "imsi": lte.get("imsi", ""),
                }
            if {"lte1", "lte2"}.issubset(meta):
                break
    return meta


def upload_speed(row):
    value = as_float(row.get("upload_speed_mbit_s"))
    if value is not None:
        return value
    bytes_s = as_float(row.get("upload_speed_bytes_s"))
    if bytes_s is not None:
        return bytes_s * 8 / 1_000_000
    return None


def summarize_mikrotik_run(run):
    rows = read_csv(run.csv_path)
    raw_meta = read_raw_lte_meta(run.csv_path)
    result = {
        "run": run,
        "rows": len(rows),
        "speed": {},
        "signal": {},
        "success": {},
    }
    for iface, label in [("lte1", "lte1_port18080"), ("lte2", "lte2_port18081")]:
        upload_rows = [
            r
            for r in rows
            if r.get("phase") == "after"
            and r.get("path_label") == label
            and r.get("interface") == iface
        ]
        speeds = [upload_speed(r) for r in upload_rows]
        times = [as_float(r.get("upload_time_total_s")) for r in upload_rows]
        result["speed"][iface] = {
            "avg": mean(speeds),
            "median": median(speeds),
            "min": min([s for s in speeds if s is not None], default=None),
            "max": max([s for s in speeds if s is not None], default=None),
            "time_avg": mean(times),
            "n": len(upload_rows),
        }
        result["success"][iface] = sum(
            1
            for r in upload_rows
            if r.get("curl_exit_code") == "0" and str(r.get("http_code", "")).startswith("2")
        )

        sig_rows = [r for r in rows if r.get("interface") == iface]
        result["signal"][iface] = {
            col: mean([as_float(r.get(col)) for r in sig_rows])
            for col in ["sinr", "rsrq", "rsrp", "rssi", "cqi", "ri"]
        }
        bands = sorted({r.get("primary_band", "") for r in sig_rows if r.get("primary_band")})
        cells = sorted({r.get("current_cellid", "") for r in sig_rows if r.get("current_cellid")})
        operators = sorted({r.get("operator", "") for r in sig_rows if r.get("operator")})
        result["signal"][iface]["bands"] = ", ".join(bands)
        result["signal"][iface]["cells"] = ", ".join(cells)
        result["signal"][iface]["operator"] = ", ".join(operators)
        result["signal"][iface]["raw_meta"] = raw_meta.get(iface, {})
    return result


SUMMARIES = [summarize_mikrotik_run(run) for run in RUNS]
BY_KEY = {s["run"].key: s for s in SUMMARIES}


def add_page_title(ax, title, subtitle=None):
    ax.axis("off")
    if len(title) >= 45 and "\n" not in title:
        words = title.split()
        split_at = len(words) // 2
        title = " ".join(words[:split_at]) + "\n" + " ".join(words[split_at:])
    ax.text(0.06, 0.92, title, fontsize=19, weight="bold", ha="left", va="top", color="#172033")
    if subtitle:
        subtitle_y = 0.82 if "\n" in title else 0.86
        ax.text(0.06, subtitle_y, subtitle, fontsize=11, ha="left", va="top", color="#556070")


def add_wrapped(ax, text, x=0.06, y=0.8, width=112, size=10.5, line_height=0.04, color="#222222"):
    for para in text.strip().split("\n\n"):
        lines = textwrap.wrap(para.strip(), width=width)
        for line in lines:
            ax.text(x, y, line, fontsize=size, ha="left", va="top", color=color)
            y -= line_height
        y -= line_height * 0.55
    return y


def new_page(pdf, title, subtitle=None, landscape=False):
    size = (11.69, 8.27) if landscape else (8.27, 11.69)
    fig, ax = plt.subplots(figsize=size)
    fig.patch.set_facecolor("white")
    add_page_title(ax, title, subtitle)
    return fig, ax


def save_page(pdf, fig):
    fig.tight_layout(pad=1.1, rect=[0.02, 0.08, 0.98, 0.92])
    pdf.savefig(fig)
    plt.close(fig)


def grouped_bars(ax, labels, vals_a, vals_b, title, ylabel, name_a="LTE1 / 18080", name_b="LTE2 / 18081", ylim=None):
    x = list(range(len(labels)))
    width = 0.36
    ax.bar([i - width / 2 for i in x], vals_a, width, label=name_a, color="#2F6B9A")
    ax.bar([i + width / 2 for i in x], vals_b, width, label=name_b, color="#D98B2B")
    ax.set_title(title, fontsize=13, weight="bold")
    ax.set_ylabel(ylabel)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=20, ha="right")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(frameon=False, loc="best")
    if ylim:
        ax.set_ylim(*ylim)
    for i, (a, b) in enumerate(zip(vals_a, vals_b)):
        if a is not None:
            ax.text(i - width / 2, a + (0.25 if a >= 0 else -0.25), fmt(a, 1), ha="center", va="bottom" if a >= 0 else "top", fontsize=8)
        if b is not None:
            ax.text(i + width / 2, b + (0.25 if b >= 0 else -0.25), fmt(b, 1), ha="center", va="bottom" if b >= 0 else "top", fontsize=8)


def table_page(pdf, title, subtitle, columns, rows, font_size=8.5, landscape=True):
    fig, ax = new_page(pdf, title, subtitle, landscape=landscape)
    ax.axis("off")
    table = ax.table(
        cellText=rows,
        colLabels=columns,
        loc="center",
        cellLoc="left",
        colLoc="left",
        bbox=[0.04, 0.05, 0.92, 0.76],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(font_size)
    table.scale(1, 1.35)
    for (row, col), cell in table.get_celld().items():
        cell.set_edgecolor("#CBD3DC")
        if row == 0:
            cell.set_facecolor("#E8EEF5")
            cell.set_text_props(weight="bold", color="#172033")
        elif row % 2 == 0:
            cell.set_facecolor("#F7F9FB")
    save_page(pdf, fig)


def speed(summary, iface):
    return summary["speed"][iface]["avg"]


def sig(summary, iface, field):
    return summary["signal"][iface].get(field)


def short_label(label):
    return (
        label.replace("R99 outdoor morning", "R99 out morning")
        .replace("R99 outdoor evening", "R99 out evening")
        .replace("R3 outdoor evening", "R3 out evening")
        .replace("R3 outdoor night", "R3 out night")
        .replace("Teltonika RUT956 reference", "RUT956 reference")
    )


def short_pattern(pattern):
    if "12 min" in pattern:
        return "30 x 12 min"
    if "back-to-back" in pattern:
        return "30 x b2b"
    if "single" in pattern:
        return "10 x single"
    return pattern


def union_for_router(router, iface, key):
    values = []
    for summary in SUMMARIES:
        if summary["run"].router != router:
            continue
        value = summary["signal"][iface].get(key)
        if not value:
            continue
        for part in str(value).split(", "):
            if part and part not in values:
                values.append(part)
    return ", ".join(values) if values else "n/a"


def latest_meta_for_router(router, iface):
    for summary in reversed(SUMMARIES):
        if summary["run"].router != router:
            continue
        meta = summary["signal"][iface].get("raw_meta") or {}
        if meta:
            return meta
    return {}


def modem_description(router, iface):
    meta = latest_meta_for_router(router, iface)
    model = meta.get("model") or "n/a"
    revision = meta.get("revision") or "n/a"
    if revision.startswith("16121.1034.00.01."):
        revision = revision.replace("16121.1034.00.01.01.", "01.")
        return f"{model} {revision} (latest 01.10)"
    if revision.startswith("R11l-LTE7_"):
        revision = revision.replace("R11l-LTE7_", "")
    return f"{model} {revision}"


def operator_description(router, iface):
    operator = union_for_router(router, iface, "operator")
    if operator == "n/a":
        return operator
    return operator


def short_bands(router, iface):
    bands = []
    for part in union_for_router(router, iface, "bands").split(", "):
        if not part or part == "n/a":
            continue
        band = part.split("@", 1)[0].strip()
        if band and band not in bands:
            bands.append(band)
    return ", ".join(bands) if bands else "n/a"


def make_pdf(pdf_path):
    with PdfPages(pdf_path) as pdf:
        fig, ax = new_page(
            pdf,
            "LTE Upload Performance and Signal Quality Comparison",
            f"MikroTik R99 / R3_7.6 and Teltonika RUT956 reference, generated {date.today().isoformat()}",
        )
        y = add_wrapped(
            ax,
            """
            This report summarizes repeated upload tests made through individual LTE modems. The practical question is not total aggregate throughput, but whether each modem path is suitable for robust upload performance in remote-controlled vehicle installations.

            Main finding: individual LTE path performance is strongly affected by radio quality, especially RSRQ and SINR where exposed, but cell load also matters. The same R99 outdoor setup improved substantially in the early morning compared with the previous evening run, while raw signal strength stayed broadly similar.

            The charts intentionally separate LTE1 and LTE2. Combined speed is not used because installation work needs to identify weak modem paths, antenna issues, and cell-quality problems independently.
            """,
            y=0.77,
            width=88,
            size=11,
        )
        add_wrapped(
            ax,
            """
            Key averages: R99 outdoor morning reached 6.98 Mbit/s on LTE1 and 10.21 Mbit/s on LTE2. R3 outdoor night reached 10.08 Mbit/s on LTE1 and 11.43 Mbit/s on LTE2. The Teltonika RUT956 reference single-path upload averaged 9.58 Mbit/s with manually captured SINR 14 dB and RSRQ -10 dB.
            """,
            y=y - 0.03,
            width=88,
            size=10.5,
            color="#344054",
        )
        save_page(pdf, fig)

        fig, ax = new_page(pdf, "Testing Method", "How the figures in this report were produced")
        add_wrapped(
            ax,
            """
            Upload method: two approximately 124 MB files were uploaded to a public HTTP upload service. For MikroTik tests, port 18080 was routed through LTE1 and port 18081 through LTE2, allowing each modem path to be measured independently. The upload client recorded HTTP status, upload duration, and curl-reported upload speed in Mbit/s.

            Router telemetry: during MikroTik tests, the script queried RouterOS API before each upload, during active uploads, and after completion. The report uses average telemetry per LTE interface, including RSRQ, RSRP, RSSI, SINR when exposed by the modem, CQI, and bands/cells observed.

            Repetition: MikroTik tests used 30 iterations per run. Some runs were back-to-back to show immediate behavior under continuous uploads; others were spaced over about six hours to sample changing network conditions. The Teltonika RUT956 reference used 10 repeated uploads over the active router path. Its LTE signal values were captured manually from the router UI rather than sampled through the same script.

            Caveats: R99 indoor was a six-hour spaced test, while several later runs were back-to-back. R3 does not expose SINR in the captured RouterOS fields, so RSRQ is the main cross-router quality indicator. The reference router result is single-path, so it should be treated as a practical benchmark rather than a modem-by-modem equivalent of the MikroTik tests.
            """,
            y=0.78,
            width=92,
            size=10.5,
        )
        save_page(pdf, fig)

        fig, ax = new_page(
            pdf,
            "Technical Context: Router and Modem Data",
            "MikroTik values come from RouterOS telemetry, raw JSONL, and the R3 audit snapshot.",
        )
        add_wrapped(
            ax,
            f"""
            R99 router: RouterOS {ROUTER_TECH['R99']['routeros']}; board {ROUTER_TECH['R99']['board']}; RouterBOARD firmware {ROUTER_TECH['R99']['routerboard_fw']}.

            R99 LTE1: {modem_description('R99', 'lte1')}; operator {operator_description('R99', 'lte1')}; SIM2; ELISA/static APN profile; bands observed {short_bands('R99', 'lte1')}.

            R99 LTE2: {modem_description('R99', 'lte2')}; operator {operator_description('R99', 'lte2')}; SIM1; ELISA/static APN profile; bands observed {short_bands('R99', 'lte2')}.

            R3 router: RouterOS {ROUTER_TECH['R3_7.6']['routeros']}; board {ROUTER_TECH['R3_7.6']['board']}; RouterBOARD firmware {ROUTER_TECH['R3_7.6']['routerboard_fw']}.

            R3 LTE1: {modem_description('R3_7.6', 'lte1')}; operator {operator_description('R3_7.6', 'lte1')}; SIM2; ELISA/static APN profile; bands observed {short_bands('R3_7.6', 'lte1')}.

            R3 LTE2: {modem_description('R3_7.6', 'lte2')}; operator {operator_description('R3_7.6', 'lte2')}; SIM1; ELISA/static APN profile; bands observed {short_bands('R3_7.6', 'lte2')}.

            Teltonika RUT956 reference: router model known from the test context; firmware version, LTE modem model, operator/APN, and modem firmware were not captured during this reference upload run. Its signal values were captured manually: SINR 14 dB, RSRQ -10 dB, RSSI -72 dBm, RSRP -102 dBm.

            Relevant note: the R3 FG621-EA modem firmware captured in the audit was behind the latest version reported by RouterOS. R99 reported R11l-LTE7_V005 as current and latest.
            """,
            y=0.78,
            width=96,
            size=10.3,
        )
        save_page(pdf, fig)

        # Intra-router speed comparisons.
        fig, axes = plt.subplots(2, 1, figsize=(11.69, 8.27))
        fig.suptitle("Speed Differences Between Modems Inside Each Router", fontsize=17, weight="bold", y=0.97)
        groups = [
            ("R99", ["r99_indoor_6h", "r99_outdoor_evening", "r99_outdoor_morning"]),
            ("R3_7.6", ["r3_indoor_b2b", "r3_outdoor_evening", "r3_outdoor_night"]),
        ]
        for ax, (router, keys) in zip(axes, groups):
            labels = [BY_KEY[k]["run"].label.replace("R99 ", "").replace("R3 ", "") for k in keys]
            grouped_bars(
                ax,
                labels,
                [speed(BY_KEY[k], "lte1") for k in keys],
                [speed(BY_KEY[k], "lte2") for k in keys],
                router,
                "Average upload speed (Mbit/s)",
                ylim=(0, 13),
            )
        fig.text(0.06, 0.02, "Each bar is the average of 30 successful uploads. LTE paths are shown separately; no combined throughput is used.", fontsize=9, color="#556070")
        save_page(pdf, fig)

        # Intra-router signal comparison.
        fig, axes = plt.subplots(2, 1, figsize=(11.69, 8.27))
        fig.suptitle("Signal Quality Differences Between Modems Inside Each Router", fontsize=17, weight="bold", y=0.97)
        for ax, (router, keys) in zip(axes, groups):
            labels = [BY_KEY[k]["run"].label.replace("R99 ", "").replace("R3 ", "") for k in keys]
            grouped_bars(
                ax,
                labels,
                [sig(BY_KEY[k], "lte1", "rsrq") for k in keys],
                [sig(BY_KEY[k], "lte2", "rsrq") for k in keys],
                f"{router} average RSRQ",
                "RSRQ (dB, less negative is better)",
                ylim=(-16, -7),
            )
        fig.text(0.06, 0.02, "RSRQ is a quality metric affected by interference and resource loading. It was available for all MikroTik runs; SINR was available for R99 only.", fontsize=9, color="#556070")
        save_page(pdf, fig)

        # Router-to-router speed and signal comparisons.
        fig, axes = plt.subplots(2, 1, figsize=(11.69, 8.27))
        fig.suptitle("Speed and Signal Differences Between Routers", fontsize=17, weight="bold", y=0.97)
        router_labels = ["R3 outdoor evening", "R99 outdoor evening", "R3 outdoor night", "R99 outdoor morning"]
        router_keys = ["r3_outdoor_evening", "r99_outdoor_evening", "r3_outdoor_night", "r99_outdoor_morning"]
        grouped_bars(
            axes[0],
            router_labels,
            [speed(BY_KEY[k], "lte1") for k in router_keys],
            [speed(BY_KEY[k], "lte2") for k in router_keys],
            "Per-modem upload speed",
            "Average upload speed (Mbit/s)",
            ylim=(0, 13),
        )
        grouped_bars(
            axes[1],
            router_labels,
            [sig(BY_KEY[k], "lte1", "rsrq") for k in router_keys],
            [sig(BY_KEY[k], "lte2", "rsrq") for k in router_keys],
            "Per-modem RSRQ",
            "RSRQ (dB, less negative is better)",
            ylim=(-16, -7),
        )
        fig.text(0.06, 0.02, "Evening back-to-back runs are the closest direct router comparison. Night/morning runs show what happens when cell load likely decreases.", fontsize=9, color="#556070")
        save_page(pdf, fig)

        # MikroTik vs Teltonika.
        fig, axes = plt.subplots(1, 2, figsize=(11.69, 8.27))
        fig.suptitle("MikroTik Versus Teltonika RUT956 Reference", fontsize=17, weight="bold", y=0.95)
        labels = ["R3 night\nLTE1", "R3 night\nLTE2", "R99 morning\nLTE1", "R99 morning\nLTE2", "RUT956\nreference"]
        speed_vals = [
            speed(BY_KEY["r3_outdoor_night"], "lte1"),
            speed(BY_KEY["r3_outdoor_night"], "lte2"),
            speed(BY_KEY["r99_outdoor_morning"], "lte1"),
            speed(BY_KEY["r99_outdoor_morning"], "lte2"),
            REFERENCE["speed_avg"],
        ]
        colors = ["#2F6B9A", "#D98B2B", "#2F6B9A", "#D98B2B", "#4D7C4A"]
        axes[0].bar(range(len(labels)), speed_vals, color=colors)
        axes[0].set_title("Average upload speed", fontsize=13, weight="bold")
        axes[0].set_ylabel("Mbit/s")
        axes[0].set_xticks(range(len(labels)))
        axes[0].set_xticklabels(labels)
        axes[0].grid(axis="y", alpha=0.25)
        axes[0].set_ylim(0, 13)
        for i, v in enumerate(speed_vals):
            axes[0].text(i, v + 0.25, fmt(v, 1), ha="center", fontsize=8)

        sig_labels = ["R99 morning\nLTE1", "R99 morning\nLTE2", "RUT956\nreference"]
        x = range(len(sig_labels))
        width = 0.35
        rsrq_vals = [sig(BY_KEY["r99_outdoor_morning"], "lte1", "rsrq"), sig(BY_KEY["r99_outdoor_morning"], "lte2", "rsrq"), REFERENCE["rsrq"]]
        sinr_vals = [sig(BY_KEY["r99_outdoor_morning"], "lte1", "sinr"), sig(BY_KEY["r99_outdoor_morning"], "lte2", "sinr"), REFERENCE["sinr"]]
        axes[1].bar([i - width / 2 for i in x], rsrq_vals, width, label="RSRQ dB", color="#637083")
        axes[1].bar([i + width / 2 for i in x], sinr_vals, width, label="SINR dB", color="#A84D46")
        axes[1].axhline(0, color="#777777", linewidth=0.8)
        axes[1].set_title("Signal quality where comparable", fontsize=13, weight="bold")
        axes[1].set_xticks(list(x))
        axes[1].set_xticklabels(sig_labels)
        axes[1].set_ylabel("dB")
        axes[1].grid(axis="y", alpha=0.25)
        axes[1].legend(frameon=False)
        for i, v in enumerate(rsrq_vals):
            axes[1].text(i - width / 2, v - 0.8, fmt(v, 1), ha="center", fontsize=8)
        for i, v in enumerate(sinr_vals):
            axes[1].text(i + width / 2, v + 0.5, fmt(v, 1), ha="center", fontsize=8)
        fig.text(0.06, 0.02, "The RUT956 signal values were manually captured: SINR 14 dB, RSRQ -10 dB, RSSI -72 dBm, RSRP -102 dBm. Its upload test was single-path.", fontsize=9, color="#556070")
        save_page(pdf, fig)

        speed_rows = []
        for s in SUMMARIES:
            run = s["run"]
            speed_rows.append(
                [
                    short_label(run.label),
                    short_pattern(run.pattern),
                    f"{s['success']['lte1']}/30",
                    fmt(s["speed"]["lte1"]["avg"], 2),
                    fmt(s["speed"]["lte1"]["median"], 2),
                    f"{s['success']['lte2']}/30",
                    fmt(s["speed"]["lte2"]["avg"], 2),
                    fmt(s["speed"]["lte2"]["median"], 2),
                ]
            )
        speed_rows.append([
            "RUT956 reference",
            "10 x single",
            "10/10",
            fmt(REFERENCE["speed_avg"], 2),
            fmt(REFERENCE["speed_median"], 2),
            "n/a",
            "n/a",
            "n/a",
        ])
        table_page(
            pdf,
            "Overview Table: Upload Results",
            "Average and median speed are in Mbit/s. LTE1 and LTE2 are kept separate.",
            ["Run", "Pattern", "LTE1 ok", "LTE1 avg", "LTE1 med", "LTE2 ok", "LTE2 avg", "LTE2 med"],
            speed_rows,
            font_size=8,
        )

        sig_rows = []
        for s in SUMMARIES:
            run = s["run"]
            for iface in ["lte1", "lte2"]:
                sig_rows.append(
                    [
                        short_label(run.label),
                        iface.upper(),
                        fmt(sig(s, iface, "sinr"), 2),
                        fmt(sig(s, iface, "rsrq"), 2),
                        fmt(sig(s, iface, "rsrp"), 1),
                        fmt(sig(s, iface, "rssi"), 1),
                        fmt(sig(s, iface, "cqi"), 2),
                    ]
                )
        sig_rows.append([
            "RUT956 reference",
            "single",
            fmt(REFERENCE["sinr"], 2),
            fmt(REFERENCE["rsrq"], 2),
            fmt(REFERENCE["rsrp"], 1),
            fmt(REFERENCE["rssi"], 1),
            "n/a",
        ])
        table_page(
            pdf,
            "Overview Table: Signal Quality",
            "Averages from RouterOS telemetry for MikroTik runs. RUT956 values were captured manually.",
            ["Run", "Path", "SINR dB", "RSRQ dB", "RSRP dBm", "RSSI dBm", "CQI"],
            sig_rows,
            font_size=7.8,
        )

        fig, ax = new_page(pdf, "Conclusion: Current Best Router", "Does the data show one router that is clearly better?")
        add_wrapped(
            ax,
            """
            The current data does not justify declaring one specific router as clearly and universally better. The strongest statement is narrower: under the tested outdoor/night or early-morning conditions, both MikroTik platforms can produce usable upload speeds, but their per-modem consistency differs.

            R3_7.6 has the best balanced outdoor result in the present dataset: 10.08 Mbit/s on LTE1 and 11.43 Mbit/s on LTE2 during the night six-hour test, with the best RSRQ values of the MikroTik runs. This makes R3_7.6 the strongest current candidate if the question is balanced two-modem behavior in quiet network conditions.

            R99 is not clearly worse. The early-morning R99 outdoor run reached 6.98 Mbit/s on LTE1 and 10.21 Mbit/s on LTE2, and its LTE2 path is competitive with the best R3 and RUT956 reference results. However, R99 showed a much weaker previous evening outdoor run, so it appears more sensitive to signal quality, cell loading, or modem/cell selection.

            The Teltonika RUT956 reference is competitive on the single tested path and had the best captured SINR. But because only one upload path was measured and firmware/modem details were not captured, it should be treated as a reference benchmark rather than a final winner.

            Recommendation for future tests: add new routers using the same per-modem method, keep the same files and upload endpoints, capture router FW and LTE modem FW at the start, and run at least one same-time back-to-back comparison window. A clear winner should require both modem paths to outperform alternatives under comparable cell-load conditions.
            """,
            y=0.78,
            width=92,
            size=10.4,
        )
        save_page(pdf, fig)

        fig, ax = new_page(pdf, "Technical Interpretation", "How to read the results for remote-controlled vehicle router installation")
        add_wrapped(
            ax,
            """
            1. RSRQ is the strongest common signal-quality indicator in this data. When RSRQ improved from roughly -13 to -10 dB, upload speed improved substantially. This is visible both on R99 between evening and morning outdoor runs, and on R3 between evening and night outdoor runs.

            2. RSRP and RSSI are not enough. Several slower runs had similar or even stronger received power than faster runs. Stronger RSSI can include interference, so it can look good while SINR and throughput remain poor.

            3. SINR matters, but only R99 exposed it in these MikroTik captures. R99 morning improved from very poor SINR to slightly less poor SINR, while speed improved much more than the SINR change alone would predict. That points to cell load as an additional factor.

            4. Test timing matters. The best R3 and R99 outdoor results were obtained during night or early morning windows. For remote-controlled cars, this means a vehicle that works acceptably during quiet periods may still underperform during loaded-cell periods.

            5. For field installation, evaluate each modem path independently. A dual-LTE router can hide one weak modem if only aggregate traffic is inspected. Per-modem upload, RSRQ/SINR, band/cell identity, and antenna placement should be reviewed together.

            Practical recommendation: use outdoor antennas, separate and orient them carefully, record RSRQ and SINR where possible, and repeat tests at both quiet and busy times. Treat RSRQ worse than about -12 dB or SINR below about 5 dB as a warning sign for upload reliability in real remote-control video/telemetry use.
            """,
            y=0.78,
            width=92,
            size=10.4,
        )
        save_page(pdf, fig)

        metadata = pdf.infodict()
        metadata["Title"] = "LTE Upload Performance and Signal Quality Comparison"
        metadata["Author"] = "OpenClaw / Ari"
        metadata["Subject"] = "MikroTik R99, MikroTik R3_7.6, and Teltonika RUT956 LTE upload comparison"
        metadata["Keywords"] = "LTE, MikroTik, Teltonika, RUT956, R99, R3, RSRQ, SINR, upload"


def main():
    pdf_path = OUT_DIR / "lte_upload_router_comparison_whitepaper_20260701.pdf"
    make_pdf(pdf_path)
    print(pdf_path)


if __name__ == "__main__":
    main()
