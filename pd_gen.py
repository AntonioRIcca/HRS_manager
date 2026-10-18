import pandas as pd
import numpy as np


season_config = {
    "summer": {
        "months": [6, 7, 8],
        "weather": {
            "sunny": 0.80,
            "part_cloudy": 0.15,
            "cloudy": 0.05,
        },
    },
    "autumn": {
        "months": [9, 10, 11],
        "weather": {
            "sunny": 0.42,
            "part_cloudy": 0.33,
            "cloudy": 0.25,
        },
    },
    "winter": {
        "months": [12, 1, 2],
        "weather": {
            "sunny": 0.55,
            "part_cloudy": 0.23,
            "cloudy": 0.22,  # Normalizzato a 1.0 per la somma delle probabilità
        },
    },
    "spring": {
        "months": [3, 4, 5],
        "weather": {
            "sunny": 0.50,
            "part_cloudy": 0.32,
            "cloudy": 0.18,
        },
    },
}

df_load = pd.read_excel("load.xlsx")
df_pv = pd.read_excel("pv.xlsx", sheet_name="Irraggiamento")


class PDgen:
    def __init__(self):
        # self.calculation()
        pass

    def get_season(self, month):
        """Restituisce la stagione in base al mese solare."""
        for s_name, cfg in season_config.items():
            if month in cfg["months"]:
                return s_name
        return "winter"

    def generator(self):
        # 3. Generazione dei 365 giorni dell'anno 2026
        days_2026 = pd.date_range(start="2026-01-01", end="2026-12-31", freq="D")

        # Impostazione del seed per la riproducibilità dell'estrazione probabilistica (opzionale)
        np.random.seed(42)

        daily_dataframes = []

        for single_day in days_2026:
            # Identificazione della stagione
            season_name = self.get_season(single_day.month)
            weather_dict = season_config[season_name]["weather"]

            # Estrazione probabilistica della condizione meteo del giorno
            conditions = list(weather_dict.keys())
            probabilities = list(weather_dict.values())
            chosen_weather = np.random.choice(conditions, p=probabilities)

            # Identificazione delle colonne corrispondenti in pv.xlsx
            irr_col_name = f"{season_name}_{chosen_weather}_irr"
            temp_col_name = f"{season_name}_{chosen_weather}_temp"

            # Generazione dei 96 timestamp del giorno (passo 15 minuti)
            day_timestamps = pd.date_range(
                start=f"{single_day.strftime('%Y-%m-%d')} 00:00:00",
                periods=96,
                freq="15min",
            )

            # Costruzione del dataframe giornaliero
            df_day = pd.DataFrame(
                {
                    "Timestamp": day_timestamps,
                    "P_LOAD_[kW]": df_load["P LOAD  [kW]"].values,
                    "Irr_PV_[W/m2]": df_pv[irr_col_name].values,
                    "T_PV_[°C]": df_pv[temp_col_name].values,
                    "Stagione": season_name,
                    "Meteo": chosen_weather,
                }
            )

            daily_dataframes.append(df_day)

        # 4. Concatenazione dei giorni e creazione del dataset annuale
        df_annual = pd.concat(daily_dataframes, ignore_index=True)
        # df_annual.set_index("Timestamp", inplace=True)

        # A. Esportazione in formato Excel (.xlsx)
        file_excel = "anno_solare_2026_microgrid.xlsx"
        df_annual.to_excel(file_excel, index=False, engine="openpyxl")
        print(f"-> File Excel esportato con successo: {file_excel}")

        print("=== Generazione completata con successo ===")
        print(f"Dimensioni del DataFrame annuale: {df_annual.shape}")
        print("\nAnteprima dei primi record:")
        print(df_annual.head())

        return df_annual


if __name__ == "__main__":
    pd_gen = PDgen()
    pd_gen.generator()