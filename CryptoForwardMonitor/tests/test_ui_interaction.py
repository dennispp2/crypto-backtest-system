"""UI-only interaction contracts. Never launch the real forward engine."""
from pathlib import Path
from threading import Thread, get_ident
from types import SimpleNamespace
from unittest import TestCase, mock
import xml.etree.ElementTree as ET

from test_monitor import APP_DIR
from app import CryptoForwardMonitorApp
from ui_components import Progress
from ui_dispatch import UiDispatcher


class InteractionTests(TestCase):
    def test_worker_callbacks_wait_for_ui_thread(self):
        dispatcher = UiDispatcher()
        called = []
        worker = Thread(target=lambda: dispatcher.post(lambda: called.append(get_ident())))
        worker.start()
        worker.join()
        self.assertEqual(called, [])
        self.assertEqual(dispatcher.drain(), 1)
        self.assertEqual(called, [get_ident()])

    def test_close_discards_display_callbacks(self):
        dispatcher = UiDispatcher()
        callback = mock.Mock()
        dispatcher.post(callback)
        dispatcher.close()
        self.assertEqual(dispatcher.drain(), 0)
        self.assertFalse(dispatcher.post(callback))
        callback.assert_not_called()

    def test_dispatch_drain_is_bounded(self):
        dispatcher = UiDispatcher()
        callback = mock.Mock()
        for _ in range(100):
            dispatcher.post(callback)
        self.assertEqual(dispatcher.drain(), 50)
        self.assertEqual(callback.call_count, 50)
        self.assertEqual(dispatcher.drain(), 50)

    def test_model_success_uses_nonblocking_notice(self):
        view = SimpleNamespace(_model_reset=mock.Mock(), notify=mock.Mock(), refresh_dashboard=mock.Mock())
        result = SimpleNamespace(outcome="COMPLETED", completed=True, execution_summary="")
        with mock.patch("app.messagebox.showinfo") as popup:
            CryptoForwardMonitorApp.model_finished(view, result)
        popup.assert_not_called()
        view.notify.assert_called_once()
        view.refresh_dashboard.assert_called_once()

    def test_model_failure_remains_explicit(self):
        view = SimpleNamespace(_model_reset=mock.Mock(), notify=mock.Mock(), refresh_dashboard=mock.Mock())
        result = SimpleNamespace(outcome="FAILED", completed=False, message="failure details", execution_summary="")
        CryptoForwardMonitorApp.model_finished(view, result)
        view.notify.assert_called_once_with("模型執行失敗：failure details", error=True)

    def test_busy_model_button_has_feedback(self):
        view = SimpleNamespace(model_in_progress=True, notify=mock.Mock())
        with mock.patch("app.threading.Thread") as worker:
            CryptoForwardMonitorApp._start_model(view, force=False)
        worker.assert_not_called()
        view.notify.assert_called_once()

    def test_progress_fraction_not_exaggerated(self):
        bar = SimpleNamespace(maximum=180, set=mock.Mock())
        Progress.__setitem__(bar, "value", 1.83)
        bar.set.assert_called_once_with(1.83 / 180)

    def test_progress_bounded(self):
        bar = SimpleNamespace(maximum=3, set=mock.Mock())
        Progress.__setitem__(bar, "value", 8)
        bar.set.assert_called_once_with(1)
        with self.assertRaises(KeyError):
            Progress.__setitem__(bar, "wrong-key", 1)

    def test_manifest_requires_per_monitor_dpi(self):
        manifest = ET.parse(Path(APP_DIR) / "app.manifest")
        values = {node.tag.rsplit("}", 1)[-1]: node.text for node in manifest.iter()}
        self.assertEqual(values["dpiAwareness"], "PerMonitor")
        self.assertEqual(values["dpiAware"], "true/pm")

    def test_allocation_redraw_does_not_modify_weights(self):
        bar = mock.Mock()
        weights = (35.1, 19.2, 45.7)
        view = SimpleNamespace(allocation_canvases={"q": bar}, allocation_percentages={"q": weights})
        CryptoForwardMonitorApp._draw_allocation_bar(view, "q")
        bar.set_allocation.assert_called_once_with(weights)
        self.assertEqual(view.allocation_percentages["q"], weights)
