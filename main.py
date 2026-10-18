from model import Model
import pandas as pd

from pd_gen import PDgen


# Use cases:
# 1: 100% rinnovabile
# 2: Combo: 100% rinnovabile + accumulo
# 3: Max Power

pd_gen = PDgen()
df = pd_gen.generator()

model = Model(df=df, h2v_chg_max_n=1)
model.sim(uc=2)
model.xlsx_export()
model.output_print()
# model.graphs()