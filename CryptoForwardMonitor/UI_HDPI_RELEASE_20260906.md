# High-DPI / rounded dashboard release — 2026-09-06

## Scope and design

The presentation was upgraded to CustomTkinter 5.2.2: rounded components,
compact exchange-style layout, sidebar navigation, pixel-based scroll easing,
busy-button feedback and non-modal completion/error notices. Force-run
confirmation is retained. Background callbacks are marshalled onto the Tk
thread through a bounded queue; callbacks arriving after close are discarded.

No model rules, thresholds, engine files, holdings or execution gates changed.
No live model run was triggered during verification. Existing safety failures
remain visible. Market refresh still persists its ordinary refresh timestamp.

## DPI evidence

- Previous EXE manifest had no DPI awareness declaration; previous app startup
  did not enable DPI awareness.
- New startup enables awareness before constructing Tk; new EXE manifest
  embeds `dpiAware=true/pm` and `dpiAwareness=PerMonitor`.
- Runtime preview window diagnostic: `window_dpi_awareness=2`, `window_dpi=144`.
- Shipped EXE manifest inspected after packaging: PerMonitor present,
  requested execution level remains `asInvoker`, `uiAccess=false`.
- Did not change Windows display scaling, font settings, drivers or security settings.
- Other monitors / all possible Windows scaling percentages were not manually tested.

References: [Microsoft High DPI](https://learn.microsoft.com/en-us/windows/win32/hidpi/high-dpi-desktop-application-development-on-windows),
[CustomTkinter scaling](https://customtkinter.tomschimansky.com/documentation/scaling/).

## Verification

- Python compilation: PASS.
- Full suite: 53/53 PASS; includes prior parsing, paper execution integrity,
  no-auto-model-execution, presentation and new queue/notice/progress tests.
- Withdrawn-window test: actual widget construction, all three pages, report text,
  logical-width breakpoints, notifications, help and history; temporary config
  and mocked controller, no production reads/writes or network/model calls.
- Source preview and packaged EXE overview visually inspected with desktop tool.
- Packaged EXE was observed launching and refreshing live quotes successfully.
- No claim of comprehensive native UI testing at every display scale.

## Preservation check — hashes unchanged from before this update

| File | SHA256 |
|---|---|
| dist/config.json | 7346D75F411ECF0360C643635C8E88FDFAD1204133C3AF79E9006F8AFB41224E |
| forward_v310_portfolio.csv | AC0F076060C2602237BDF707F44F6B27E6D700759924BEE8FE00DE63C024A47E |
| forward_v31_shadow_portfolio.csv | AEF001D4DEE82BB967D7C2D40D2C2C6D55D9541575FF21421837669953B587A3 |

## Delivery and rollback

- EXE: `dist/CryptoForwardMonitor.exe`, 19,386,105 bytes.
- SHA256: `13F372C20A15EF39F9DC135CD467CB41EF3A3E61A9553A63AAEAD560323718DB`.
- Previous EXE and source backup: `build/hdpi_20260906/previous/`.
- Build uses Python 3.12.14, PyInstaller 6.22.2 and Pillow 12.3.0.
- CTk assets/fonts and original Bitcoin image bundled. Unused optional NumPy
  excluded from the desktop package; the existing NumPy installation is retained.
  CustomTkinter and darkdetect were added to the project environment for the UI.
- `build_exe.bat` installs pinned dependencies and retains existing dist config.
- To restore the old UI, close the app and restore only the backed-up EXE.
  Do not replace config, portfolio, history or archive directories.

Source SHA256:

- app.py: B69F0D98067D23B34357EC2A429E88B36333EA9014837B85C244F48608CF6A62
- ui.py: 52DDF5B0C5C87A871EC35F3FC5BED15D5EB95ABF2A435CD20E86C70ADE698F18
- ui_components.py: 82FA14066F5C43EBBE39A3BC37BB38706AB3BF9A8189743915DAC3A2D188D382
- ui_dispatch.py: 9960E4E687B34ECB9D924A17C5FEE52BAAAB1331DBD79D20CF819519AFFE7AF6
