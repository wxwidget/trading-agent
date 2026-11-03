# Local seed data

The historical seed snapshot is not included in this public repository. Place the five locally authorized input files here when using `scripts/run.py`: `open.csv.gz`, `close.csv.gz`, `div.csv.gz`, `tradable.csv.gz`, and `volume.csv.gz`. Each file must have a date index and columns matching `sh510300`, `sz159915`, `sh510880`, `sh518880`, and `sz159920`.

Use a seed snapshot only as a historical starting point. Refresh and validate through the requested signal date before producing a current plan. Do not commit account records, private destinations, or run outputs.
