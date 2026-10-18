import datetime

import pandas as pd
# import numpy as np
import matplotlib.pyplot as plt


params = {
    'el': {
        'p_rate': 9.0,
        'p': 0.0,
        'irr': 0.0,
        'temp': 0.0,
        't_cell': 0.0,
        'eff': 22.0,  # [g_H2/kWh]
        'flow': 0.0,
        # 'flow_av': 0.0,
        'en': 0.0,
    },
    'pv': {
        'p_rate': 15.0,
        'p': 0.0,
        'en': 0.0,
    },
    'bess': {
        'cap': 24.0,  # [kWh]
        'p_rate': 25.0,  # [kW]
        'soc0': 0.0,  # SOC iniziale
        'soc': 0.0,  #
        'soc_min': 0.1,  # SOC minimo
        'soc_max': 0.9,  # [%] SOC massimo
        'en': 0.0,  # [kWh]
    },
    'h2s': {
        'cap': 1500,  # [g_H2] capacità
        'flow_rate': 4000,  # [g_H2/h] Portata massima IN/OUT
        'soc0': 0.0,  # [%] SOC iniziale
        'soc': 0.0,  #
        'flow': 0.0,  # [g_H2/h]
        # 'flow_av': 0.0,
    },
    'h2v': {
        'flow': 0,
        'uptake': 0,
    },
    'load': {
        'p': 0.0,
        'en': 0.0,  # [kWh]
    },
    'pod': {
        'en': 0.0,  # [kWh]
    },
}


class Model:
    def __init__(self, excel_file='dati test.xlsx', dt=0.25, par=params, h2v_chg_max_n=3, t_s=7.0, t_e=17.0):
        # ==========================================
        # 1. CARICAMENTO DATI E INIZIALIZZAZIONE
        # ==========================================
        self.df = pd.read_excel(excel_file)
        self.n_steps = len(self.df)
        self.dt = dt  # Intervalli di 15 minuti in ore

        self.h2v_chg_max_n = h2v_chg_max_n

        self.par = par
        self.t_s, self.t_e = t_s, t_e

        self.df_res = None

        # Flotta veicoli inizialmente completamente carichi (SOC = 1.0)
        self.vehicles = []
        for i in range(4):
            self.vehicles.append({
                'id': f'CB_{i + 1}',
                'cap': 100,  # g
                'rate': 500,  # g/h = 8.33 g/min
                'cons': 9.0,    # g/h di H2 consumati mentre è in funzione
                'soc': 0.4,
                'flow': 0.0,
                'start_time': None,
                'end_time': None,
                'charging_minutes': 0.0,
                'work_slot': [0, 24],
                'charge_slot': [0, 24],
                'in_charge': False,
                'to_charge': False,
            })

        for i in range(2):
            self.vehicles.append({
                'id': f'FL_{i + 1}',
                'cap': 1800.0,  # g
                'rate': 3000.0,  # g/h = 50.0 g/m4.2n
                'cons': 120.0,  # g/h di H2 consumati mentre è in funzione
                'soc': 1.0,
                'flow': 0.0,
                'start_time': None,
                'end_time': None,
                'charging_minutes': 0.0,
                'work_slot': [7, 17],
                'charge_slot': [0, 24],
                'in_charge': False,
                'to_charge': False,
            })
        self.h2v_prod = 0.0


        self.results = []

        # Registrazione dello stato iniziale (00:00)
        first_row = self.df.iloc[0]
        self.ora_val = first_row['Ora']
        self.ora_str = f"{self.ora_val.hour:02d}:{self.ora_val.minute:02d}" if hasattr(self.ora_val, 'hour') \
            else str(self.ora_val)[:5]

        # step_init = {
        #     'Ora': ora_str,
        #     'P_LOAD_kW': 0.0,
        #     'P_PV_kW': 0.0,
        #     'Grid_Power_kW': 0.0,
        #     'BESS_Power_kW': 0.0,
        #     'Electrolyzer_Power_kW': 0.0,
        #     'BESS_SOC_kWh': bess_soc * bess_cap,
        #     'BESS_SOC_Percent': bess_soc * 100.0,
        #     'H2_Storage_kg': h2_store_mass,
        #     'H2_Storage_Percent': (h2_store_mass / h2_store_cap) * 100.0,
        #     'H2_Produced_kg': 0.0,
        #     'H2_Dispensed_Total_kg': 0.0,
        #     'H2_flow_EL': 0.0,
        #     'H2_flow_H2S': 0.0,
        #     'H2_flow_H2V': 0.0,
        # }
        for v in self.vehicles:
            # step_init[f"{v['id']}_SOC_kg"] = v['soc']
            # step_init[f"{v['id']}_SOC_Percent"] = (v['soc'] / v['cap']) * 100.0
            v['soc_history'] = []

# results.append(step_init)
    def sim(self):
        # ==========================================
        # 2. CICLO DI SIMULAZIONE TEMPORALE
        # ==========================================
        h2v_to_chg_order = []
        h2v_in_chg_order = []

        for idx, row in self.df.iloc[0:].iterrows():
            self.par['load']['p'] = row['P LOAD  [kW]']
            self.par['pv']['irr'] = row['Irr PV [W(m2)']
            self.par['pv']['temp'] = row['T PV [°C]']
            ora_val = row['Ora']

            if hasattr(ora_val, 'hour') and hasattr(ora_val, 'minute'):
                current_total_minutes = ora_val.hour * 60 + ora_val.minute
                try:
                    ora_str = f"G{ora_val.day}:{ora_val.hour:02d}:{ora_val.minute:02d}"
                except AttributeError:
                    ora_str = f"{ora_val.hour:02d}:{ora_val.minute:02d}"
            else:
                h_parts = list(map(int, str(ora_val).split(':')[:2]))
                current_total_minutes = h_parts[0] * 60 + h_parts[1]
                ora_str = str(ora_val)[:5]

            curr_time = ora_val.hour + ora_val.minute / 60

            # Modellazione PV con correzione termica
            self.par['pv']['t_cell'] = self.par['pv']['temp'] + self.par['pv']['irr'] * 0.03
            self.par['pv']['p'] = max(0.0,
                                      self. par['pv']['p_rate'] * (self.par['pv']['irr'] / 1000.0) *
                                      (1.0 - 0.004 * (self.par['pv']['t_cell'] - 25.0)))

            # print(f'Ora: {ora_str}\t irr: {self.par['pv']['irr']} W/m2\t T_amb: {self.par['pv']['temp']} °C\t T cell: {self.par['pv']['t_cell']:.2f} °C\t P_PV: {self.par['pv']['p']} kW')
            # pv_energy = pv_gen * self.dt  # kWh

            # is_h2_priority_window = (current_total_minutes < 420)
            # active_vehicles = [v for v in self.vehicles if v['cap'] - v['soc'] > 1e-4] if is_h2_priority_window else []

            self.par['el']['p'] = 0.0
            # h2_produced = 0.0
            self.par['bess']['p'] = 0.0
            self.par['pod']['p'] = 0.0

            # h2_dispensed_step = 0.0     # Todo: To delete

            self.par['h2s']['flow'] = 0.0
            self.par['el']['flow'] = 0.0
            self.par['h2v']['flow'] = 0.0
            # h2_store_flow = 0.0
            # h2_flow_EL = 0.0
            # h2_flow_H2V = 0.0

            h2_flow_av_el = self.par['el']['p_rate'] * self.par['el']['eff']  # Caso in cui non ho limiti sull'elettrolizzatore
            # h2_flow_av_EL = min(el_p_max, pv_gen) * el_eff   # Caso in cui produco solo da PV

            h2_flow_av_store = min(self.par['h2s']['soc'] * self.par['h2s']['cap'] / self.dt,
                                   (self.par['h2s']['flow_rate'] - self.par['h2s']['flow']))

            h2v_chg_curr_n = 0
            # for v in self.vehicles:
            #     if v['in_charge']:
            #         h2v_chg_curr_n += 1

            h2v_to_chg = 0



            if ora_str == "G1:23:00":
                print('èora')

            for i in range(len(self.vehicles)):
                v = self.vehicles[i]
                None
                if v['charge_slot'][0] <= curr_time < v['charge_slot'][1] and i not in h2v_in_chg_order:
                    if ((v['work_slot'][0] <= curr_time > v['work_slot'][1] and v['soc'] < 1) or v['soc'] == 0) and i not in h2v_to_chg_order:
                        h2v_to_chg_order.append(i)
                        # v['to_charge'] = True
                elif i in h2v_in_chg_order:
                    if v['soc'] < 1:
                        # h2v_chg_curr_n += 1
                        pass
                    else:
                        # v['in_charge'] = False
                        # v['to_charge'] = False

                        h2v_to_chg_order.remove(i)

                        print('==')
                        h2v_in_chg_order.remove(i)

            av = self.h2v_chg_max_n - len(h2v_in_chg_order)
            if av > 0:
                for i in range(min(av, len(h2v_to_chg_order))):
                    h2v_in_chg_order.append(h2v_to_chg_order[0])
                    h2v_to_chg_order.pop(0)

            h2v_to_chg = len(h2v_in_chg_order)

            h2v_max_session = min(h2v_to_chg, self.h2v_chg_max_n)
            print(f'Ora: {ora_str}\tIn ricarica: {len(h2v_in_chg_order)}')

            all_v = list(range(len(self.vehicles)))

            sort_v = h2v_in_chg_order.copy()
            for i in all_v:
                if i not in h2v_in_chg_order:
                    sort_v.append(i)
            print(sort_v)
            for i in sort_v:

                v = self.vehicles[i]
                if i in h2v_in_chg_order:
                    # h2_flow_demand = 0.0     # Richiesta totale di H2 da parte dei veicoli

                    # if v['charge_slot'][0] <= curr_time < v['charge_slot'][1] and not v['in_charge']:
                    #     v['to_charge'] = ((v['work_slot'][0] <= curr_time > v['work_slot'][1] and v['soc'] < 1)
                    #                       or v['soc'] == 0)
                    #     h2v_to_chg += 1
                    # h2v_max_session = min(h2v_to_chg, self.h2v_chg_max_n)

                    # if ora_str == "09:30":
                    #     print('èora')

                    # if v['to_charge'] and h2v_chg_curr_n < self.h2v_chg_max_n and v['soc'] < 1:

                    v['in_charge'] = True
                    # La portata massima dipende da quanto H2 posso inserire in ogni veicolo, dalla portata massima del veicolo
                    # e da quanto può erogare sia l'H2S che l'EL
                    h2_flow_v_max = min((1 - v['soc']) * v['cap'] / self.dt,
                                        v['rate'],
                                        (h2_flow_av_store + h2_flow_av_el) / h2v_max_session)
                    # print((1 - v['soc']) * v['cap'] / dt, v['rate'], (h2_store_flow_max - h2_store_flow))
                    # print(f'{v['id']} flow max: {h2_flow_v_max:.2f} kg/h')

                    v['flow'] = h2_flow_v_max   # Carico il veicolo alla massima portata
                    v['soc'] = v['soc'] + v['flow'] * self.dt / v['cap']

                    h2_store_flow_v = float(min(v['flow'], h2_flow_av_store))   # Di questa portata, prendo tutto quello che posso dalla H2S

                    self.par['h2s']['flow'] += h2_store_flow_v    # portata istantanea dell'H2S si riduce
                    self.par['h2s']['soc'] -= h2_store_flow_v * self.dt / self.par['h2s']['cap']   # Si riduce anche la quantità accumulata

                    self.par['el']['flow'] +=  max(0, v['flow'] - h2_store_flow_v)  # La parte residua me la da l'EL
                    self.par['el']['p'] = self.par['el']['flow'] / self.par['el']['eff']
                    h2_flow_av_store -= h2_store_flow_v     # Per il prossimo calcolo, la portata massima dell'EL si riduce
                    h2_flow_av_el -= max(0, v['flow'] - h2_store_flow_v)    # Per il prossimo calcolo, la portata massima dell'H2S si riduce
                    self.par['h2v']['flow'] += v['flow']

                    if v['flow'] > 0:
                        h2v_max_session -= 1
                        # if not v['in_charge']:
                        #     v['in_charge'] = True
                        #     h2v_chg_curr_n += 1
                    if v['soc'] == 1:
                        h2v_in_chg_order.remove(i)

                        # if h2_store_mass > m_H2_v_max:
                    # elif v['soc'] == 1:
                    #     v['in_charge'] = False
                    #     v['to_charge'] = False

                else:
                    if v['work_slot'][0] <= curr_time < v['work_slot'][1]:
                        if v['soc'] > 0:
                            v['flow'] = - min(v['cons'], v['soc'] * v['cap'] / self.dt)
                            v['soc'] = v['soc'] + v['flow'] * self.dt / v['cap']
                        else:
                            v['flow'] = 0

                v['soc_history'].append(v['soc'] * 100.0)

            #
            pv_res = self.par['pv']['p']
            # bess_res = min(bess_p_max, bess_soc * bess_cap / dt)

            # -- Definizione della provenienza dell'energia necessaria all'Elettrolizzatore ---------------------
            ## Si prende tutto quello che può dal PV
            el_lack = self.par['el']['p']
            el_from_pv = min(pv_res, el_lack)
            el_lack -= el_from_pv
            pv_res -= el_from_pv

            ## Se ne serve ancora, cerca di prendersela dal BESS
            el_from_bess = min(el_lack,
                               self.par['bess']['p_rate'],
                               self.par['bess']['soc'] * self.par['bess']['cap'] / self.dt)
            el_lack -= el_from_bess
            self.par['bess']['p'] -= el_from_bess
            # bess_res -= el_from_bess
            self.par['bess']['soc'] -= el_from_bess * self.dt / self.par['bess']['cap']

            ## l'aliquota residua se la prende dal POD
            self.par['pod']['p'] += el_lack
            # ---------------------------------------------------------------------------------------------------

            # -- Definizione dell'utilizzo dell'energia fotovoltaica residua ------------------------------------
            ## Ricarica dello storage di H2
            if self.par['el']['p'] < self.par['bess']['p_rate'] and self.par['h2s']['soc'] < 1:
                el_surplus = min(pv_res,
                                 self.par['el']['p_rate'] - self.par['el']['p'],                                # La potenza residua dell'EL
                                 (1 - self.par['h2s']['soc']) * self.par['h2s']['cap'] / (self.par['el']['eff'] * self.dt),     # L'equivalente del residuo ricaricabile della bombola
                                 self.par['h2s']['flow_rate'] / self.par['el']['eff'])                         # L'equivalente della massima portata di ricarica della bombola
                self.par['el']['p'] += el_surplus
                self.par['el']['flow'] += el_surplus * self.par['el']['eff']
                pv_res -= el_surplus
                self.par['h2s']['flow'] -= el_surplus * self.par['el']['eff']
                self.par['h2s']['soc'] += el_surplus * self.par['el']['eff'] * self.dt / self.par['h2s']['cap']
                # h2_store_mass += el_surplus * el_eff * dt

            ## Ricarica del BESS
            if self.par['bess']['soc'] < 1:
                bess_surplus = min(pv_res,  # Potenza residua del PV
                                   self.par['bess']['p_rate'],  # Potenza massima assorbibile dal BESS
                                   (1 - self.par['bess']['soc']) * self.par['bess']['cap'] / self.dt)                      # Energia mancante per unità di tempo
                self.par['bess']['p'] += bess_surplus
                pv_res -= bess_surplus
                self.par['bess']['soc'] += bess_surplus * self.dt / self.par['bess']['cap']

            self.par['pod']['p'] -= pv_res
            # -- Definizione dell'utilizzo dell'energia fotovoltaica residua ------------------------------------

            self.par['pod']['p'] += self.par['load']['p']


            # -- Calcolo dell'energia ---------------------------------------------------------------------------
            for el in ['pod', 'el', 'bess', 'pv', 'load']:
                self.par[el]['en'] += self.par[el]['p'] * self.dt

            self.par['h2v']['uptake'] += self.par['h2v']['flow'] * self.dt

            # pod_en += grid_power * dt
            # el_en += el_power * dt
            # bess_en += bess_power * dt
            # load_en += load * dt
            # pv_en += pv_gen * dt
            # h2v_prod += h2_flow_H2V * dt

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
                'P_LOAD_kW': self.par['load']['p'],
                'P_PV_kW': self.par['pv']['p'],
                'Grid_Power_kW': self.par['pod']['p'],
                'BESS_Power_kW': self.par['bess']['p'],
                'Electrolyzer_Power_kW': self.par['el']['p'],
                'BESS_SOC_kWh': self.par['bess']['soc'] * self.par['bess']['cap'],
                'BESS_SOC_Percent': self.par['bess']['soc'] * 100.0,
                'H2_Storage_kg': self.par['h2s']['soc'] * self.par['h2s']['cap'],
                'H2_Storage_Percent': self.par['h2s']['soc'] * 100.0,
                # 'H2_Produced_kg': h2_produced,
                # 'H2_Dispensed_Total_kg': h2_dispensed_step,
                'H2_flow_EL': self.par['el']['flow'],
                'H2_flow_H2S': self.par['h2s']['flow'],
                'H2_flow_H2V':self.par['h2v']['flow'],
            }
            for v in self.vehicles:
                # step_res[f"{v['id']}_SOC_kg"] = v['soc']
                step_res[f"{v['id']}_SOC_Percent"] = (v['soc'] / v['cap']) * 100.0
                step_res[f"{v['id']}_H2Flow_g/h"] = v['flow']

            self.results.append(step_res)

        self.df_res = pd.DataFrame(self.results)

    def xlsx_export(self, excel_output_filename="risultati_dettagliati_microgrid.xlsx"):
        # ==========================================
        # 3. ESPORTAZIONE IN EXCEL
        # ==========================================
        # excel_output_filename = "risultati_dettagliati_microgrid.xlsx"
        self.df_res.to_excel(excel_output_filename, index=False)
        print(f"File Excel dettagliato generato con successo: {excel_output_filename}")

    def output_print(self):
        # ==========================================
        # 4. STAMPA DEGLI OUTPUT TESTUALI
        # ==========================================
        print("==================================================")
        print("       REPORT RISULTATI SIMULAZIONE MICROGRID     ")
        print("==================================================")
        print(f"BESS SOC Iniziale: {self.df_res['BESS_SOC_kWh'].iloc[0]:.2f} kWh |"
              f" Finale: {self.df_res['BESS_SOC_kWh'].iloc[-1]:.2f} kWh (Target: 12.00 kWh)")
        print(f"Accumulo H2 Iniziale: {self.df_res['H2_Storage_kg'].iloc[0]:.2f} kg |"
              f" Finale: {self.df_res['H2_Storage_kg'].iloc[-1]:.2f} kg (Target: 1.50 kg)")
        print("\n--- REPORT SESSIONI DI RICARICA FLOTTA ---")
        for v in self.vehicles:
            print(f"Veicolo: {v['id']} | SOC Finale: {v['soc']:.3f} / {v['cap']} kg | "
                  f"Minuti di carica: {v['charging_minutes']:.0f} min | "
                  f"Inizio: {v['start_time']} | Fine: {v['end_time'] if v['end_time'] else 'Non completato'}")

        print('\n\n')
        print(f'Energia al POD: {self.par['pod']['en']:.2f} kWh')
        print(f'Energia Elettrolizzatore: {self.par['el']['en']:.2f} kWh')
        print(f'Energia BESS: {self.par['bess']['en']:.2f} kWh')
        print(f'Energia FotoVoltaica: {self.par['pv']['en']:.2f} kWh')
        print(f'Energia Carichi: {self.par['load']['en']:.2f} kWh')
        print(f'H2 prodotto: {self.par['h2v']['uptake']:.1f} g')

        print("==================================================")

    def graphs(self):
        # ==========================================
        # 5. GENERAZIONE DEI GRAFICI (4 Subplots)
        # ==========================================
        fig, axs = plt.subplots(5, 1, figsize=(10, 16), sharex=True)

        # 1. H2 Storage SOC%
        axs[0].plot(self.df_res['Ora'], self.df_res['H2_Storage_Percent'], color='darkcyan', linewidth=2.5)
        axs[0].axvline(x='07:00', color='red', linestyle='--', label='Target Ricarica (07:00)')
        axs[0].set_ylabel('H2 Storage SOC (%)')
        axs[0].set_title("1. Andamento del SOC% dell'Accumulo di Idrogeno Stazionario")
        axs[0].grid(True, linestyle=':', alpha=0.6)
        axs[0].legend()

        # 2. BESS SOC%
        axs[1].plot(self.df_res['Ora'], self.df_res['BESS_SOC_Percent'], color='royalblue', linewidth=2.5)
        axs[1].axvline(x='07:00', color='red', linestyle='--')
        axs[1].set_ylabel('BESS SOC (%)')
        axs[1].set_title('2. Andamento del SOC% del BESS (Capacità 24 kWh - Ricarica attiva da esubero PV)')
        axs[1].grid(True, linestyle=':', alpha=0.6)

        # 3. SOC% dei Veicoli
        for v in self.vehicles:
            style = '-' if 'CargoBike' in v['id'] else '--'
            width = 1.5 if 'CargoBike' in v['id'] else 2.5
            axs[2].plot(self.df_res['Ora'], v['soc_history'], label=v['id'], linestyle=style, linewidth=width)
        axs[2].axvline(x='07:00', color='red', linestyle='--')
        axs[2].set_ylabel('Veicoli SOC (%)')
        axs[2].set_title('3. Andamento dello Stato di Carica (SOC%) dei Veicoli a Idrogeno')
        axs[2].grid(True, linestyle=':', alpha=0.6)
        axs[2].legend(loc='lower right', ncol=2, fontsize=8)

        # 4. Profili di Potenza (Ordine: 1. EL, 2. BESS Power, 3. PV, 4. LOAD, 5. Rete)
        axs[3].plot(self.df_res['Ora'], self.df_res['Electrolyzer_Power_kW'], color='orange', label='EL',
                    linewidth=2)
        axs[3].plot(self.df_res['Ora'], self.df_res['BESS_Power_kW'], color='royalblue', label='BESS',
                    linewidth=2, linestyle='-')
        axs[3].plot(self.df_res['Ora'], self.df_res['P_PV_kW'], color='gold', label='PV', linewidth=2)
        axs[3].plot(self.df_res['Ora'], self.df_res['P_LOAD_kW'], color='crimson', label='LOAD', linewidth=2)
        axs[3].plot(self.df_res['Ora'], self.df_res['Grid_Power_kW'], color='purple', label='POD', linewidth=2,
                    linestyle='-.')
        axs[3].axvline(x='07:00', color='red', linestyle='--')
        axs[3].set_ylabel('Potenza (kW)')
        axs[3].set_xlabel('Orario')
        axs[3].set_title('4. Profili di Potenza (EL, BESS, PV, LOAD, Rete Esterna)')
        axs[3].grid(True, linestyle=':', alpha=0.6)
        axs[3].legend(loc='lower right', ncol=2, fontsize=8)

        # 5. Flussi di H2
        axs[4].plot(self.df_res['Ora'], self.df_res['H2_flow_EL'], color='royalblue', linewidth=2.5, label='EL')
        axs[4].plot(self.df_res['Ora'], self.df_res['H2_flow_H2S'], color='orange', linewidth=2.5, label=' H2S')
        axs[4].plot(self.df_res['Ora'], self.df_res['H2_flow_H2V'], color='gold', linewidth=2.5, label=' H2V')
        axs[4].axvline(x='07:00', color='red', linestyle='--')
        axs[4].set_ylabel('Flusso H2')
        axs[4].set_title('5. Flusso H2 dai dispositivi')
        axs[4].grid(True, linestyle=':', alpha=0.6)
        axs[4].legend(loc='upper right', fontsize=8)

        plt.xticks(self.df_res['Ora'][::8], rotation=45)
        plt.tight_layout()
        plt.savefig('microgrid_simulation_results.png', dpi=300)
        plt.close()
        print("Grafici generati e salvati in 'microgrid_simulation_results.png'.")


if __name__ == "__main__":
    model = Model(h2v_chg_max_n=1)
    model.sim()
    model.xlsx_export()
    model.output_print()
    model.graphs()