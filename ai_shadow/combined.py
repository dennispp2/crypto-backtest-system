"""Live decision synthesis and presentation, separate from frozen engines."""
from dataclasses import replace

from ai_shadow.paper_broker import PaperBroker
from ai_shadow.portfolio import CASH_FIELDS, weights
from ai_shadow.risk_gateway import RiskGateway


def primary_constraints(approved, current, quant, *, hard_floor):
    """Safety veto/clamp, not an optimizer or a new FSM."""
    def hold(reason):
        return replace(approved, status='BLOCK', action='HOLD',
                       exposure=current['BTC']+current['ETH'], weights=dict(current),
                       reasons=[*approved.reasons, reason])
    if approved.action == 'HOLD':
        return approved
    crash = str(quant.get('crash', '')).upper() in {'YES', 'TRUE', '1'}
    if approved.action in {'ADD', 'STRONG_ADD'} and (crash or int(quant.get('v310_stage', 0)) >= 4):
        return hold('V310_CRASH_STAGE4_PRIORITY')
    if approved.exposure < hard_floor:
        exposure = current['BTC']+current['ETH']
        if exposure < hard_floor:
            return hold('NO_FORCED_BUY_BELOW_V310_FLOOR')
        ratio = approved.weights['BTC']/approved.exposure if approved.exposure else (
            current['BTC']/exposure if exposure else .625)
        return replace(approved, status='CLAMP', exposure=hard_floor,
                       weights={'BTC': hard_floor*ratio, 'ETH': hard_floor*(1-ratio), 'Cash': 1-hard_floor},
                       reasons=[*approved.reasons, 'V310_HARD_FLOOR_CLAMP'])
    return approved


def combined_paper_execution(state, decision, quant, source_row, quotes, decision_id, completed,
                             *, risk_config, broker_config, hard_floor, clock, frozen_hash_pass):
    prices = {a:(q['bid']+q['ask'])/2 for a, q in quotes.items()}
    current = weights(state, prices)
    approved = RiskGateway(risk_config).evaluate(decision, current, frozen_hash_pass=frozen_hash_pass)
    approved = primary_constraints(approved, current, quant, hard_floor=hard_floor)
    broker = PaperBroker(broker_config, clock=clock, risk_config=risk_config)
    end, orders = broker.execute(state, approved, quotes, decision_id, completed)
    # Trial broker returns a copy. Never commit a plan spending protected cash.
    protected = min(state['cash'], sum(float(source_row[name]) for name in CASH_FIELDS if name != 'normal_cash'))
    if end['cash'] < protected-1e-8:
        approved = replace(approved, status='BLOCK', action='HOLD',
                           exposure=current['BTC']+current['ETH'], weights=current,
                           reasons=[*approved.reasons, 'V310_PROTECTED_CASH_UNAVAILABLE'])
        end, orders = broker.execute(state, approved, quotes, decision_id, completed)
    return approved, end, orders


def render_combined_result(quant, ai_result, view):
    """Never present a prior failed cycle as today's successful synthesis."""
    lines = ['【V3.10＋AI 綜合結果｜僅紙上模擬】',
             f"V3.10：{quant['v310_state']}｜Stage {quant['v310_stage']}｜目標曝險 {quant['target_exposure']:.1%}",
             f"純 V3.10 實際曝險：{quant['actual_exposure']:.1%}｜原版帳本保留獨立比較。"]
    cycle = (view or {}).get('cycle')
    matches = bool(cycle) and (not ai_result.decision_id or cycle['decision_id'] == ai_result.decision_id)
    if not ai_result.completed or not matches:
        return '\n'.join(lines+[f'AI 未取得本次完整綜合決策：{ai_result.outcome}。',
                               '不將舊 AI 決策冒充本次結果；未執行新的 AI 紙上調整。'])
    decision, risk, state = cycle['decision'], cycle['risk_gateway'], cycle['state']
    total = state['nav']
    lines += [f"AI 建議：{decision['action']}｜信心 {decision['confidence']:.0%}｜要求曝險 {decision['target_total_exposure']:.1%}",
              f"最終風控後動作：{risk['action']}｜{risk['status']}｜核准曝險 {risk['exposure']:.1%}",
              f"核准配置：BTC {risk['weights']['BTC']:.1%}／ETH {risk['weights']['ETH']:.1%}／現金 {risk['weights']['Cash']:.1%}",
              f"綜合帳本實際配置：BTC {state['btc_value']/total:.1%}／ETH {state['eth_value']/total:.1%}／現金 {state['cash']/total:.1%}",
              f"綜合帳本總資產：US${total:,.2f}｜承接持倉與現金，不重設本金。",
              '主要理由：'+'；'.join(decision['thesis']),
              '風控說明：'+'、'.join(risk['reasons'] or ['通過']),
              '【本次綜合版紙上成交】']
    fills = [o for o in cycle['orders'] if o['status'] == 'FILLED']
    lines += [f"{o['fill_time']}｜{o['asset']} {o['side']} {o['quantity']:.8f}｜US${o['notional']:,.2f} @ US${o['fill_price']:,.2f}"
              for o in fills] or ['沒有紙上成交。']
    return '\n'.join(lines)
