from model import Model


model = Model(excel_file='dati test_24.xlsx', h2v_chg_max_n=6)
model.sim()
model.xlsx_export()
model.output_print()
model.graphs()