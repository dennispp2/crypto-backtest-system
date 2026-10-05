"""Owned-window render QA, OFFLINE with isolated mock data; no real account."""
import ctypes
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'CryptoForwardMonitor'))
sys.path.insert(0,str(ROOT))

from app import CryptoForwardMonitorApp
from ai_shadow.tests.test_orchestrator import setup
from PIL import ImageGrab
from controller import DashboardSnapshot
from portfolio import load_combined_portfolio
sys.path.insert(0,str(ROOT/'CryptoForwardMonitor/tests'))
from test_monitor import FixedMarket, NOW, SAMPLE, PORTFOLIO_SAMPLE
from parser import parse_status
from portfolio import load_portfolio
from ai_shadow.portfolio import mark


def mock_snapshot(temp):
    """Isolated QA fixture, never production holdings or auth."""
    ai, _ = setup(temp/'mock-ledger')
    assert ai.run().completed
    view = ai.view()
    view['genesis']['strategy_mode'] = 'v310_hybrid'
    (temp/'q.csv').write_text(PORTFOLIO_SAMPLE,encoding='utf-8')
    market = FixedMarket().fetch()
    pure = load_portfolio(temp/'q.csv',market)
    # Use the SAME holdings/price scale for both cards. The decision fixture
    # uses BTC=$100 / ETH=$10 and cannot be repriced with $81k / $2.5k as-is.
    state = {
        **view['state'], 'btc_units':pure.btc_units, 'eth_units':pure.eth_units,
        'cash':pure.cash_value, 'btc_cost_basis':pure.btc_units*80656.87,
        'eth_cost_basis':pure.eth_units*2504.39, 'fund_units':pure.total_value,
        'initial_nav':pure.total_value, 'peak_unit_nav':1., 'max_drawdown':0.,
    }
    state = mark(state,{'BTC':market.btc.price,'ETH':market.eth.price})
    view['state'] = state
    view['cycle']['state'] = state
    view['genesis']['state'] = state
    combined = load_combined_portfolio(view,market)
    return DashboardSnapshot(
        parse_status(SAMPLE),market,None,None,pure,pure,(),
        'UI QA ONLY · MOCK DATA',[],{},NOW,NOW,
        ai_view=view,combined_portfolio=combined,
    )


def main():
    folder = ROOT/'artifacts/ai_shadow_local/ui_qa'
    folder.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='CFM-ui-qa-') as directory:
        temp = Path(directory)
        payload = json.loads((ROOT/'CryptoForwardMonitor/config.example.json').read_text(encoding='utf-8'))
        payload.update(model_workdir=str(temp),app_data_dir=str(temp/'monitor'),status_file=str(temp/'status.md'),
                       v310_portfolio_file=str(temp/'q.csv'),v31_portfolio_file=str(temp/'b.csv'),auto_refresh=False)
        config = temp/'config.json'
        config.write_text(json.dumps(payload),encoding='utf-8')
        snapshot = mock_snapshot(temp)
        window = CryptoForwardMonitorApp(config,ui_smoke=True)
        window.title('UI QA ONLY · MOCK DATA · 非真實帳戶')
        window.apply_snapshot(snapshot)
        window.show_page('資產總覽')
        window.notify('介面測試｜模擬資料，非正式帳戶；不會動用你的資金。',error=True)
        # Finish CTk's deiconify/titlebar bootstrap before scheduling closure.
        window.update()
        def capture():
            window.update_idletasks()
            assert window.winfo_ismapped(), 'QA window must be mapped before capture'
            handle = ctypes.windll.user32.GetParent(window.winfo_id())
            captured = ImageGrab.grab(window=handle)
            assert any(high > low for low,high in captured.getextrema()), 'Blank screenshot is not a visual PASS'
            captured.save(folder/'combined_overview_mock.png')
            window.close()
        window.after(1500,capture)
        window.mainloop()
    print(str(folder/'combined_overview_mock.png'))


if __name__=='__main__':
    main()
