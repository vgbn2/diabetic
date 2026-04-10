import pdfplumber
import pandas as pd
import numpy as np
import argparse
from pathlib import Path
from datetime import datetime, timedelta
import re
from diabetic.ingestion.offline.vision_parser.render_engine import PDFRenderer
from diabetic.ingestion.offline.vision_parser.icon_detector import IconDetector

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
        self.pdf_path    = Path(pdf_path)
        self.data_points = []
        self._renderer   = None
        self._detector   = IconDetector()

    def _crop_safe(self, bbox):
        """Clamps a bounding box to be strictly within the current page boundaries."""
        px0, py0, px1, py1 = self.page.bbox
        x0, y0, x1, y1 = bbox
        return (
            max(px0, min(px1, x0)),
            max(py0, min(py1, y0)),
            max(px0, min(px1, x1)),
            max(py0, min(py1, y1))
        )

    def parse(self):
        # 1. Automated Normalization for Share reports
        active_path = self.pdf_path
        with pdfplumber.open(self.pdf_path) as pdf:
            if len(pdf.pages) == 1 and pdf.pages[0].height > 2000:
                print(f"Detected Ottai Share format. Attempting automated normalization...")
                try:
                    from diabetic.ingestion.offline.normalize_ottai_share import normalize_share_report
                    norm_path = normalize_share_report(self.pdf_path)
                    if norm_path and norm_path.exists():
                        active_path = norm_path
                        print(f"Normalization successful. Switched to: {active_path.name}")
                except ImportError:
                    print("ERROR: normalize_ottai_share.py not found. Cannot parse large Share PDF.")
                    return []

        print(f"parsing: {active_path.name}")
        self._renderer = PDFRenderer(active_path)
        
        with pdfplumber.open(active_path) as pdf:
            for i, page in enumerate(pdf.pages):
                self._process_page(page, i)
        return self.data_points

    def _process_page(self, page_obj, page_idx):
        # Use a strict bounding box to localize coordinates and prevent ghosting
        self.page = page_obj.within_bbox(page_obj.cropbox)
        
        text   = self.page.extract_text() or ""
        words  = self.page.extract_words()
        curves = self.page.curves

        year_match  = re.search(r"\b(202\d)\b", text)
        global_year = int(year_match.group(1)) if year_match else datetime.now().year

        date_pattern = r"\b(\d{1,2}\s+(?:Th\d{2}|thg\s+\d{1,2}))\b"
        matches      = list(re.finditer(date_pattern, text))

        # Task 1: Position-aware date word lookup
        # Map character offsets to word indices to handle duplicate dates
        word_spans = []
        curr_pos = 0
        for i, w in enumerate(words):
            word_spans.append((curr_pos, curr_pos + len(w['text'])))
            curr_pos += len(w['text']) + 1 # +1 for the space assumed by rejoin

        reconstructed_text = " ".join([w['text'] for w in words])
        matches = list(re.finditer(date_pattern, reconstructed_text))

        raw_headers = []
        for match in matches:
            date_str = match.group(1)
            dt = parse_vn_date(f"{date_str} {global_year}")
            if not dt:
                continue

            # Map the match offset to the start word index
            match_start = match.start()
            start_word_idx = 0
            for i, span in enumerate(word_spans):
                if span[0] <= match_start < span[1]:
                    start_word_idx = i
                    break

            date_parts = date_str.replace(',', '').split()
            found_coords = None
            # Search for the consecutive words starting from the mapped index (Fix 1)
            for i in range(start_word_idx, min(start_word_idx + 10, len(words) - len(date_parts) + 1)):
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
                         if row_idx + 1 < len(rows) else self.page.height)

            agp_words = [w for w in words if "AGP" in w['text'] and w['top'] > y_start]
            agp_stop  = min(w['top'] for w in agp_words) - 5 if agp_words else self.page.bbox[3]

            # FIX 1: the original y_end clipped the last row on a page too tightly
            # because next_y == page.height and agp_stop could be very small
            # if an "AGP" word appeared elsewhere. Add an explicit floor: y_end
            # must be at least 80 pts below y_start (a chart can't be shorter than that).
            y_end = max(min(next_y, agp_stop), y_start + 80)

            # Fix 3: Exclude report header row (AGP section)
            # Row 0 usually spans > 2000 pts in Share format if misidentified.
            # Normal A4 charts are usually 250-400 pts high.
            if (y_end - y_start) > 2000:
                print(f"Skipping possible header/AGP row: y={y_start:.0f}-{y_end:.0f} (height={y_end-y_start:.0f})")
                continue

            # Local Scale Search first
            row_labels = [
                w for w in words
                if y_start < w['top'] < y_end
                and w['text'] in ['0', '10', '30']
                and w['x0'] < 100
            ]

            # Global Scale Scanner Fallback for sparse reports
            if not row_labels:
                x0, y0, x1, y1 = self.page.bbox
                # Scan full width for labels
                search_box = self._crop_safe((x0, y0, x1, y1))
                all_page_labels = self.page.within_bbox(search_box).extract_words()
                row_labels = [w for w in all_page_labels if w['text'] in ['0', '10', '30']]

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
            elif 0 in y_map and 30 in y_map:
                pts_per_mmol = (y_map[0] - y_map[30]) / 30.0
                zero_y       = y_map[0]
            elif 10 in y_map:
                pts_per_mmol = 1.38 # Best guess for standard scale
                zero_y       = y_map[10] + 10.0 * pts_per_mmol
            elif 0 in y_map:
                pts_per_mmol = 1.38
                zero_y       = y_map[0]
            elif 30 in y_map:
                pts_per_mmol = 1.38
                zero_y       = y_map[30] + 30.0 * pts_per_mmol
            else:
                if not y_map:
                    continue
                pts_per_mmol = 1.38
                # Fallback zero_y should be near the bottom of a standard chart area
                # if nothing else is found.
                zero_y = y_start + (y_end - y_start) * 0.8 

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
                # Glucose Blue variants
                if (bc > 0.8 and gc > 0.3 and rc < 0.4) or (bc > 0.9 and rc > 0.8):
                    return "glucose"
                
                for ref in CH_GLUCOSE_RGB:
                    if abs(rc - ref[0]) < 0.05 and abs(gc - ref[1]) < 0.05 and abs(bc - ref[2]) < 0.05:
                        return "glucose"

                if gc > 0.45 and rc < 0.4  and bc < 0.5: return "bolus"
                if rc > 0.4  and bc > 0.4  and gc < 0.5: return "basal"
                if rc > 0.7  and gc > 0.6  and bc < 0.5: return "meal"
                return "unknown"

            row_glucose_curves = []
            row_pivots         = []

            # Gather all vector objects (curves and lines)
            all_vectors = curves + self.page.lines

            for c in all_vectors:
                # Normalize lines into pts structure
                if 'pts' in c:
                    pts = c['pts']
                else:
                    pts = [(c['x0'], c['top']), (c['x1'], c['bottom'])]
                    c['pts'] = pts
                
                if not pts:
                    continue
                
                # Slicing Filter: Process curve if any part is within the row's vertical range
                ys_all = [p[1] for p in pts]
                c_top, c_bot = min(ys_all), max(ys_all)
                if c_bot < y_start - 5 or c_top > y_end + 5:
                    continue

                channel = get_metabolic_channel(c)
                if channel == "unknown":
                    continue

                xs    = [p[0] for p in pts]
                ys    = [p[1] for p in pts]
                width = max(xs) - min(xs)
                var_y = np.var(ys)

                if channel == "glucose":
                    row_glucose_curves.append(c)
                else:
                    row_pivots.append({'type': channel, 'x': np.mean(xs), 'y': np.mean(ys)})

            # --- Vision Extraction Integration ---
            # Render page and detect icons that vector engine might miss
            try:
                img_bgr = self._renderer.render_page(page_idx)
                masks = self._renderer.generate_masks(img_bgr)
                
                # Detect and sync coordinates (Divide by 8.0 for 576 DPI -> 72 DPI points)
                for cX, cY in self._detector.detect_centroids(masks["syringe"]):
                    ptX, ptY = cX / 8.0, cY / 8.0
                    if y_start - 30 < ptY < y_end + 60:
                        # Deduplicate against vector engine bolus/basal
                        if not any(abs(p['x'] - ptX) < 10 and abs(p['y'] - ptY) < 10 for p in row_pivots):
                            row_pivots.append({'type': 'bolus', 'x': ptX, 'y': ptY})
                
                for cX, cY in self._detector.detect_centroids(masks["meal"]):
                    ptX, ptY = cX / 8.0, cY / 8.0
                    if y_start - 30 < ptY < y_end + 60:
                        if not any(abs(p['x'] - ptX) < 10 and abs(p['y'] - ptY) < 10 for p in row_pivots):
                            row_pivots.append({'type': 'meal', 'x': ptX, 'y': ptY})
                            
            except Exception as e:
                print(f"Vision engine warning on page {page_idx}: {e}")

            # Fix 2: Curve concatenation for small glucose segments
            concatenated_glucose = []
            if row_glucose_curves:
                # Sort by x coordinate
                row_glucose_curves.sort(key=lambda c: min(p[0] for p in c['pts']))
                
                # Chain segments together
                curr_chain = list(row_glucose_curves[0]['pts'])
                for i in range(1, len(row_glucose_curves)):
                    prev_x1 = curr_chain[-1][0]
                    prev_y1 = curr_chain[-1][1]
                    next_pts = row_glucose_curves[i]['pts']
                    next_x0 = next_pts[0][0]
                    next_y0 = next_pts[0][1]
                    
                    # If start of next is close to end of current (within 5 pts)
                    if abs(next_x0 - prev_x1) < 5 and abs(next_y0 - prev_y1) < 5:
                        curr_chain.extend(next_pts)
                    else:
                        # Evaluate completed chain
                        ch_xs = [p[0] for p in curr_chain]
                        ch_ys = [p[1] for p in curr_chain]
                        width = max(ch_xs) - min(ch_xs)
                        var_y = np.var(ch_ys)
                        if var_y > 0.1 and width > 20:
                            concatenated_glucose.append({'pts': curr_chain})
                        curr_chain = list(next_pts)
                
                # final chain
                ch_xs = [p[0] for p in curr_chain]
                ch_ys = [p[1] for p in curr_chain]
                if np.var(ch_ys) > 0.1 and (max(ch_xs) - min(ch_xs)) > 20:
                    concatenated_glucose.append({'pts': curr_chain})
            
            row_glucose_curves = concatenated_glucose

            for rect in self.page.rects:
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
                                if col_idx + 1 < len(row_headers) else self.page.width)
                x_end        = x_next_start - 5

                cell_time_labels = [
                    w for w in words
                    if y_start - 10 < w['top'] < y_end + 30
                    and x_start <= w['x0'] < x_end + 15
                    and re.match(r"^(?:\d{1,2}[:\s]\d{2}|\d{2})$", w['text'])
                ]

                if not cell_time_labels:
                    # FALLBACK for single-column or sparse reports:
                    # Use a wider margin to catch the chart start/end
                    left_x  = 50 
                    right_x = x_end - 20
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
                            if i < 10 and page_idx == 0:
                                print(f"DEBUG POINT: x={px:.1f}, y={py:.1f}, zero={zero_y:.1f}, glu={glucose:.2f}")
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
            
        # Deduplication: Remove exact duplicate rows and sort chronologically
        initial_len = len(df)
        df = df.drop_duplicates().sort_values('timestamp')
        
        df.to_csv(output_path, index=False)
        print(f"extracted {len(df)} points (cleaned {initial_len - len(df)} duplicates) -> {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf")
    parser.add_argument("--output", "-o",
                        default="ottai_data/processed/high_res_glucose.csv")
    args = parser.parse_args()

    hp = HighResGlucoseParser(args.pdf)
    hp.parse()
    hp.save_csv(args.output)