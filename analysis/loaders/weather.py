from __future__ import annotations

import re
from typing import Optional, List
from bs4 import BeautifulSoup


class WeatherData:
    global_solar_radiation_w_m2: Optional[float]
    atmospheric_counter_radiation_w_m2: Optional[float]
    longwave_outgoing_radiation_w_m2: Optional[float]
    average_relative_humidity_percent: Optional[float]
    current_precip_mm_per_min: Optional[float]

    def __init__(self,
        global_solar_radiation_w_m2: Optional[float],
        atmospheric_counter_radiation_w_m2: Optional[float],
        longwave_outgoing_radiation_w_m2: Optional[float],
        average_relative_humidity_percent: Optional[float],
        current_precip_mm_per_min: Optional[float]
    ):
        self.global_solar_radiation_w_m2 = global_solar_radiation_w_m2
        self.atmospheric_counter_radiation_w_m2 = atmospheric_counter_radiation_w_m2
        self.longwave_outgoing_radiation_w_m2 = longwave_outgoing_radiation_w_m2
        self.average_relative_humidity_percent = average_relative_humidity_percent
        self.current_precip_mm_per_min = current_precip_mm_per_min

    def get_global_solar_radiation(self) -> Optional[float]:
        return self.global_solar_radiation_w_m2

    def get_atmospheric_counter_radiation(self) -> Optional[float]:
        return self.atmospheric_counter_radiation_w_m2

    def get_longwave_outgoing_radiation(self) -> Optional[float]:
        return self.longwave_outgoing_radiation_w_m2

    def get_average_relative_humidity(self) -> Optional[float]:
        return self.average_relative_humidity_percent

    def get_current_precipitation(self) -> Optional[float]:
        return self.current_precip_mm_per_min


_FLOAT_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


def _extract_first_float(text: str) -> Optional[float]:
    match = _FLOAT_RE.search(text)
    if match:
        try:
            return float(match.group(0))
        except ValueError:
            return None
    return None


def _extract_all_floats(text: str) -> List[float]:
    values = []
    for m in _FLOAT_RE.finditer(text):
        try:
            values.append(float(m.group(0)))
        except ValueError:
            continue
    return values


def weather_data_from_html(html_data: str) -> WeatherData:
    soup = BeautifulSoup(html_data, 'html.parser')

    # Initialize values
    global_rad = atmos_counter = longwave_out = avg_humidity = precip_current = None

    # 1. Radiation table (Strahlungswerte)
    # Find a table whose first header cell (after a row with colspan text) contains 'Globalstr.'
    for tbl in soup.find_all('table'):
        header_b_tags = tbl.find_all('b')
        header_texts = [b.get_text(strip=True) for b in header_b_tags]
        if any('Globalstr.' in t for t in header_texts) and any('Atmos.Gegenstr.' in t for t in header_texts):
            # The data row should be the row after the header row listing the <b> labels.
            rows = tbl.find_all('tr')
            if len(rows) >= 2:
                # Identify the header row containing the radiation labels
                label_row = None
                for r in rows:
                    if r.find('b') and 'Globalstr.' in r.get_text():
                        label_row = r
                        break
                if label_row:
                    # Data row is next sibling tr
                    data_row = label_row.find_next_sibling('tr')
                    if data_row:
                        cells = data_row.find_all('td')
                        if len(cells) >= 4:
                            global_rad = _extract_first_float(cells[0].get_text())
                            atmos_counter = _extract_first_float(cells[2].get_text())
                            longwave_out = _extract_first_float(cells[3].get_text())
            break  # Stop after first matching table

    # 2. Relative humidity row in profile table (Profilwerte)
    # Identify table containing 'Profilwerte' then find row with 'Relative Feuchte'
    for tbl in soup.find_all('table'):
        if 'Profilwerte' in tbl.get_text():
            rh_row = None
            for r in tbl.find_all('tr'):
                if r.find('b') and 'Relative Feuchte' in r.get_text():
                    rh_row = r
                    break
            if rh_row:
                rh_vals = []
                # Skip first cell (label)
                for td in rh_row.find_all('td')[1:]:
                    val = _extract_first_float(td.get_text())
                    if val is not None:
                        rh_vals.append(val)
                if rh_vals:
                    avg_humidity = sum(rh_vals) / len(rh_vals)
            break

    # 3. Current precipitation (Niederschlag aktuell) in 'Sonstige Messwerte'
    for tbl in soup.find_all('table'):
        if 'Sonstige Messwerte' in tbl.get_text():
            # Find header row containing Niederschlag aktuell
            header_row = None
            for r in tbl.find_all('tr'):
                if 'Niederschlag' in r.get_text() and 'aktuell' in r.get_text():
                    header_row = r
                    break
            if header_row:
                data_row = header_row.find_next_sibling('tr')
                if data_row:
                    # Determine which cell corresponds to current precipitation by matching pattern
                    headers = header_row.find_all('td')
                    data_cells = data_row.find_all('td')
                    for idx, h in enumerate(headers):
                        h_text = h.get_text()
                        if 'Niederschlag' in h_text and 'aktuell' in h_text and idx < len(data_cells):
                            precip_current = _extract_first_float(data_cells[idx].get_text())
                            break
            break

    return WeatherData(
        global_solar_radiation_w_m2=global_rad,
        atmospheric_counter_radiation_w_m2=atmos_counter,
        longwave_outgoing_radiation_w_m2=longwave_out,
        average_relative_humidity_percent=avg_humidity,
        current_precip_mm_per_min=precip_current,
    )


def weather_data_from_file(file_path: str) -> WeatherData:
    print("Loading Weather data from file:", file_path)
    with open(file_path, 'r', encoding='utf-8') as f:
        html_data = f.read()
    return weather_data_from_html(html_data)
