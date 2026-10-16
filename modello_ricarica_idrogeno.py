"""
Modello energetico elettrico-idrogeno per la ricarica di 5 cargo-bike e 2 muletti.
Legge i profili da Excel, simula i flussi e genera grafici/report.

Dipendenze:
    pip install pandas numpy matplotlib openpyxl

IMPORTANTE:
- Il file Excel deve contenere colonne per timestamp/ora, carico LOAD (kW),
  irraggiamento e temperatura ambiente.
- L'irraggiamento può essere in W/m² oppure kW/m²: verificare SOLAR_INPUT_UNIT.
- Il modello PV usa una stima semplificata con NOCT e coefficiente termico.
- La conversione PEM è interpretata come 22 g H2/kWh (non g/kW).
- La logica di scheduling è euristica e orientata a massimizzare il numero:
  prima prova a completare le cargo-bike, poi i muletti. Non è una prova di
  ottimo globale. Per una soluzione certificata di massimo numero serve un MILP.
"""

from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# --------------------------- CONFIGURAZIONE ---------------------------

EXCEL_FILE = "dati test.xlsx"    # <-- inserire il nome/percorso del file Excel
SHEET_NAME = 0                   # nome del foglio oppure indice
DEADLINE = "07:00"               # ora limite, riferita al giorno finale dei dati
DT_H = 1 / 12                    # passo di simulazione: 5 minuti
START_BESS_SOC = 0.50
START_H2_KG = 1.50

PV_RATED_KW = 15.0
PEM_RATED_KW = 9.0
PEM_KG_PER_KWH = 0.022           # 22 g/kWh
H2_TANK_CAP_KG = 1.5
H2_TANK_IN_MAX_KG_H = 5.0
H2_TANK_OUT_MAX_KG_H = 5.0

BESS_CAP_KWH = 24.0
BESS_P_CH_MAX_KW = 25.0
BESS_P_DIS_MAX_KW = 25.0
BESS_ETA_CH = 0.95
BESS_ETA_DIS = 0.95
BESS_MIN_SOC = 0.0
BESS_MAX_SOC = 1.0

# Modello PV semplificato:
PV_NOCT_C = 45.0
PV_TEMP_COEFF = -0.004   # variazione relativa di potenza per °C rispetto a 25 °C
SOLAR_INPUT_UNIT = "W/m2"  # usare "kW/m2" se il foglio contiene kW/m²

# Potenza ausiliaria del PEM esclusa: aggiungere qui se nota.
PEM_MIN_LOAD_KW = 0.0
ALLOW_PEM_PART_LOAD = True

# --------------------------- LETTURA E NORMALIZZAZIONE ---------------------------

def find_col(df, candidates, required=True):
    """Trova una colonna ignorando maiuscole, spazi, accenti semplici e underscore."""
    norm = {str(c).strip().lower().replace(" ", "").replace("_", ""): c for c in df.columns}
    for cand in candidates:
        key = cand.strip().lower().replace(" ", "").replace("_", "")
        if key in norm:
            return norm[key]
    if required:
        raise ValueError(
            f"Colonna non trovata. Cercavo una tra {candidates}. "
            f"Colonne presenti: {list(df.columns)}"
        )
    return None

def load_profiles(path):
    df = pd.read_excel(path, sheet_name=SHEET_NAME)
    time_col = find_col(df, ["timestamp", "datetime", "dataora", "date_time", "data e ora", "ora", "time", "data"])
    load_col = find_col(df, [
        "P LOAD  [kW]",
        "P LOAD [kW]",
        "LOAD",
        "carico",
        "load_kw"
    ])

    irr_col = find_col(df, [
        "Irr PV [W(m2)",
        "irraggiamento",
        "irradiance",
        "ghi"
    ])

    temp_col = find_col(df, [
        "T PV [°C]",
        "temperatura",
        "temperatura ambiente",
        "temperature"
    ])

    raw_time = df[time_col]
    # Excel può avere timestamp completi oppure solo orari. Se sono orari,
    # si crea una sequenza temporale fittizia mantenendo l'ordine delle righe.
    parsed = pd.to_datetime(raw_time, errors="coerce")
    if parsed.notna().all():
        df["timestamp"] = parsed
    else:
        try:
            seconds = pd.to_timedelta(raw_time.astype(str))
            base = pd.Timestamp("2026-01-01")
            df["timestamp"] = base + seconds
        except Exception:
            raise ValueError("La colonna temporale non è interpretabile. Usare timestamp Excel o orari HH:MM.")

    out = pd.DataFrame({
        "timestamp": df["timestamp"],
        "load_kw": pd.to_numeric(df[load_col], errors="coerce"),
        "irradiance": pd.to_numeric(df[irr_col], errors="coerce"),
        "ambient_c": pd.to_numeric(df[temp_col], errors="coerce"),
    }).dropna().sort_values("timestamp").reset_index(drop=True)

    if len(out) < 2:
        raise ValueError("Servono almeno due righe temporali valide nel file Excel.")

    # Interpola i profili al passo DT_H, così il modello gestisce un passo regolare.
    out = out.set_index("timestamp")
    freq_min = max(1, int(round(DT_H * 60)))
    grid = pd.date_range(out.index.min(), out.index.max(), freq=f"{freq_min}min")
    out = out.reindex(out.index.union(grid)).sort_index().interpolate(method="time").reindex(grid)
    out.index.name = "timestamp"
    out = out.reset_index()

    if SOLAR_INPUT_UNIT.lower() == "w/m2":
        out["ghi_wm2"] = out["irradiance"].clip(lower=0)
    elif SOLAR_INPUT_UNIT.lower() == "kw/m2":
        out["ghi_wm2"] = out["irradiance"].clip(lower=0) * 1000
    else:
        raise ValueError('SOLAR_INPUT_UNIT deve essere "W/m2" oppure "kW/m2".')
    return out

# --------------------------- VEICOLI E MODELLO ---------------------------

def make_vehicles():
    vehicles = []
    for i in range(1, 6):
        vehicles.append({
            "vehicle": f"Cargo-bike {i}", "type": "cargo-bike",
            "capacity_kg": 0.100, "rate_kg_h": 0.5, "soc_kg": 0.0,
            "start": pd.NaT, "end": pd.NaT, "completed": False,
        })
    for i in range(1, 3):
        vehicles.append({
            "vehicle": f"Muletta {i}", "type": "muletto",
            "capacity_kg": 1.800, "rate_kg_h": 3.0, "soc_kg": 0.0,
            "start": pd.NaT, "end": pd.NaT, "completed": False,
        })
    return vehicles

def pv_power_kw(ghi_wm2, ambient_c):
    """Stima della potenza PV; non sostituisce i dati di potenza misurata dell'impianto."""
    cell_temp = ambient_c + (PV_NOCT_C - 20.0) * max(ghi_wm2, 0.0) / 800.0
    temp_factor = max(0.0, 1.0 + PV_TEMP_COEFF * (cell_temp - 25.0))
    return min(PV_RATED_KW, PV_RATED_KW * max(ghi_wm2, 0.0) / 1000.0 * temp_factor)

def simulate(profiles):
    vehicles = make_vehicles()
    n = len(profiles)
    dt = DT_H
    bess_kwh = BESS_CAP_KWH * START_BESS_SOC
    tank_kg = min(H2_TANK_CAP_KG, max(0.0, START_H2_KG))
    records = []
    deadline_h, deadline_m = map(int, DEADLINE.split(":"))
    last_date = profiles["timestamp"].iloc[-1].date()
    deadline_dt = pd.Timestamp(year=last_date.year, month=last_date.month, day=last_date.day,
                               hour=deadline_h, minute=deadline_m)
    # Se la deadline precede l'inizio dei dati per via della data, è fissata al giorno seguente.
    if deadline_dt < profiles["timestamp"].iloc[0]:
        deadline_dt += pd.Timedelta(days=1)

    for _, row in profiles.iterrows():
        ts = row["timestamp"]
        if ts > deadline_dt:
            break

        pv_kw = pv_power_kw(float(row["ghi_wm2"]), float(row["ambient_c"]))
        load_kw = max(0.0, float(row["load_kw"]))
        # Il carico è servito prima con PV, poi con energia già accumulata nel BESS.
        pv_to_load = min(pv_kw, load_kw)
        load_deficit = max(0.0, load_kw - pv_to_load)
        max_bess_dis = min(BESS_P_DIS_MAX_KW, bess_kwh * BESS_ETA_DIS / dt)
        bess_dis_kw = min(load_deficit, max_bess_dis)
        bess_kwh -= (bess_dis_kw / BESS_ETA_DIS) * dt
        load_unserved_kw = max(0.0, load_deficit - bess_dis_kw)

        pv_surplus_kw = max(0.0, pv_kw - pv_to_load)
        # Il PEM usa solo surplus PV residuo; non preleva energia dalla rete né dal BESS.
        pem_kw = min(PEM_RATED_KW, pv_surplus_kw)
        if pem_kw < PEM_MIN_LOAD_KW:
            pem_kw = 0.0
        if not ALLOW_PEM_PART_LOAD and pem_kw < PEM_RATED_KW:
            pem_kw = 0.0
        pem_h2_kg_h = pem_kw * PEM_KG_PER_KWH
        h2_produced_kg = pem_h2_kg_h * dt
        h2_to_tank_kg = min(h2_produced_kg, H2_TANK_IN_MAX_KG_H * dt,
                            max(0.0, H2_TANK_CAP_KG - tank_kg))
        h2_vented_kg = max(0.0, h2_produced_kg - h2_to_tank_kg)
        tank_kg += h2_to_tank_kg

        # Ricarica veicoli: prima le cargo-bike (massimizza il numero completabili),
        # poi i muletti. In ogni passo si può ricaricare più di un veicolo.
        h2_available = min(tank_kg, H2_TANK_OUT_MAX_KG_H * dt)
        h2_delivered_step = 0.0
        active_vehicles = []
        ordered = sorted(vehicles, key=lambda v: (0 if v["type"] == "cargo-bike" else 1,
                                                  v["capacity_kg"], v["vehicle"]))
        for v in ordered:
            remaining = v["capacity_kg"] - v["soc_kg"]
            if remaining <= 1e-9:
                continue
            # Avvio sessione solo se è disponibile idrogeno da erogare.
            max_this_vehicle = v["rate_kg_h"] * dt
            amount = min(remaining, max_this_vehicle, h2_available)
            if amount > 1e-12:
                if pd.isna(v["start"]):
                    v["start"] = ts
                v["soc_kg"] += amount
                h2_available -= amount
                h2_delivered_step += amount
                active_vehicles.append(v["vehicle"])
                if v["soc_kg"] >= v["capacity_kg"] - 1e-9:
                    v["soc_kg"] = v["capacity_kg"]
                    v["end"] = ts + pd.Timedelta(hours=dt)
                    v["completed"] = True

        tank_kg -= h2_delivered_step

        # La batteria si carica solo con surplus PV che rimane dopo il PEM.
        # Quindi nessuna energia di rete o del BESS alimenta il PEM.
        remaining_pv_kw = max(0.0, pv_surplus_kw - pem_kw)
        max_bess_ch = min(BESS_P_CH_MAX_KW,
                          max(0.0, (BESS_CAP_KWH - bess_kwh) / (BESS_ETA_CH * dt)))
        bess_ch_kw = min(remaining_pv_kw, max_bess_ch)
        bess_kwh += bess_ch_kw * BESS_ETA_CH * dt
        bess_kwh = min(BESS_CAP_KWH, max(0.0, bess_kwh))

        records.append({
            "timestamp": ts, "pv_kw": pv_kw, "load_kw": load_kw,
            "pv_to_load_kw": pv_to_load, "bess_dis_kw": bess_dis_kw,
            "bess_ch_kw": bess_ch_kw, "pem_kw": pem_kw,
            "load_unserved_kw": load_unserved_kw,
            "bess_soc": bess_kwh / BESS_CAP_KWH,
            "bess_kwh": bess_kwh, "h2_tank_kg": tank_kg,
            "h2_produced_kg_h": pem_h2_kg_h,
            "h2_to_tank_kg_h": h2_to_tank_kg / dt,
            "h2_vehicle_kg_h": h2_delivered_step / dt,
            "h2_vented_kg_h": h2_vented_kg / dt,
            "active_vehicles": ", ".join(active_vehicles),
            **{f"soc_{v['vehicle']}": v["soc_kg"] / v["capacity_kg"] for v in vehicles},
        })

    return pd.DataFrame(records), pd.DataFrame(vehicles)

# --------------------------- REPORT E GRAFICI ---------------------------

def make_plots(sim, vehicle_report):
    t = sim["timestamp"]
    # 1. Profili di potenza elettrica
    fig, ax = plt.subplots(figsize=(13, 5))
    for col, label in [
        ("pv_kw", "Fotovoltaico disponibile"),
        ("load_kw", "Carico LOAD"),
        ("pem_kw", "Elettrolizzatore PEM"),
        ("bess_ch_kw", "Carica BESS"),
        ("bess_dis_kw", "Scarica BESS"),
    ]:
        ax.plot(t, sim[col], label=label, linewidth=1.5)
    ax.set_ylabel("Potenza [kW]")
    ax.set_xlabel("Tempo")
    ax.set_title("Profili di potenza elettrica")
    ax.grid(True, alpha=0.3); ax.legend(ncol=2); fig.tight_layout()
    fig.savefig("01_profili_potenza.png", dpi=160)

    # 2. SOC dei veicoli
    fig, ax = plt.subplots(figsize=(13, 5))
    for col in [c for c in sim.columns if c.startswith("soc_") and c != "bess_soc"]:
        ax.plot(t, 100 * sim[col], label=col.replace("soc_", ""), linewidth=1.5)
    ax.set_ylabel("SOC veicolo [%]"); ax.set_ylim(0, 105)
    ax.set_xlabel("Tempo"); ax.set_title("Stato di carica dei veicoli")
    ax.grid(True, alpha=0.3); ax.legend(ncol=3); fig.tight_layout()
    fig.savefig("02_soc_veicoli.png", dpi=160)

    # 3. SOC BESS
    fig, ax = plt.subplots(figsize=(13, 4))
    ax.plot(t, 100 * sim["bess_soc"], label="SOC BESS", linewidth=2)
    ax.set_ylabel("SOC [%]"); ax.set_ylim(0, 105)
    ax.set_xlabel("Tempo"); ax.set_title("Stato di carica del BESS")
    ax.grid(True, alpha=0.3); ax.legend(); fig.tight_layout()
    fig.savefig("03_soc_bess.png", dpi=160)

    # 4. Flussi di idrogeno
    fig, ax = plt.subplots(figsize=(13, 5))
    for col, label in [
        ("h2_produced_kg_h", "Produzione PEM"),
        ("h2_to_tank_kg_h", "Ingresso serbatoio"),
        ("h2_vehicle_kg_h", "Uscita verso veicoli"),
        ("h2_vented_kg_h", "Produzione non immagazzinata"),
    ]:
        ax.plot(t, sim[col], label=label, linewidth=1.5)
    ax.set_ylabel("Portata H₂ [kg/h]"); ax.set_xlabel("Tempo")
    ax.set_title("Flussi di idrogeno"); ax.grid(True, alpha=0.3)
    ax.legend(ncol=2); fig.tight_layout()
    fig.savefig("04_flussi_idrogeno.png", dpi=160)

    # 5. Massa di H2 nel serbatoio
    fig, ax = plt.subplots(figsize=(13, 4))
    ax.plot(t, sim["h2_tank_kg"], label="H₂ nel serbatoio", linewidth=2)
    ax.axhline(H2_TANK_CAP_KG, linestyle="--", label="Capacità serbatoio")
    ax.set_ylabel("Massa H₂ [kg]"); ax.set_xlabel("Tempo")
    ax.set_title("Inventario del serbatoio di idrogeno")
    ax.grid(True, alpha=0.3); ax.legend(); fig.tight_layout()
    fig.savefig("05_inventario_h2.png", dpi=160)
    plt.show()

def main():
    path = Path(EXCEL_FILE)
    if not path.exists():
        raise FileNotFoundError(
            f"Non trovo '{EXCEL_FILE}'. Salva il foglio Excel nella stessa cartella "
            "dello script oppure modifica EXCEL_FILE."
        )

    profiles = load_profiles(path)
    sim, vehicles = simulate(profiles)
    make_plots(sim, vehicles)

    # Riepilogo orari e risultato
    vehicles["start"] = pd.to_datetime(vehicles["start"])
    vehicles["end"] = pd.to_datetime(vehicles["end"])
    vehicles["SOC_finale_%"] = 100 * vehicles["soc_kg"] / vehicles["capacity_kg"]
    vehicles["H2_richiesto_kg"] = vehicles["capacity_kg"]
    vehicles["H2_caricato_kg"] = vehicles["soc_kg"]
    vehicles["sessione_completata"] = vehicles["completed"]
    report_cols = ["vehicle", "capacity_kg", "rate_kg_h", "H2_caricato_kg",
                   "SOC_finale_%", "start", "end", "sessione_completata"]
    print("\n=== RISULTATO PER VEICOLO ===")
    print(vehicles[report_cols].to_string(index=False))
    print(f"\nVeicoli completamente caricati: {int(vehicles['completed'].sum())}/7")
    print(f"Idrogeno erogato ai veicoli: {sim['h2_vehicle_kg_h'].sum() * DT_H:.3f} kg")
    print(f"Energia PEM consumata: {sim['pem_kw'].sum() * DT_H:.3f} kWh")
    print(f"Energia PV prodotta (stima): {sim['pv_kw'].sum() * DT_H:.3f} kWh")
    print(f"Energia LOAD richiesta: {sim['load_kw'].sum() * DT_H:.3f} kWh")
    print(f"Carico non servito cumulato: {sim['load_unserved_kw'].sum() * DT_H:.3f} kWh")
    print(f"SOC finale BESS: {100 * sim['bess_soc'].iloc[-1]:.1f}%")
    print(f"H2 finale serbatoio: {sim['h2_tank_kg'].iloc[-1]:.3f} kg")

    sim.to_csv("risultati_simulazione.csv", index=False)
    vehicles[report_cols].to_csv("riepilogo_veicoli.csv", index=False)
    print("\nFile generati: risultati_simulazione.csv, riepilogo_veicoli.csv")
    print("Grafici: 01_profili_potenza.png ... 05_inventario_h2.png")

if __name__ == "__main__":
    main()
