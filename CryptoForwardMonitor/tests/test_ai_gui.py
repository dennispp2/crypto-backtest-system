"""AI UI contracts without OAuth, market calls, GPT usage or real engine runs."""
import json
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest import mock

from test_monitor import APP_DIR, FixedMarket, NOW, SAMPLE
from app import CryptoForwardMonitorApp
from ai_ui import render_decision, outcome_text
from ai_shadow.orchestrator import AIResult
from ai_shadow.daily_cycle import DailyCycleResult


class AiGuiTests(unittest.TestCase):
    def test_corrupt_ai_config_does_not_disable_quant_monitor(self):
        from ai_integration import create_ai
        from config import AppConfig
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            folder = temp/'ai_shadow/data'
            folder.mkdir(parents=True)
            (folder/'runtime_config.json').write_text('{broken', encoding='utf-8')
            config = AppConfig.from_mapping({'model_workdir':str(temp),'app_data_dir':str(temp/'monitor')},temp/'config.json')
            ai = create_ai(config)
            self.assertEqual(ai.view()['outcome'],'AI_CONFIGURATION_INVALID')
            self.assertFalse(ai.run().completed)
            self.assertIsNone(ai.auth.active_account())

    def test_complete_cycle_renders_all_nine_health_scores(self):
        from ai_shadow.tests.test_orchestrator import setup
        with tempfile.TemporaryDirectory() as directory:
            ai, _ = setup(Path(directory))
            self.assertTrue(ai.run().completed)
            text = render_decision(ai.view())
            self.assertIn('macro_health: 50/100', text)
            self.assertIn('post_entry_health: 50/100', text)
            self.assertIn('V3.10 同起點最大回撤', text)

    def test_usage_limit_visible_no_reset_invention(self):
        text = outcome_text('USAGE_LIMIT_EXCEEDED')
        self.assertIn('用量',text)
        self.assertNotIn('小時後',text)

    def test_empty_portfolio_does_not_invent_genesis_nav(self):
        text = render_decision({'outcome':'GENESIS_REQUIRED'})
        self.assertIn('起始',text)
        self.assertNotIn('20,000',text)

    def test_ai_failure_not_v310_failure(self):
        from types import SimpleNamespace
        view=SimpleNamespace(model_finished=mock.Mock(),notify=mock.Mock(),apply_ai_view=mock.Mock(),ai=mock.Mock())
        quant=SimpleNamespace(outcome='COMPLETED',completed=True)
        CryptoForwardMonitorApp.daily_cycle_finished(view,DailyCycleResult(quant,AIResult('USAGE_LIMIT_EXCEEDED')))
        view.model_finished.assert_called_once_with(quant)
        self.assertIn('V3.10：COMPLETED',view.notify.call_args.args[0])
        self.assertIn('ChatGPT',view.notify.call_args.args[0])

    def test_ai_page_and_settings_widgets_no_network(self):
        real_init=tk.Tk.__init__
        def hidden(root,*args,**kwargs):
            real_init(root,*args,**kwargs)
            tk.Tk.withdraw(root)
        with tempfile.TemporaryDirectory() as directory:
            temp=Path(directory)
            config=json.loads((APP_DIR/'config.json').read_text(encoding='utf-8'))
            config.update(model_workdir=str(temp),app_data_dir=str(temp),status_file=str(temp/'status.md'),auto_refresh=False,
                          v310_portfolio_file=str(temp/'q.csv'),v31_portfolio_file=str(temp/'b.csv'))
            path=temp/'config.json'
            path.write_text(json.dumps(config),encoding='utf-8')
            with mock.patch.object(tk.Tk,'__init__',hidden),mock.patch.object(CryptoForwardMonitorApp,'refresh_dashboard'):
                window=CryptoForwardMonitorApp(path)
                try:
                    window.show_page('AI 決策')
                    self.assertEqual(window.page_title.cget('text'),'AI 決策')
                    window.apply_ai_view({'outcome':'AI_DISABLED'})
                    window.show_ai_settings()
                    window.update_idletasks()
                    self.assertTrue(window.ai_settings_window.winfo_exists())
                    self.assertEqual(window.ai_model_var.get(),'先載入可用模型')
                    self.assertFalse(window.ai.settings()['enabled'])
                    self.assertEqual(window.ai.auth.metadata()['accounts'],{})
                    self.assertIsNone(window.ai.auth.vault)
                finally:
                    window.close()
