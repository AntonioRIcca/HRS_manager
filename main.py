from model import Model
import pandas as pd

from pd_gen import PDgen


# Use cases:
# 1: 100% rinnovabile
# 2: Combo: 100% rinnovabile + accumulo
# 3: Max Power

input_file = '_winter_'
h2v_chg_max_n=3
uc=3

results = []

for input_file in ['_spring_', '_summer_', '_autumn_', '_winter_', ]:
    for uc in range(1, 4):
        df = pd.read_excel(f'{input_file}.xlsx')

        # pd_gen = PDgen()
        # df = pd_gen.generator()

        model = Model(df=df, h2v_chg_max_n=h2v_chg_max_n)
        kpi = model.sim(uc=uc)
        model.output_print()
        model.graphs(name=input_file)
        results.append(kpi)

        filename = f'{input_file}_uc={uc}_sim_chg={h2v_chg_max_n}'

        # pd_gen = PDgen()
        # df = pd_gen.generator()
        # results = []
        # output_name = ''
        #
        # for h2v_chg_max_n in range(1, 7):
        #     model = Model(df=df, h2v_chg_max_n=h2v_chg_max_n)
        #     for uc in range(1,4):
        #         kpi = model.sim(uc=uc)
        #         # model.xlsx_export()
        #         model.output_print()
        #         # # model.graphs()
        #         results.append(kpi)
        #         print(f"\n\nTerminato caso\tCarica simultanea: {h2v_chg_max_n}\tCaso d'uso: {uc}")
#
df_res = pd.DataFrame(results)
df_res.to_excel(f'All_seasons_output_file.xlsx', index=False)


