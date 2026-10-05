"""Compact Traditional Chinese AI presentation; worker results dispatched to Tk."""
from __future__ import annotations

import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox

import customtkinter as ctk

from ai_shadow.errors import AIError
from ui_components import UI_COLORS, Button, Card, Label, SmoothScrollPage, frame, font, wrapping_label

USAGE_URL = 'https://chatgpt.com/settings/usage'
ERROR_TEXT = {
    'AI_DISABLED':'AI 尚未啟用；V3.10 正常獨立運作', 'GENESIS_REQUIRED':'請先建立 AI 紙上起始帳戶',
    'READY':'已就緒，按「執行每日模型」開始', 'AI_COMPLETED':'AI 決策已完成',
    'TODAY_AI_ALREADY_COMPLETED':'今天 AI 已完成，不會重複交易', 'AUTH_REQUIRED':'請先登入 ChatGPT',
    'REAUTH_REQUIRED':'授權已失效，請重新登入', 'TOKEN_EXPIRED':'登入憑證到期，請重新登入',
    'PLAN_USAGE_NOT_AUTHORIZED':'此帳號尚未允許 ChatGPT Plan Usage', 'USER_NOT_ELIGIBLE':'此帳號不符合目前方案使用資格',
    'USAGE_LIMIT_EXCEEDED':'ChatGPT 使用量已達限制；請查看用量設定',
    'USAGE_UNAVAILABLE':'暫時無法確認 ChatGPT 用量；稍後重試', 'MODEL_NOT_AVAILABLE':'模型在此帳號不可用，請重新選擇',
    'EXPERIMENT_VERSION_MISMATCH':'設定與凍結實驗不同；請建立新實驗', 'CRITICAL_DATA_STALE':'關鍵行情／帳本過期，已禁止交易',
    'WEB_SEARCH_UNAVAILABLE':'網頁研究不可用，改用 Provider 資料', 'GPT_TIMEOUT':'GPT 請求逾時，沒有成交',
    'STREAM_INTERRUPTED':'GPT 串流中斷，沒有成交', 'INVALID_STRUCTURED_OUTPUT':'GPT 輸出格式不合法，沒有成交',
    'V310_FAILED_AI_BLOCKED':'V3.10 執行失敗，AI 交易已停止', 'AI_RUN_IN_PROGRESS':'另一個視窗正在執行 AI',
    'FROZEN_HASH_FAIL':'凍結檔案校驗失敗，禁止增加曝險', 'SECURE_CREDENTIAL_STORAGE_UNAVAILABLE':'Windows 安全憑證儲存不可用',
    'GPT_FAILED':'GPT 暫時無法完成，沒有成交', 'EXTERNAL_DATA_PARTIAL':'補充資料不完整；缺失項目不會被假數據取代',
    'RISK_GATEWAY_BLOCKED':'硬風控阻擋了這次交易；持倉維持不變', 'PAPER_EXECUTION_FAILED':'紙上成交未通過對帳，沒有寫入成交',
    'AI_AUDIT_CHAIN_INVALID':'AI 帳本校驗失敗，已停止交易', 'AI_SETTINGS_FAILED':'設定操作失敗，請檢查本機設定',
    'AI_CONFIGURATION_INVALID':'AI 設定無效，已停用 AI；V3.10 仍可執行。修正 AI 成本／風控設定後重開 App。',
    'AUDIT_EXPORT_PENDING':'成交已安全存入帳本，但部分 CSV／JSON 尚未匯出；關閉佔用檔案後可重建匯出',
    'RESPONSE_INCOMPLETE':'GPT 回覆未完整結束，沒有成交', 'GPT_REFUSED':'GPT 未提供決策，沒有成交',
}
ACTION_TEXT = {'ADD':'加碼', 'STRONG_ADD':'積極加碼', 'HOLD':'維持部位', 'REDUCE':'減碼', 'EXIT':'退出加密部位'}


def outcome_text(code):
    return ERROR_TEXT.get(code, 'AI 未完成，沒有成交：'+str(code))


def percentage(value):
    return '樣本不足／尚無資料' if value is None else f'{value:+.2%}'


def render_decision(view):
    if not view:
        return 'AI 尚未啟用。\n工具與設定 → ChatGPT 與 AI 設定。'
    hybrid = (view.get('genesis') or {}).get('strategy_mode') == 'v310_hybrid'
    lines = [outcome_text(view.get('outcome')), ('V3.10 為主要依據，AI 補充判讀；綜合帳本與純 V3.10 比較組分離。'
             if hybrid else '僅紙上模擬；AI 與 V3.10 / V3.1 分離。')]
    if view.get('export_warning'):
        lines.append(outcome_text(view['export_warning']))
    if not view.get('state'):
        return '\n\n'.join(lines)
    state, genesis, cycle = view['state'], view['genesis'], view.get('cycle')
    lines += ['【V3.10＋AI 綜合紙上帳戶】' if hybrid else '【獨立紙上帳戶】', f"實驗：{genesis['experiment_id']}\n模型：{genesis['model_slug']}\n開始：{genesis['genesis_timestamp']}",
              f"總資產 ${state['nav']:,.2f}｜BTC {state['btc_units']:.8f}｜ETH {state['eth_units']:.8f}｜現金 ${state['cash']:,.2f}",
              f"新增本金 ${state['external_contributions']:,.2f}｜手續費 ${state['fees']:,.2f}｜滑價 ${state['slippage']:,.2f}",
              '估值時間：'+state['timestamp']+'（最後一次紙上處理時間，非即時重估）',
              '均價基準是啟用時市價，不是繼承的歷史買入均價。']
    if not cycle:
        return '\n\n'.join(lines+['尚無 GPT 決策；資料不足時不交易。'])
    decision, risk, metrics = cycle['decision'], cycle['risk_gateway'], cycle['metrics']
    lines += ['【今天的決策】', f"請求：{ACTION_TEXT[decision['action']]}｜信心 {decision['confidence']:.0%}\n"
              f"批准：{ACTION_TEXT[risk['action']]}｜曝險 {risk['exposure']:.1%}｜Gateway {risk['status']}\n"
              f"批准配置：BTC {risk['weights']['BTC']:.1%} / ETH {risk['weights']['ETH']:.1%} / 現金 {risk['weights']['Cash']:.1%}\n"
              f"原因：{', '.join(risk['reasons']) or '通過硬風控'}\n研究論點：{'；'.join(decision['thesis'])}",
              '【相同起點績效】', f"GPT TWR：{percentage(metrics['total_return_since_genesis'])}\n"
              f"V3.10 同起點 TWR：{percentage(metrics['v310_return_since_same_genesis'])}\n"
              f"Alpha：{percentage(metrics['alpha_since_genesis'])}\n最大回撤：{percentage(metrics['max_drawdown'])}\n"
              f"波動率：{percentage(metrics['volatility'])}｜CAGR：{percentage(metrics['twr_cagr'])}\n"
              f"Sharpe {metrics['sharpe']}｜Sortino {metrics['sortino']}｜Calmar {metrics['calmar']}\n{metrics['sample_warning']}",
              f"V3.10 同起點最大回撤：{percentage(metrics.get('v310_max_drawdown'))}\n"
              f"V3.10 同起點波動率：{percentage(metrics.get('v310_volatility'))}\n"
              f"戰術週轉：AI {metrics['tactical_turnover']:.4f}x / V3.10 {metrics.get('v310_turnover')}\n"
              f"手續費：AI ${metrics['fees']:,.2f} / V3.10 {metrics.get('v310_fees')}\n"
              f"成交筆數：AI {metrics['trade_count']} / V3.10 {metrics.get('v310_trade_count')}（總筆數無資料時不推測）\n"
              '注意：這是同起點、排除外部本金的比較，不是同一 tick 的配對實驗。\n'
              'V3.10 回撤／波動率按 AI 決策觀測點計算；AI 回撤另包含補入帳時的已完成 4H 估值。',
              '【健康分數（GPT 判斷，非客觀機率）】',
              '\n'.join(f"{key}: {value}/100" for key,value in decision.items() if key.endswith('_health')),
              f"多頭 {decision['bull_probability']:.0%}｜基本 {decision['base_probability']:.0%}｜空頭 {decision['bear_probability']:.0%}",
              f"入場後論點狀態：{decision['thesis_status']}｜V3.10 意見：{decision['v310_view']}",
              '【支持因素】', '\n'.join('• '+s for s in decision['key_positive_factors']) or '無',
              '【主要風險】', '\n'.join('• '+s for s in decision['key_risks']) or '無',
              '【論點失效條件】', '\n'.join('• '+s for s in decision['invalidation_conditions']) or '無',
              '【本次紙上成交】']
    for order in cycle['orders']:
        lines.append(f"{order['fill_time']}｜{order['asset']} {order['side']} {order['quantity']:.8f}\n"
                     f"${order['notional']:,.2f} @ ${order['fill_price']:,.2f}｜{order['status']}｜{order['reason']}")
    if not cycle['orders']:
        lines.append('本次沒有成交。')
    lines += ['【資料品質與來源】', f"核心：{cycle['snapshot']['data_freshness']['critical']}｜補充：{cycle['snapshot']['data_freshness']['supplementary']}",
              f"網頁研究：{cycle['research']['status']}\n{cycle['research'].get('brief','')}"]
    for source in cycle['research'].get('sources', []):
        lines.append(f"{source.get('source_title','')}\n{source['source_url']}")
    def source_lines(value, prefix='external'):
        if isinstance(value, dict):
            if 'status' in value:
                lines.append(f"{prefix}：{value['status']}｜{value.get('source','')}｜{value.get('source_timestamp','時間未提供')}")
            for key, child in value.items():
                if isinstance(child, (dict,list)):
                    source_lines(child, prefix+'.'+key)
        elif isinstance(value, list):
            for child in value:
                source_lines(child,prefix)
    source_lines(cycle['snapshot']['external'])
    lines += ['【稽核】', f"決策時間：{cycle['decision_time']}\n完成：{cycle['decision_completed_at']}\n"
              f"Decision ID：{cycle['decision_id']}\nSnapshot SHA256：{cycle['snapshot_hash']}\nPolicy SHA256：{cycle['policy_hash']}\n"
              f"Research SHA256：{cycle.get('research_hash','--')}\nGenesis SHA256：{cycle.get('genesis_hash','--')}"]
    return '\n\n'.join(lines)


class AIUiMixin:
    def _ai_variables(self):
        self.ai_vars = {k:tk.StringVar(value='--') for k in ('status','nav','allocation','decision','alpha','account')}
        self.ai_settings_window = None
        self.ai_settings_busy = False

    def _ai_summary_card(self):
        card = Card(self.main_right, 'AI 執行狀態', subtitle='最後成功判讀 · 非即時績效', color='green')
        card.pack(fill='x', pady=(4,10))
        for key in ('status','account','decision','alpha'):
            wrapping_label(card.content, textvariable=self.ai_vars[key], size=13, color='muted' if key!='status' else 'green')
        Button(card.content, '查看 AI 決策', lambda:self.show_page('AI 決策')).pack(anchor='e', pady=(12,0))

    def _ai_page(self):
        page = frame(self.host)
        self.pages['AI 決策'] = page
        controls = frame(page)
        controls.pack(fill='x', pady=(0,12))
        Button(controls, 'ChatGPT 與 AI 設定', self.show_ai_settings, width=180).pack(side='left')
        Button(controls, '管理 ChatGPT 用量', lambda:webbrowser.open(USAGE_URL), width=170).pack(side='left', padx=12)
        Button(controls, '重建 CSV／JSON 匯出', lambda:self._ai_job(self.ai.repair_exports), width=180).pack(side='left')
        card = Card(page, 'V3.10＋AI 決策與紙上交易', subtitle='量化基線＋AI 判讀＋風控後配置｜純 V3.10 保留比較｜不會下真實訂單')
        card.pack(fill='both', expand=True)
        self.ai_text = ctk.CTkTextbox(card.content, font=font(15), wrap='word',
                                    fg_color=UI_COLORS['surface'], text_color=UI_COLORS['text'])
        self.ai_text.pack(fill='both', expand=True)
        self.ai_text.configure(state='disabled')

    def apply_ai_view(self, view):
        self.ai_vars['status'].set(outcome_text((view or {}).get('outcome','AI_DISABLED')))
        account = (view or {}).get('account')
        self.ai_vars['account'].set('已登入 · '+str(account.get('email') or 'ChatGPT 帳號') if account else 'ChatGPT 尚未登入')
        state = (view or {}).get('state')
        self.ai_vars['nav'].set(f"${state['nav']:,.2f}" if state else '尚未建立帳戶')
        self.ai_vars['allocation'].set(f"BTC {state['btc_value']/state['nav']:.1%} · ETH {state['eth_value']/state['nav']:.1%} · 現金 {state['cash']/state['nav']:.1%}" if state else '不會自動複製之後的 V3.10 交易')
        cycle = (view or {}).get('cycle')
        self.ai_vars['decision'].set(f"{ACTION_TEXT[cycle['decision']['action']]} · 信心 {cycle['decision']['confidence']:.0%} · {cycle['risk_gateway']['status']}" if cycle else '等待首次 AI 決策')
        self.ai_vars['alpha'].set('同起點 Alpha '+percentage(cycle['metrics']['alpha_since_genesis']) if cycle else '同起點 Alpha 尚無資料')
        text = render_decision(view)
        if self.ai_text.get('1.0','end-1c') != text:
            position = self.ai_text.yview()[0]
            self.ai_text.configure(state='normal')
            self.ai_text.delete('1.0','end')
            self.ai_text.insert('1.0',text)
            self.ai_text.configure(state='disabled')
            self.ai_text.yview_moveto(position)

    def _ai_job(self, job, done=None):
        if self.model_in_progress or self.ai_settings_busy:
            self.notify('模型或登入程序正在執行中，請稍候。')
            return
        self.ai_settings_busy = True
        self.notify('正在處理 ChatGPT 設定…')
        def worker():
            try:
                result = job()
                self.dispatcher.post(self._ai_job_finished, result, done, None)
            except Exception as exc:
                code = exc.code if isinstance(exc,AIError) else 'AI_SETTINGS_FAILED'
                self.dispatcher.post(self._ai_job_finished, None, done, code)
        threading.Thread(target=worker,daemon=True).start()

    def _ai_job_finished(self, result, done, error):
        self.ai_settings_busy = False
        if error:
            self.notify(outcome_text(error), error=True)
        else:
            self.notify('設定操作完成。')
            if done:
                done(result)
        self._refresh_ai_settings()
        self.apply_ai_view(self.ai.view())

    def _refresh_ai_settings(self):
        window = self.ai_settings_window
        if window is None or not window.winfo_exists():
            return
        meta = self.ai.auth.metadata()
        self._account_labels = {f"{a.get('email') or 'ChatGPT 帳號'} · {r[:8]}":r for r,a in meta['accounts'].items()}
        active = self.ai.auth.active_account()
        label = next((k for k,r in self._account_labels.items() if active and r==active['registration']), '尚未登入')
        self.ai_account_picker.configure(values=list(self._account_labels) or ['尚未登入'])
        self.ai_account_var.set(label)
        self.ai_connection_var.set('已登入 · Using ChatGPT plan' if active and active['plan_authorized'] else '尚未允許 ChatGPT Plan Usage')
        self.ai_enabled_var.set(self.ai.settings()['enabled'])

    def show_ai_settings(self):
        if self.model_in_progress:
            self.notify('模型正在執行，暫時不能切換帳號與設定。')
            return
        if self.ai_settings_window and self.ai_settings_window.winfo_exists():
            self.ai_settings_window.lift()
            return
        window = ctk.CTkToplevel(self)
        self.ai_settings_window = window
        window.title('ChatGPT 與 V3.10＋AI 設定')
        window.geometry('760x670')
        window.transient(self)
        window.configure(fg_color=UI_COLORS['background'])
        page = SmoothScrollPage(window)
        page.pack(fill='both',expand=True,padx=18,pady=18)
        card = Card(page.content, '使用你的 ChatGPT 方案', subtitle='沒有 API Key／付費 API 備援；資格與模型由帳號決定')
        card.pack(fill='x')
        self.ai_connection_var = tk.StringVar(value='尚未登入')
        wrapping_label(card.content,textvariable=self.ai_connection_var,color='green')
        self.ai_account_var = tk.StringVar(value='尚未登入')
        self.ai_account_picker = ctk.CTkOptionMenu(card.content, variable=self.ai_account_var, values=['尚未登入'],
                                                command=self._select_ai_account, width=500,font=font(14))
        self.ai_account_picker.pack(fill='x',pady=12)
        buttons = frame(card.content)
        buttons.pack(fill='x')
        Button(buttons,'Continue with ChatGPT',lambda:self._login_ai(False),width=220,primary=True).pack(side='left')
        Button(buttons,'重新登入',lambda:self._login_ai(True)).pack(side='left',padx=10)
        Button(buttons,'登出',lambda:self._ai_job(self.ai.auth.logout,self._logout_done),width=80).pack(side='left')
        Button(card.content,'管理 ChatGPT 用量',lambda:webbrowser.open(USAGE_URL),width=180).pack(anchor='w',pady=12)
        model = Card(page.content,'GPT 模型與綜合帳本',subtitle='模型、政策或風控改變都要新實驗；舊帳本永久保留')
        model.pack(fill='x',pady=14)
        self.ai_model_var = tk.StringVar(value=self.ai.settings().get('model') or '先載入可用模型')
        self._model_labels = {}
        self.ai_model_picker = ctk.CTkOptionMenu(model.content,variable=self.ai_model_var,values=[self.ai_model_var.get()],
                                              font=font(14),width=500)
        self.ai_model_picker.pack(fill='x',pady=8)
        Button(model.content,'載入此帳號可用模型',lambda:self._ai_job(lambda:self.ai.client_factory().list_models(),self._models_done),width=220).pack(anchor='w',pady=8)
        self.ai_enabled_var = tk.BooleanVar(value=self.ai.settings()['enabled'])
        ctk.CTkSwitch(model.content,text='一鍵執行 V3.10＋AI 判讀',variable=self.ai_enabled_var,font=font(14),
                      command=self._toggle_ai).pack(anchor='w',pady=12)
        Button(model.content,'啟用 V3.10＋AI／建立新綜合帳本…',self._create_ai_genesis,width=330,primary=True).pack(anchor='w',pady=8)
        wrapping_label(model.content,text='啟用時複製最新 V3.10 的 BTC／ETH 數量及現金，之後獨立運作。\n'
                       '市場與紙上持倉將傳送給 OpenAI 分析；不傳送交易所帳號或登入憑證。\n'
                       '補充資料可能缺失，Live OAuth／GPT 的實際資格需你登入後驗證。',size=13)
        Button(model.content,'開啟 AI 成本／風控設定',lambda:self.open_path(self.ai.root/'runtime_config.json'),width=240).pack(anchor='w',pady=12)
        wrapping_label(model.content,text='修改成本或 freshness 後需重新開啟 App 並建立新實驗。既有實驗不能套用新參數。',size=13)
        self._refresh_ai_settings()
        window.after(150,window.lift)

    def _login_ai(self, returning):
        account = self.ai.auth.active_account()
        registration = account['registration'] if returning and account else None
        self._ai_job(lambda:self.ai.auth.sign_in(registration),self._login_done)

    def _login_done(self, account):
        settings = self.ai.settings()
        seen = settings.get('welcome_seen',[])
        if account['plan_authorized'] and account['registration'] not in seen:
            messagebox.showinfo('正在使用你的 ChatGPT 方案','合資格的 AI 請求會使用你的 ChatGPT 方案／點數餘額。\n可在「管理 ChatGPT 用量」查看和調整限制。',parent=self)
            self.ai.remember_welcome(account['registration'])

    def _logout_done(self, confirmed):
        if not confirmed:
            self.notify('本機憑證已清除，但遠端撤銷未確認；請到 ChatGPT 設定檢查授權。',error=True)

    def _select_ai_account(self, label):
        registration = self._account_labels.get(label)
        if registration:
            self._ai_job(lambda:self.ai.auth.select(registration),lambda _:self._clear_models())

    def _clear_models(self):
        self._model_labels = {}
        self.ai_model_picker.configure(values=['請重新載入此帳號模型'])
        self.ai_model_var.set('請重新載入此帳號模型')

    def _models_done(self, models):
        if not self.ai_settings_window or not self.ai_settings_window.winfo_exists():
            return
        self._model_labels = {f"{m['display_name']} · {m['slug']}":m['slug'] for m in models}
        self.ai_model_picker.configure(values=list(self._model_labels) or ['沒有可用模型'])
        selected = next((label for label,slug in self._model_labels.items() if slug==self.ai.settings()['model']), None)
        self.ai_model_var.set(selected or next(iter(self._model_labels),'沒有可用模型'))

    def _toggle_ai(self):
        enabled = self.ai_enabled_var.get()
        self._ai_job(lambda:self.ai.configure(enabled=enabled))

    def _create_ai_genesis(self):
        model = self._model_labels.get(self.ai_model_var.get())
        if not model:
            self.notify('先載入並選擇此帳號可用模型。',error=True)
            return
        if messagebox.askyesno('確認綜合紙上帳本','接續目前 V3.10 的 BTC／ETH 數量與現金，建立 V3.10＋AI 綜合帳本？\n\n不重設成 $20,000，不匯入歷史回測獲利。\n舊實驗不刪除，右側純 V3.10 不受影響。\nAI 以量化狀態為基線判讀，HOLD 不複製純版交易；行情刷新不會執行 GPT。',parent=self):
            def initialize_combined():
                return self.ai.initialize(model, strategy_mode='v310_hybrid')
            self._ai_job(initialize_combined)
