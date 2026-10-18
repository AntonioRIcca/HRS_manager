from model import Model
import pandas as pd

from pd_gen import PDgen


# Use cases:
# 1: 100% rinnovabile
# 2: Combo: 100% rinnovabile + accumulo
# 3: Max Power

# df = pd.read_excel('dati test.xlsx')

# pd_gen = PDgen()
# df = pd_gen.generator()
#
# model = Model(df=df, h2v_chg_max_n=1)
# kpi = model.sim(uc=3)
# model.output_print()


pd_gen = PDgen()
df = pd_gen.generator()
results = []

for h2v_chg_max_n in range(1, 7):
    model = Model(df=df, h2v_chg_max_n=h2v_chg_max_n)
    for uc in range(1,4):
        kpi = model.sim(uc=uc)
        # model.xlsx_export()
        model.output_print()
        # # model.graphs()
        results.append(kpi)
        print(f"\n\nTerminato caso\tCarica simultanea: {h2v_chg_max_n}\tCaso d'uso: {uc}")

df_res = pd.DataFrame(results)
df_res.to_excel('output_file.xlsx', index=False)


