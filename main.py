import datetime

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# ==========================================
# 1. CARICAMENTO DATI E INIZIALIZZAZIONE
# ==========================================
df = pd.read_excel('dati test.xlsx')
n_steps = len(df)
dt = 0.25  # Intervalli di 15 minuti in ore

# Parametri di sistema
pv_peak = 15.0
grid_limit = 9.0
pod_en = 0.0
load_en = 0.0
pv_en = 0.0

bess_cap = 24.0
bess_p_max = 25.0
initial_bess_soc = 0.0  # (50% - Target fine/inizio giornata)
bess_soc = initial_bess_soc
bess_en = 0.0

h2_store_cap = 1500
h2_store_flow_max = 4000  # g/h = 83.33 g/min
initial_h2_mass = h2_store_cap * 0.0  # g (100% - Target fine/inizio giornata)
h2_store_mass = initial_h2_mass
h2_store_flow = 0.0     # FLusso istantaneo

el_p_max = 9.0  # Potenza massima nominale EL = 9 kW
el_eff = 22.0   # g/kWh (22 g/kW)
h2_flow_EL = 0.0
h2_flow_av_EL = el_p_max * el_eff  # Caso in cui non ho limiti sull'elettrolizzatore
el_en = 0.0

# Flotta veicoli inizialmente completamente scarichi (SOC = 0.0)
vehicles = []
for i in range(5):
    vehicles.append({
        'id': f'CargoBike_{i + 1}',
        'cap': 100,  # g
        'rate': 500,  #  g/h = 8.33 g/min
        'soc': 1.0,
        'flow': 0.0,
        'start_time': None,
        'end_time': None,
        'charging_minutes': 0.0
    })
for i in range(2):
    vehicles.append({
        'id': f'Forklift_{i + 1}',
        'cap': 1800.0,  # g
        'rate': 3000.0,  # g/h = 50.0 g/min
        'soc': 1.0,
        'flow': 0.0,
        'start_time': None,
        'end_time': None,
        'charging_minutes': 0.0
    })

results = []

# Registrazione dello stato iniziale (00:00)
first_row = df.iloc[0]
ora_val = first_row['Ora']
ora_str = f"{ora_val.hour:02d}:{ora_val.minute:02d}" if hasattr(ora_val, 'hour') else str(ora_val)[:5]

step_init = {
    'Ora': ora_str,
    'P_LOAD_kW': 0.0,
    'P_PV_kW': 0.0,
    'Grid_Power_kW': 0.0,
    'BESS_Power_kW': 0.0,
    'Electrolyzer_Power_kW': 0.0,
    'BESS_SOC_kWh': bess_soc * bess_cap,
    'BESS_SOC_Percent': bess_soc * 100.0,
    'H2_Storage_kg': h2_store_mass,
    'H2_Storage_Percent': (h2_store_mass / h2_store_cap) * 100.0,
    'H2_Produced_kg': 0.0,
    'H2_Dispensed_Total_kg': 0.0,
    'H2_flow_EL': 0.0,
    'H2_flow_H2S': 0.0,
    'H2_flow_H2V': 0.0,
}
for v in vehicles:
    step_init[f"{v['id']}_SOC_kg"] = v['soc']
    step_init[f"{v['id']}_SOC_Percent"] = (v['soc'] / v['cap']) * 100.0
    v['soc_history'] = [100]

results.append(step_init)

# ==========================================
# 2. CICLO DI SIMULAZIONE TEMPORALE
# ==========================================
for idx, row in df.iloc[1:].iterrows():
    load = row['P LOAD  [kW]']
    irr = row['Irr PV [W(m2)']
    temp = row['T PV [°C]']
    ora_val = row['Ora']

    if hasattr(ora_val, 'hour') and hasattr(ora_val, 'minute'):
        current_total_minutes = ora_val.hour * 60 + ora_val.minute
        ora_str = f"{ora_val.hour:02d}:{ora_val.minute:02d}"
    else:
        h_parts = list(map(int, str(ora_val).split(':')[:2]))
        current_total_minutes = h_parts[0] * 60 + h_parts[1]
        ora_str = str(ora_val)[:5]

    # Modellazione PV con correzione termica
    t_cell = temp + irr * 0.03
    pv_gen = max(0.0, pv_peak * (irr / 1000.0) * (1.0 - 0.004 * (t_cell - 25.0)))
    pv_energy = pv_gen * dt  # kWh

    is_h2_priority_window = (current_total_minutes < 420)
    active_vehicles = [v for v in vehicles if v['cap'] - v['soc'] > 1e-4] if is_h2_priority_window else []

    el_power = 0.0
    h2_produced = 0.0
    bess_power = 0.0
    grid_power = 0.0

    h2_dispensed_step = 0.0     # Todo: To delete

    h2_store_flow = 0.0
    h2_flow_EL = 0.0
    h2_flow_H2V = 0.0

    h2_flow_av_EL = el_p_max * el_eff  # Caso in cui non ho limiti sull'elettrolizzatore
    # h2_flow_av_EL = min(el_p_max, pv_gen) * el_eff   # Caso in cui produco solo da PV

    h2_flow_av_store = min(h2_store_mass / dt, (h2_store_flow_max - h2_store_flow))


    # IMPORTANTE: Codice aggiunto da AR
    for v in vehicles:
        h2_flow_demand = 0.0     # Richiesta totale di H2 da parte dei veicoli

        # TODO: l'orario deve essere generalizzato
        # Politica di ricarica
        if ora_val <= datetime.time(7, 0) or ora_val >= datetime.time(18, 0):
            if v['soc'] < 1:
                # La portata massima dipende da quanto H2 posso inserire in ogni veicolo, dalla portata massima del veicolo
                # e da quanto può erogare sia l'H2S che l'EL
                h2_flow_v_max = min((1 - v['soc']) * v['cap'] / dt,
                                    v['rate'],
                                    h2_flow_av_store + h2_flow_av_EL)
                # print((1 - v['soc']) * v['cap'] / dt, v['rate'], (h2_store_flow_max - h2_store_flow))
                # print(f'{v['id']} flow max: {h2_flow_v_max:.2f} kg/h')

                v['flow'] = h2_flow_v_max   # Carico il veicolo alla massima portata
                v['soc'] = v['soc'] + v['flow'] * dt / v['cap']

                h2_store_flow_v = float(min(v['flow'], h2_flow_av_store))   # Di questa portata, prendo tutto quello che posso dalla H2S

                h2_store_flow += h2_store_flow_v    # portata istantanea dell'H2S si riduce
                h2_store_mass -= h2_store_flow_v * dt   # Si riduce anche la quantità accumulata

                h2_flow_EL +=  max(0, v['flow'] - h2_store_flow_v)  # La parte residua me la da l'EL
                el_power = h2_flow_EL / el_eff
                h2_flow_av_store -= h2_store_flow_v     # Per il prossimo calcolo, la portata massima dell'EL si riduce
                h2_flow_av_EL -= max(0, v['flow'] - h2_store_flow_v)    # Per il prossimo calcolo, la portata massima dell'H2S si riduce
                h2_flow_H2V += v['flow']
                # if h2_store_mass > m_H2_v_max:
        else: # Politica di scarica
            if v['soc'] > 0:
                v['flow'] = - min(v['cap'] / 11, v['soc'] * v['cap'] / dt)
                v['soc'] = v['soc'] + v['flow'] * dt / v['cap']

        v['soc_history'].append(v['soc'] * 100.0)

        None

    #
    pv_res = pv_gen
    # bess_res = min(bess_p_max, bess_soc * bess_cap / dt)

    # -- Definizione della provenienza dell'energia necessaria all'Elettrolizzatore ---------------------
    ## Si prende tutto quello che può dal PV
    el_lack = el_power
    el_from_pv = min(pv_res, el_lack)
    el_lack -= el_from_pv
    pv_res -= el_from_pv

    ## Se ne serve ancora, cerca di prendersela dal BESS
    el_from_bess = min(el_lack, bess_p_max, bess_soc * bess_cap / dt)
    el_lack -= el_from_bess
    bess_power -= el_from_bess
    # bess_res -= el_from_bess
    bess_soc -= el_from_bess * dt / bess_cap

    ## l'aliquota residua se la prende dal POD
    grid_power += el_lack
    # ---------------------------------------------------------------------------------------------------

    # -- Definizione dell'utilizzo dell'energia fotovoltaica residua ------------------------------------
    ## Ricarica dello storage di H2
    if el_power < el_p_max and h2_store_mass < h2_store_cap:
        el_surplus = min(pv_res,
                         el_p_max - el_power,                                # La potenza residua dell'EL
                         (h2_store_cap - h2_store_mass) / (el_eff * dt),     # L'equivalente del residuo ricaricabile della bombola
                         h2_store_flow_max / el_eff)                         # L'equivalente della massima portata di ricarica della bombola
        el_power += el_surplus
        h2_flow_EL += el_surplus * el_eff
        pv_res -= el_surplus
        h2_store_flow -= el_surplus * el_eff
        h2_store_mass += el_surplus * el_eff * dt

    ## Ricarica del BESS
    if bess_soc < 1:
        bess_surplus = min(pv_res,  # Potenza residua del PV
                           bess_p_max,  # Potenza massima assorbibile dal BESS
                           (1 - bess_soc) * bess_cap / dt)                      # Energia mancante per unità di tempo
        bess_power += bess_surplus
        pv_res -= bess_surplus
        bess_soc += bess_surplus * dt / bess_cap

    grid_power -= pv_res
    # -- Definizione dell'utilizzo dell'energia fotovoltaica residua ------------------------------------

    grid_power += load


    # -- Calcolo dell'energia ---------------------------------------------------------------------------
    pod_en += grid_power * dt
    el_en += el_power * dt
    bess_en += bess_power * dt
    load_en += load * dt
    pv_en += pv_gen * dt

    # print(f'Ora: {ora_str}\tPV: {pv_gen:.2f} kW\tEL: {el_power:.2f} kW\t PV_res: {pv_res:.2f} kW\t'
    #       f'BESS: {bess_soc * 100:.2f}%\tBESS_P: {bess_power:.2f} kW')

    # # -------------------------------------------------------------
    # # NUOVA CASCATA DI DISPACCIAMENTO ENERGETICO COERENTE
    # # -------------------------------------------------------------
    #
    # # A. Copertura del Carico utenza (LOAD) tramite PV
    # load_energy = load * dt
    # energy_for_load_from_pv = min(load_energy, pv_energy)
    # pv_energy -= energy_for_load_from_pv
    # remaining_load_energy = load_energy - energy_for_load_from_pv
    #
    # # B. Alimentazione Elettrolizzatore con PV residuo (o BESS/Rete se in finestra prioritaria H2)
    # h2_needed_for_vehicles = sum([v['cap'] - v['soc'] for v in active_vehicles])
    # h2_needed_for_storage = max(0.0, initial_h2_mass - h2_store_mass)
    #
    # el_energy_needed = 0.0
    # if h2_needed_for_vehicles > 0 or (not is_h2_priority_window and h2_needed_for_storage > 0):
    #     target_h2_step = min(5.0 * dt,
    #                          h2_needed_for_vehicles + (h2_needed_for_storage if not is_h2_priority_window else 0.0))
    #     el_energy_needed = min(el_p_max * dt, target_h2_step / el_eff)
    #
    # energy_for_el_from_pv = min(el_energy_needed, pv_energy)
    # pv_energy -= energy_for_el_from_pv
    # remaining_el_energy = el_energy_needed - energy_for_el_from_pv
    #
    # energy_for_el_from_bess = 0.0
    # if remaining_el_energy > 0 and bess_soc > 1e-4:
    #     max_bess_discharge = min(bess_p_max * dt, bess_soc)
    #     energy_for_el_from_bess = min(remaining_el_energy, max_bess_discharge)
    #     bess_soc = max(0.0, bess_soc - energy_for_el_from_bess)
    #     remaining_el_energy -= energy_for_el_from_bess
    #     bess_power = -energy_for_el_from_bess / dt
    #
    # energy_for_el_from_grid = 0.0
    # if remaining_el_energy > 0:
    #     grid_for_el_power = min(grid_limit, remaining_el_energy / dt)
    #     energy_for_el_from_grid = grid_for_el_power * dt
    #     remaining_el_energy -= energy_for_el_from_grid
    #     grid_power += grid_for_el_power
    #
    # total_el_energy = energy_for_el_from_pv + energy_for_el_from_bess + energy_for_el_from_grid
    # if total_el_energy > 0:
    #     el_power = total_el_energy / dt
    #     h2_produced = total_el_energy * el_eff
    #
    # # C. Sfruttamento dell'esubero PV (dalle 11:00 in poi) per ricaricare il BESS fino a target 12 kWh
    # energy_for_bess = 0.0
    # bess_deficit = initial_bess_soc - bess_soc
    # if pv_energy > 0 and bess_deficit > 1e-4:
    #     bess_space = bess_cap - bess_soc
    #     max_bess_charge_energy = min(bess_p_max * dt, bess_space)
    #     energy_for_bess = min(max_bess_charge_energy, bess_deficit / 0.95, pv_energy)
    #     pv_energy -= energy_for_bess
    #     bess_soc += energy_for_bess * 0.95
    #     bess_power = energy_for_bess / dt  # Positivo = Carica BESS
    #
    # # D. Eventuale fabbisogno residuo del carico coperto da BESS o Rete
    # if remaining_load_energy > 0 and bess_soc > 1e-4:
    #     max_bess_discharge = min(bess_p_max * dt, bess_soc)
    #     energy_for_load_from_bess = min(remaining_load_energy, max_bess_discharge)
    #     bess_soc = max(0.0, bess_soc - energy_for_load_from_bess)
    #     remaining_load_energy -= energy_for_load_from_bess
    #
    #     discharge_kw = energy_for_load_from_bess / dt
    #     if bess_power >= 0:
    #         bess_power = -discharge_kw
    #     else:
    #         bess_power -= discharge_kw
    #
    # if remaining_load_energy > 0:
    #     grid_import_load = min(grid_limit - grid_power, remaining_load_energy / dt)
    #     grid_power += max(0.0, grid_import_load)
    #
    # # E. Se c'è ulteriore surplus PV dopo aver caricato il BESS, immettiamo in rete
    # if pv_energy > 0:
    #     grid_power = - (pv_energy / dt)
    #
    # # Controllo di sicurezza: se il BESS è a zero, potenza rigorosamente a 0
    # if bess_soc <= 1e-4:
    #     bess_power = 0.0
    #
    # # Aggiornamento accumulo H2 stazionario
    # h2_produced = min(h2_produced, h2_store_cap - h2_store_mass, h2_store_flow_max * dt)
    # h2_store_mass += h2_produced
    #
    # # Ricarica fisica flotta veicoli minuto per minuto (entro le 07:00)
    # h2_dispensed_step = 0.0
    # if is_h2_priority_window:
    #     active_vehicles = [v for v in vehicles if v['cap'] - v['soc'] > 1e-4]
    #     if active_vehicles and h2_store_mass > 1e-4:
    #         for minute_substep in range(15):
    #             if h2_store_mass <= 1e-4:
    #                 break
    #             active_vehicles = [v for v in vehicles if v['cap'] - v['soc'] > 1e-4]
    #             if not active_vehicles:
    #                 break
    #             max_flow_per_min = (h2_store_flow_max / 60.0)
    #             total_demanded_rate = sum([min(v['rate'] / 60.0, v['cap'] - v['soc']) for v in active_vehicles])
    #             scaling_factor = min(1.0, max_flow_per_min / total_demanded_rate) if total_demanded_rate > 0 else 0.0
    #
    #             for v in active_vehicles:
    #                 needed = v['cap'] - v['soc']
    #                 if needed > 1e-4:
    #                     if v['start_time'] is None:
    #                         exact_min = current_total_minutes + minute_substep
    #                         v['start_time'] = f"{exact_min // 60:02d}:{exact_min % 60:02d}"
    #                     v_rate_min = (v['rate'] / 60.0) * scaling_factor
    #                     h2_to_give = min(needed, v_rate_min, h2_store_mass)
    #                     if h2_to_give > 0:
    #                         v['soc'] += h2_to_give
    #                         h2_store_mass -= h2_to_give
    #                         h2_dispensed_step += h2_to_give
    #                         v['charging_minutes'] += 1.0
    #                     if abs(v['cap'] - v['soc']) < 1e-4 and v['end_time'] is None:
    #                         exact_min = current_total_minutes + minute_substep + 1
    #                         v['end_time'] = f"{exact_min // 60:02d}:{exact_min % 60:02d}"
    #
    # for v in vehicles:
    #     if v['id'] == 'Forklift_1':
    #         print(
    #             f'Time: {ora_str}\tFlow: {v['flow']:.2f} g/h\tSOC: {v['soc'] * 100:.2f}%\tmass: {(v['soc'] * v['cap']):.2f} g')
    #     v['soc_history'].append((v['soc'] / v['cap']) * 100.0)
    # print(f'veicolo {vehicles[5]['id']}\t{vehicles[5]['soc_history']}')
    #
    step_res = {
        'Ora': ora_str,
        'P_LOAD_kW': load,
        'P_PV_kW': pv_gen,
        'Grid_Power_kW': grid_power,
        'BESS_Power_kW': bess_power,
        'Electrolyzer_Power_kW': el_power,
        'BESS_SOC_kWh': bess_soc + bess_cap,
        'BESS_SOC_Percent': bess_soc * 100.0,
        'H2_Storage_kg': h2_store_mass,
        'H2_Storage_Percent': (h2_store_mass / h2_store_cap) * 100.0,
        'H2_Produced_kg': h2_produced,
        'H2_Dispensed_Total_kg': h2_dispensed_step,
        'H2_flow_EL': h2_flow_EL,
        'H2_flow_H2S': h2_store_flow,
        'H2_flow_H2V': h2_flow_H2V,
    }
    for v in vehicles:
        step_res[f"{v['id']}_SOC_kg"] = v['soc']
        step_res[f"{v['id']}_SOC_Percent"] = (v['soc'] / v['cap']) * 100.0

    results.append(step_res)

df_res = pd.DataFrame(results)

# ==========================================
# 3. ESPORTAZIONE IN EXCEL
# ==========================================
excel_output_filename = "risultati_dettagliati_microgrid.xlsx"
df_res.to_excel(excel_output_filename, index=False)
print(f"File Excel dettagliato generato con successo: {excel_output_filename}")

# ==========================================
# 4. STAMPA DEGLI OUTPUT TESTUALI
# ==========================================
print("==================================================")
print("       REPORT RISULTATI SIMULAZIONE MICROGRID     ")
print("==================================================")
print(
    f"BESS SOC Iniziale: {df_res['BESS_SOC_kWh'].iloc[0]:.2f} kWh | Finale: {df_res['BESS_SOC_kWh'].iloc[-1]:.2f} kWh (Target: 12.00 kWh)")
print(
    f"Accumulo H2 Iniziale: {df_res['H2_Storage_kg'].iloc[0]:.2f} kg | Finale: {df_res['H2_Storage_kg'].iloc[-1]:.2f} kg (Target: 1.50 kg)")
print("\n--- REPORT SESSIONI DI RICARICA FLOTTA ---")
for v in vehicles:
    print(f"Veicolo: {v['id']} | SOC Finale: {v['soc']:.3f} / {v['cap']} kg | "
          f"Minuti di carica: {v['charging_minutes']:.0f} min | "
          f"Inizio: {v['start_time']} | Fine: {v['end_time'] if v['end_time'] else 'Non completato'}")

print('\n\n')
print(f'Energia al POD: {pod_en:.2f} kWh')
print(f'Energia Elettrolizzatore: {el_en:.2f} kWh')
print(f'Energia BESS: {bess_en:.2f} kWh')
print(f'Energia FotoVoltaica: {pv_en:.2f} kWh')
print(f'Energia Carichi: {load_en:.2f} kWh')

print("==================================================")

# ==========================================
# 5. GENERAZIONE DEI GRAFICI (4 Subplots)
# ==========================================
fig, axs = plt.subplots(5, 1, figsize=(10, 16), sharex=True)

# 1. H2 Storage SOC%
axs[0].plot(df_res['Ora'], df_res['H2_Storage_Percent'], color='darkcyan', linewidth=2.5)
axs[0].axvline(x='07:00', color='red', linestyle='--', label='Target Ricarica (07:00)')
axs[0].set_ylabel('H2 Storage SOC (%)')
axs[0].set_title("1. Andamento del SOC% dell'Accumulo di Idrogeno Stazionario")
axs[0].grid(True, linestyle=':', alpha=0.6)
axs[0].legend()

# 2. BESS SOC%
axs[1].plot(df_res['Ora'], df_res['BESS_SOC_Percent'], color='royalblue', linewidth=2.5)
axs[1].axvline(x='07:00', color='red', linestyle='--')
axs[1].set_ylabel('BESS SOC (%)')
axs[1].set_title('2. Andamento del SOC% del BESS (Capacità 24 kWh - Ricarica attiva da esubero PV)')
axs[1].grid(True, linestyle=':', alpha=0.6)

# 3. SOC% dei Veicoli
for v in vehicles:
    style = '-' if 'CargoBike' in v['id'] else '--'
    width = 1.5 if 'CargoBike' in v['id'] else 2.5
    axs[2].plot(df_res['Ora'], v['soc_history'], label=v['id'], linestyle=style, linewidth=width)
axs[2].axvline(x='07:00', color='red', linestyle='--')
axs[2].set_ylabel('Veicoli SOC (%)')
axs[2].set_title('3. Andamento dello Stato di Carica (SOC%) dei Veicoli a Idrogeno')
axs[2].grid(True, linestyle=':', alpha=0.6)
axs[2].legend(loc='lower right', ncol=2, fontsize=8)

# 4. Profili di Potenza (Ordine: 1. EL, 2. BESS Power, 3. PV, 4. LOAD, 5. Rete)
axs[3].plot(df_res['Ora'], df_res['Electrolyzer_Power_kW'], color='orange', label='Elettrolizzatore (Max 9 kW)',
            linewidth=2)
axs[3].plot(df_res['Ora'], df_res['BESS_Power_kW'], color='royalblue', label='Potenza BESS (+ Carica / - Scarica)',
            linewidth=2, linestyle='-')
axs[3].plot(df_res['Ora'], df_res['P_PV_kW'], color='gold', label='Fotovoltaico (kW)', linewidth=2)
axs[3].plot(df_res['Ora'], df_res['P_LOAD_kW'], color='crimson', label='Carico LOAD (kW)', linewidth=2)
axs[3].plot(df_res['Ora'], df_res['Grid_Power_kW'], color='purple', label='Rete Esterna (kW)', linewidth=2,
            linestyle='-.')
axs[3].axvline(x='07:00', color='red', linestyle='--')
axs[3].set_ylabel('Potenza (kW)')
axs[3].set_xlabel('Orario')
axs[3].set_title('4. Profili di Potenza (EL, BESS, PV, LOAD, Rete Esterna)')
axs[3].grid(True, linestyle=':', alpha=0.6)
axs[3].legend(loc='upper right', fontsize=8)

# 5. Flussi di H2
axs[4].plot(df_res['Ora'], df_res['H2_flow_EL'], color='royalblue', linewidth=2.5, label='EL')
axs[4].plot(df_res['Ora'], df_res['H2_flow_H2S'], color='orange', linewidth=2.5, label=' H2S')
axs[4].plot(df_res['Ora'], df_res['H2_flow_H2V'], color='gold', linewidth=2.5, label=' H2V')
axs[4].axvline(x='07:00', color='red', linestyle='--')
axs[4].set_ylabel('Flusso H2')
axs[4].set_title('Prelievo di potenza dal POD')
axs[4].grid(True, linestyle=':', alpha=0.6)
axs[4].legend(loc='upper right', fontsize=8)

plt.xticks(df_res['Ora'][::8], rotation=45)
plt.tight_layout()
plt.savefig('microgrid_simulation_results.png', dpi=300)
plt.close()
print("Grafici generati e salvati in 'microgrid_simulation_results.png'.")