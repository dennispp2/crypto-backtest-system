# Dashboard UI release — 2026-09-06

## Scope

Presentation only: `app.py`, new `ui.py`, README and presentation tests.
No changes to the frozen engines, allocations, signal thresholds, execution rules,
portfolio ledgers or forward evaluation criteria. UI validation did not run the model.
Ordinary market refresh retains its existing refresh-timestamp persistence.

## Verification

- `python -m py_compile app.py ui.py`: PASS.
- `python -m unittest discover -s tests -v`: 42/42 PASS (36 existing + 6 presentation tests).
- Actual Windows source app: asset overview, report, audit, history viewer, narrow-window reflow and wheel scrolling inspected.
- Packaged Windows EXE: launched successfully from the production D: path; live refresh and report navigation inspected.
- Existing safety failure remains visible as a red warning. This release does not clear or resolve it.
- Existing config retained; source and distribution config SHA256 both:
  `7346D75F411ECF0360C643635C8E88FDFAD1204133C3AF79E9006F8AFB41224E`.

## Build / recovery

Python 3.12.14; PyInstaller 6.22.2; existing Bitcoin ICO retained.

- Production EXE: `dist/CryptoForwardMonitor.exe`
- SHA256: `247B0EFBDEF0A6C33A3762FF5A127D0369CF52897DCC435335D683A7A61052BB`
- Previous EXE retained: `build/ui_refresh_20260906/CryptoForwardMonitor.previous.exe`
- Previous SHA256: `BEF0D84DD00C21D6918D4B5BC30A3755EFBAFC9BBC787F5DD3FEED1C5A1D6194`
- Staged build and spec: `build/ui_refresh_20260906/`

Source SHA256:

- `app.py`: `A8931CD6BB08FE951FCD37596DCD36D2F3E47E5FB137FBBDA9086C0D1840D9A2`
- `ui.py`: `68B485B77862DF8A65D36C6B4021D375F9FC7FC6CC2F44B0B90D9EE2EF0EEAFA`
- `tests/test_dashboard_presentation.py`: `2F0B154CA696CAD6B84157896C81AC9D71082E35EC0C4C653CDB91493B390C2E`

To restore the prior UI, close the app and copy the previous EXE back to the
production EXE path. Do not replace config or data folders.
