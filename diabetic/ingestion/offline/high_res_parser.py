import pdfplumber
import pandas as pd
import numpy as np
import argparse
from pathlib import Path
from datetime import datetime, timedelta
import re

VN_MONTH = {
    "Th01": 1, "Th1": 1, "thg 1": 1,
    "Th02": 2, "Th2": 2, "thg 2": 2,
    "Th03": 3, "Th3": 3, "thg 3": 3,
    "Th04": 4, "Th4": 4, "thg 4": 4,
    "Th05": 5, "Th5": 5, "thg 5": 5,
    "Th06": 6, "Th6": 6, "thg 6": 6,
    "Th07": 7, "Th7": 7, "thg 7": 7,
    "Th08": 8, "Th8": 8, "thg 8": 8,
    "Th09": 9, "Th9": 9, "thg 9": 9,
    "Th10": 10, "thg 10": 10,
    "Th11": 11, "thg 11": 11,
    "Th12": 12, "thg 12": 12,
}


def parse_vn_date(text: str) -> datetime:
    text = text.strip()
    m = re.match(r"(\d{1,2})\s+thg\s+(\d{1,2}),?\s*(\d{4})", text)
    if m:
        return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    m = re.match(r"(\d{1,2})\s+(Th\d{2})\s+(\d{4})", text)
    if m:
        month = VN_MONTH.get(m.group(2))
        if month:
            return datetime(int(m.group(3)), month, int(m.group(1)))
    return None


class HighResGlucoseParser:
    def __init__(self, pdf_path):
        self.pdf_path   = Path(pdf_path)
        self.data_points = []

    def parse(self):
        print(f"parsing: {self.pdf_path.name}")
        with pdfplumber.open(self.pdf_path) as pdf:
            for page in pdf.pages:
                self._process_page(page)
        return self.data_points

    def _process_page(self, page):
        text   = page.extract_text() or ""
        words  = page.extract_words()
        curves = page.curves

        year_match  = re.search(r"\b(202\d)\b", text)
        global_year = int(year_match.group(1)) if year_match else datetime.now().year

        date_pattern = r"\b(\d{1,2}\s+(?:Th\d{2}|thg\s+\d{1,2}))\b"
        matches      = list(re.finditer(date_pattern, text))

        raw_headers = []
        for match in matches:
            date_str = match.group(1)
            dt       = parse_vn_date(f"{date_str} {global_year}")
            if not dt:
                continue

            date_parts   = date_str.replace(',', '').split()
            found_coords = None
            for i in range(len(words) - len(date_parts) + 1):
                if all(words[i + k]['text'].replace(',', '') == date_parts[k]
                       for k in range(len(date_parts))):
                    found_coords = {
                        'x0':     words[i]['x0'],
                        'x1':     words[i + len(date_parts) - 1]['x1'],
                        'top':    words[i]['top'],
                        'bottom': words[i]['bottom'],
                    }
                    break

            if found_coords:
                if not any(
                    abs(h['coords']['top'] - found_coords['top']) < 2 and
                    abs(h['coords']['x0']  - found_coords['x0'])  < 2
                    for h in raw_headers
                ):
                    raw_headers.append({
                        'date': dt, 'coords': found_coords, 'date_str': date_str
                    })

        if not raw_headers:
            return

        raw_headers.sort(key=lambda x: x['coords']['top'])
        rows        = []
        current_row = [raw_headers[0]]
        for h in raw_headers[1:]:
            if abs(h['coords']['top'] - current_row[0]['coords']['top']) < 25:
                current_row.append(h)
            else:
                rows.append(current_row)
                current_row = [h]
        rows.append(current_row)

        for row_idx, row_headers in enumerate(rows):
            row_headers.sort(key=lambda x: x['coords']['x0'])

            y_start   = row_headers[0]['coords']['top']
            next_y    = (rows[row_idx + 1][0]['coords']['top']
                         if row_idx + 1 < len(rows) else page.height)

            agp_words = [w for w in words if "AGP" in w['text'] and w['top'] > y_start]
            agp_stop  = min(w['top'] for w in agp_words) - 5 if agp_words else page.height

            # FIX 1: the original y_end clipped the last row on a page too tightly
            # because next_y == page.height and agp_stop could be very small
            # if an "AGP" word appeared elsewhere. Add an explicit floor: y_end
            # must be at least 80 pts below y_start (a chart can't be shorter than that).
            y_end = max(min(next_y, agp_stop), y_start + 80)

            row_labels = [
                w for w in words
                if y_start < w['top'] < y_end
                and w['text'] in ['0', '10', '30']
                and w['x0'] < 100
            ]

            y_map = {}
            for lbl in row_labels:
                val = int(lbl['text'])
                y_map.setdefault(val, []).append(lbl['top'])
            for val in y_map:
                y_map[val] = np.mean(y_map[val])

            if 0 in y_map and 10 in y_map:
                pts_per_mmol = (y_map[0] - y_map[10]) / 10.0
                zero_y       = y_map[0]
            elif 10 in y_map and 30 in y_map:
                pts_per_mmol = (y_map[10] - y_map[30]) / 20.0
                zero_y       = y_map[10] + 10.0 * pts_per_mmol
            else:
                if not row_labels:
                    continue
                pts_per_mmol = 1.38
                zero_y       = y_start + 50

            CH_GLUCOSE_RGB = [
                (0.2314, 0.4706, 1.0),
                (1.0,    0.7216, 0.0),
                (1.0,    0.8667, 0.5294),
                (0.949,  0.1569, 0.1569),
                (1.0,    0.5686, 0.5686),
            ]

            def get_metabolic_channel(obj):
                color     = obj.get('stroking_color') or obj.get('non_stroking_color')
                pts_list  = obj.get('pts', [])
                pts_count = len(pts_list)
                col_str   = str(color)

                if pts_count > 100 or ('P' in col_str and pts_count > 80):
                    return "glucose"
                if 'P' in col_str:
                    if 'P50' in col_str:
                        return "bolus"
                    return "meal" if pts_count < 30 else "basal"
                if not isinstance(color, (list, tuple)) or len(color) < 3:
                    return "unknown"

                rc, gc, bc = color[:3]
                for ref in CH_GLUCOSE_RGB:
                    if abs(rc - ref[0]) < 0.05 and abs(gc - ref[1]) < 0.05 and abs(bc - ref[2]) < 0.05:
                        return "glucose"

                if gc > 0.45 and rc < 0.4  and bc < 0.5: return "bolus"
                if rc > 0.4  and bc > 0.4  and gc < 0.5: return "basal"
                if rc > 0.7  and gc > 0.6  and bc < 0.5: return "meal"
                return "unknown"

            row_glucose_curves = []
            row_pivots         = []

            for c in curves:
                pts = c.get('pts', [])
                if not pts:
                    continue
                ys_all = [p[1] for p in pts]
                c_top  = min(ys_all)
                c_bot  = max(ys_all)
                # FIX 2: widen the vertical search band for the last row on a page —
                # use +60 instead of +40 on the bottom so curves that bleed slightly
                # past y_end are still captured.
                if not (y_start - 30 < c_top < y_end + 60 or
                        y_start - 30 < c_bot < y_end + 60):
                    continue

                channel = get_metabolic_channel(c)
                if channel == "unknown":
                    continue

                xs    = [p[0] for p in pts]
                ys    = ys_all
                width = max(xs) - min(xs)
                var_y = np.var(ys)

                if channel == "glucose":
                    if var_y > 0.1 and width > 20:
                        row_glucose_curves.append(c)
                else:
                    row_pivots.append({'type': channel, 'x': np.mean(xs), 'y': np.mean(ys)})

            for rect in page.rects:
                if not (y_start - 30 < rect['top'] < y_end + 60):
                    continue
                channel = get_metabolic_channel(rect)
                if channel in ("bolus", "basal", "meal"):
                    row_pivots.append({
                        'type': channel,
                        'x':    (rect['x0'] + rect['x1']) / 2,
                        'y':    (rect['top'] + rect['bottom']) / 2,
                    })

            for col_idx, header in enumerate(row_headers):
                x_start      = max(0, header['coords']['x0'] - 10)
                x_next_start = (row_headers[col_idx + 1]['coords']['x0']
                                if col_idx + 1 < len(row_headers) else page.width)
                x_end        = x_next_start - 5

                cell_time_labels = [
                    w for w in words
                    if y_start - 10 < w['top'] < y_end + 30
                    and x_start <= w['x0'] < x_end + 15
                    and re.match(r"^(?:\d{1,2}[:\s]\d{2}|\d{2})$", w['text'])
                ]

                if not cell_time_labels:
                    left_x  = header['coords']['x0']
                    # FIX 3: for a single-column row (one day on the page), the
                    # fallback right_x of x0+50 was far too narrow — the chart
                    # could span hundreds of pts. Use x_end as the right boundary
                    # when there are no time labels instead.
                    right_x = x_end
                else:
                    left_x  = min(w['x0'] for w in cell_time_labels)
                    right_x = max(w['x1'] for w in cell_time_labels)

                day_data = []

                for curve in row_glucose_curves:
                    for px, py in curve['pts']:
                        if left_x - 3 <= px <= right_x + 3:
                            rel_x         = (px - left_x) / max(1, right_x - left_x)
                            total_minutes = max(0.0, min(1439.99, rel_x * 1440))
                            glucose       = (zero_y - py) / pts_per_mmol
                            if 0.5 < glucose < 40.0:
                                ts = header['date'] + timedelta(minutes=total_minutes)
                                day_data.append({
                                    'timestamp': ts,
                                    'glucose':   round(float(glucose), 3),
                                    'bolus': 0, 'basal': 0, 'meal': 0,
                                })

                for p in row_pivots:
                    if left_x - 3 <= p['x'] <= right_x + 3:
                        rel_x         = (p['x'] - left_x) / max(1, right_x - left_x)
                        total_minutes = max(0.0, min(1439.99, rel_x * 1440))
                        ts    = header['date'] + timedelta(minutes=total_minutes)
                        entry = {'timestamp': ts, 'glucose': np.nan,
                                 'bolus': 0, 'basal': 0, 'meal': 0}
                        if   p['type'] == 'bolus': entry['bolus'] = 1
                        elif p['type'] == 'basal': entry['basal'] = 1
                        elif p['type'] == 'meal':  entry['meal']  = 1
                        day_data.append(entry)

                self.data_points.extend(day_data)

    def save_csv(self, output_path):
        if not self.data_points:
            print("no data extracted.")
            return
        df = pd.DataFrame(self.data_points)
        if df.empty:
            print("no data after filtering.")
            return
        df = df.sort_values('timestamp')
        # Drop readings where glucose > 25 that appear in the first 2 hours (noise/calibration)
        df = df[~((df['glucose'] > 25) & (df['timestamp'] < df['timestamp'].min() + pd.Timedelta(hours=2)))]
        
        df.to_csv(output_path, index=False)
        print(f"extracted {len(df)} points → {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf")
    parser.add_argument("--output", "-o",
                        default="ottai_data/processed/high_res_glucose.csv")
    args = parser.parse_args()

    hp = HighResGlucoseParser(args.pdf)
    hp.parse()
    hp.save_csv(args.output)