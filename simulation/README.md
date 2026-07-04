# Simulation data — NOT real

Everything in `simulation/data/*.json` is **synthetic**, produced by `generate_data.py`
(seed `20260624`). It reconstructs real named incidents (Shunxin-39, Eagle S, Yi Peng 3,
Vezhen, Deoksong STS, Chonma San) as a scripted 72-hour scenario for demo replay only.

It is never loaded into the ontology store and the dashboard must never default-fetch it.
Real data comes from the ontology exporter (`mda export-dashboard`) into `dashboard/data/`.

Regenerate: `python3 generate_data.py`
