"""One-button independent GPT shadow workflow. Called ONLY by daily execution.

Credential handling, providers, decision engine, gateway and broker are separate
seams. Read-only UI access never creates an inference client or fetches providers.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

from jsonschema import validate

from ai_shadow.audit import frozen_ok
from ai_shadow.auth.chatgpt_auth import ChatGPTAuth
from ai_shadow.clients.chatgpt_plan import ChatGPTPlanClient
from ai_shadow.configuration import FreshnessPolicy
from ai_shadow.decision_engine import DecisionEngine
from ai_shadow.errors import AIError
from ai_shadow.metrics import performance
from ai_shadow.paper_broker import BrokerConfig, PaperBroker
from ai_shadow.portfolio import available_at, benchmark, genesis_payload, mark, sync_contributions, weights
from ai_shadow.providers.base import MissingProvider, collect_providers
from ai_shadow.providers.binance import BinanceDerivativesProvider, BinanceSpotProvider
from ai_shadow.providers.liquidity import StablecoinProvider
from ai_shadow.providers.macro import FredProvider
from ai_shadow.risk_gateway import RiskConfig, RiskGateway
from ai_shadow.snapshot import build_snapshot, canonical_hash, canonical_json, utc, validate_asof
from ai_shadow.storage import ShadowStorage, atomic_text, process_lock

SAFE_LOCAL_ERRORS = {'AI_RUN_IN_PROGRESS', 'AI_AUDIT_CHAIN_INVALID', 'CREDENTIAL_IN_JOURNAL',
    'CREDENTIAL_TEXT_IN_JOURNAL', 'FROZEN_LEDGER_CHAIN_INVALID', 'FROZEN_LEDGER_TIME_GAP',
    'FROZEN_LEDGER_ACCOUNTING_INVALID', 'FROZEN_LEDGER_NAV_MISMATCH', 'FROZEN_LEDGER_EMPTY',
    'AI_ACCOUNTING_INVALID', 'AI_NAV_INVALID', 'SOURCE_PREFIX_CHANGED', 'UNEXPECTED_FROZEN_CONTRIBUTION',
    'QUOTE_INVALID', 'QUOTE_BEFORE_DECISION', 'QUOTE_STALE', 'POST_FILL_EXPOSURE_LIMIT',
    'POST_FILL_EXPOSURE_CHANGE_LIMIT', 'POST_FILL_ACCOUNTING_INVALID', 'FUTURE_EVIDENCE',
    'FORBIDDEN_SNAPSHOT_FIELD', 'TECHNICAL_HISTORY_INSUFFICIENT', 'DAILY_CANDLE_GAP',
    'CANDLE_ORDER_INVALID', 'CANDLE_VALUE_INVALID', 'CANDLE_PRICE_INVALID', 'FUTURE_TECHNICAL',
    'RELATIVE_STRENGTH_ASOF_MISMATCH', 'STATUS_LEDGER_MISMATCH'}


@dataclass(frozen=True)
class AIResult:
    outcome: str
    completed: bool = False
    decision_id: str | None = None


class AIOrchestrator:
    def __init__(self, project_root, data_root, read_forward, *, auth=None, market=None, providers=None,
                 client_factory=None, clock=utc, frozen_checker=None, progress=None, freshness=None,
                 broker_config=None, risk_config=None, benchmark_cost_reader=None):
        self.project_root, self.root = Path(project_root).resolve(), Path(data_root).resolve()
        # A misconfigured runtime root must never land inside frozen output.
        frozen_output = self.project_root/'v3_10_forward'
        if self.root == frozen_output or frozen_output in self.root.parents or self.root == self.project_root:
            raise ValueError('AI_DATA_ROOT_UNSAFE')
        self.root.mkdir(parents=True, exist_ok=True)
        self.settings_path = self.root/'settings.json'
        self.read_forward, self.clock = read_forward, clock
        self.freshness = freshness or FreshnessPolicy()
        self.broker_config = broker_config or BrokerConfig()
        self.risk_config = risk_config or RiskConfig()
        self.benchmark_cost_reader = benchmark_cost_reader
        self.auth = auth or ChatGPTAuth(self.root/'auth')
        self.market = market or BinanceSpotProvider(clock=clock)
        self.providers = providers if providers is not None else [FredProvider(),
            BinanceDerivativesProvider(max_age_seconds=self.freshness.derivatives_max_age_seconds),
            StablecoinProvider(max_age_seconds=self.freshness.liquidity_max_age_seconds),
            MissingProvider('etf_flow', 'BTC and ETH daily ETF flow not configured; no news-to-flow substitution'),
            MissingProvider('onchain', 'Exchange flows / whale / LTH verified complete sources unavailable'),
            MissingProvider('events', 'Optional grounded GPT web research supplied separately')]
        self.client_factory = client_factory or (lambda: ChatGPTPlanClient(self.auth,
            registration=(self.auth.active_account() or {}).get('registration')))
        self.frozen_checker = frozen_checker or (lambda: frozen_ok(self.project_root))
        self.progress = progress or (lambda _: None)
        if not self.settings_path.exists():
            atomic_text(self.settings_path, canonical_json({'enabled':False, 'model':None, 'experiment':None}))

    def settings(self):
        return json.loads(self.settings_path.read_text(encoding='utf-8'))

    def configure(self, *, enabled=None, model=None, strategy_mode=None):
        with process_lock(self.root/'cycle.lock'):
            value = self.settings()
            if enabled is not None:
                value['enabled'] = bool(enabled)
            if model is not None:
                value['model'] = model
            if strategy_mode is not None:
                if strategy_mode not in {'independent', 'v310_hybrid'}:
                    raise ValueError('STRATEGY_MODE_INVALID')
                value['strategy_mode'] = strategy_mode
            atomic_text(self.settings_path, canonical_json(value))

    def decision_engine(self, model, *, strategy_mode=None):
        mode = strategy_mode or self.settings().get('strategy_mode', 'independent')
        if mode not in {'independent', 'v310_hybrid'}:
            raise AIError('STRATEGY_MODE_INVALID')
        if mode == 'v310_hybrid':
            policy_file = Path(__file__).parent/'policy/v310_combined_v1.md'
            return DecisionEngine(self.client_factory(), model, clock=self.clock, policy_file=policy_file)
        return DecisionEngine(self.client_factory(), model, clock=self.clock)

    def storage(self):
        experiment = self.settings().get('experiment')
        if not experiment:
            return None
        # IDs are generated UUIDs; corrupted settings cannot redirect writes.
        from uuid import UUID
        experiment = str(UUID(experiment))
        directory = self.root/'experiments'/experiment
        if not (directory/'journal.sqlite3').is_file():
            raise AIError('AI_AUDIT_CHAIN_INVALID')
        return ShadowStorage(directory)

    def repair_exports(self):
        """Regenerate derived files ONLY; never re-run GPT, cash flows or fills."""
        with process_lock(self.root/'cycle.lock'):
            store = self.storage()
            if store is None or not store.verify_chain():
                raise AIError('AI_AUDIT_CHAIN_INVALID')
            store.export()

    def remember_welcome(self, registration):
        with process_lock(self.root/'cycle.lock'):
            settings = self.settings()
            settings['welcome_seen'] = list(dict.fromkeys([*settings.get('welcome_seen', []), registration]))
            atomic_text(self.settings_path, canonical_json(settings))

    def initialize(self, model, *, strategy_mode=None):
        """Explicit GUI Genesis action; NEVER triggered by refresh/run implicitly."""
        with process_lock(self.root/'cycle.lock'):
            account = self.auth.active_account()
            if not account or not account['plan_authorized']:
                raise AIError('AUTH_REQUIRED' if not account else 'PLAN_USAGE_NOT_AUTHORIZED')
            mode = strategy_mode or self.settings().get('strategy_mode', 'independent')
            engine = self.decision_engine(model, strategy_mode=mode)
            if model not in {m['slug'] for m in engine.client.list_models()}:
                raise AIError('MODEL_NOT_AVAILABLE')
            quant, rows, source_hash = self.read_forward()
            now = self.clock()
            if not self.frozen_checker() or quant.get('frozen_hash_status') != 'PASS':
                raise AIError('FROZEN_HASH_FAIL')
            if not 0 <= (now-available_at(rows[-1])).total_seconds() <= self.freshness.quant_max_age_seconds:
                raise AIError('CRITICAL_DATA_STALE')
            quotes = self.market.quotes()
            prices = {a:(q['bid']+q['ask'])/2 for a,q in quotes.items()}
            timestamp = self.clock()
            for q in quotes.values():
                if not 0 <= (timestamp-utc(q['quote_time'])).total_seconds() <= 30 or q['bid'] <= 0 or q['ask'] < q['bid']:
                    raise AIError('QUOTE_INVALID')
            experiment = str(uuid4())
            payload = genesis_payload(rows[-1], source_hash, timestamp, model, engine.policy_hash, experiment,
                                      prices=prices, risk=asdict(self.risk_config))
            payload.update(broker_config=asdict(self.broker_config), fee_bps=self.broker_config.fee_bps,
                           slippage_bps=self.broker_config.slippage_bps, min_notional_usd=self.broker_config.min_notional_usd)
            payload['account_registration'] = account['registration']
            payload['freshness_policy'] = asdict(self.freshness)
            payload['initial_quotes'] = quotes
            payload['strategy_mode'] = mode
            if mode == 'v310_hybrid':
                rules = json.loads((self.project_root/'config/config_frozen_v3_1.json').read_text(encoding='utf-8'))
                payload.update(label='V310_PLUS_AI_PAPER_ONLY', policy_version='v310_combined_v1',
                               v310_hard_floor=rules['hard_floor'],
                               capital_continuity='Existing live V3.10 units and cash; no fresh capital or backtest wealth')
            store = ShadowStorage(self.root/'experiments'/experiment)
            store.create_genesis(payload)
            atomic_text(self.settings_path, canonical_json({**self.settings(), 'enabled':True,
                'model':model, 'experiment':experiment, 'strategy_mode':mode}))
            return payload

    def run(self):
        store = None
        phase = 'preflight'
        try:
            with process_lock(self.root/'cycle.lock'):
                settings = self.settings()
                if not settings['enabled']:
                    return AIResult('AI_DISABLED')
                store = self.storage()
                if store is None:
                    return AIResult('GENESIS_REQUIRED')
                if not store.verify_chain():
                    raise AIError('AI_AUDIT_CHAIN_INVALID')
                day = self.clock().date().isoformat()
                if store.completed_day(day):
                    return AIResult('TODAY_AI_ALREADY_COMPLETED', True)
                genesis = store.genesis()
                account = self.auth.active_account()
                if not account:
                    raise AIError('AUTH_REQUIRED')
                if not account['plan_authorized']:
                    raise AIError('PLAN_USAGE_NOT_AUTHORIZED')
                engine = self.decision_engine(settings['model'])
                if (engine.model != genesis['model_slug'] or engine.policy_hash != genesis['policy_hash'] or
                    genesis['risk_rules'] != asdict(self.risk_config) or genesis['account_registration'] != account['registration'] or
                    genesis['freshness_policy'] != asdict(self.freshness) or
                    genesis['broker_config'] != asdict(self.broker_config)):
                    raise AIError('EXPERIMENT_VERSION_MISMATCH')
                self.progress('建立 V3.10 最新 Snapshot')
                phase = 'snapshot_and_receipts'
                quant, rows, source_hash = self.read_forward()
                now = self.clock()
                if available_at(rows[-1]) > now:
                    raise AIError('FUTURE_EVIDENCE')
                quant = {**quant, 'status_available_at':available_at(rows[-1]).isoformat()}
                state, receipts = sync_contributions(store.state(), rows, now)
                if receipts:
                    state['timestamp'] = now.isoformat()
                    store.commit_receipts({'state':state, 'contributions':receipts})
                self.progress('收集外部市場與已完成日 K')
                phase = 'external_data'
                technical = self.market.technical()
                external = collect_providers(self.providers)
                macro = external.get('macro', {})
                external['risk_assets'] = {k:macro[k] for k in ('sp500_proxy_not_spy','nasdaq_composite_proxy_not_qqq','gold','wti') if k in macro}
                prices = {a:technical[a]['spot_now'] for a in ('BTC','ETH')}
                marked = mark(state, prices)
                allocation = weights(marked, prices)
                view = {k:marked[k] for k in ('nav','btc_units','eth_units','cash','unit_nav','drawdown','external_contributions')}
                view.update(btc_weight=allocation['BTC'], eth_weight=allocation['ETH'], cash_weight=allocation['Cash'],
                            exposure=allocation['BTC']+allocation['ETH'], btc_avg_cost=marked['btc_cost_basis']/marked['btc_units'] if marked['btc_units'] else None,
                            eth_avg_cost=marked['eth_cost_basis']/marked['eth_units'] if marked['eth_units'] else None,
                            cost_basis_label=marked['cost_basis_label'], previous_decision=store.cycles()[-1]['decision'] if store.cycles() else None)
                snapshot = build_snapshot(quant=quant, technical=technical, external=external, portfolio=view, created_at=self.clock(),freshness=self.freshness)
                schema = json.loads((Path(__file__).parent/'schemas/market_snapshot.schema.json').read_text(encoding='utf-8'))
                validate(snapshot, schema)
                decision_id = canonical_hash({'status_date':quant['status_date'], 'snapshot_hash':snapshot['snapshot_hash'],
                                              'policy_hash':engine.policy_hash, 'model_slug':engine.model, 'experiment_id':genesis['experiment_id']})
                if snapshot['data_freshness']['critical'] != 'PASS':
                    raise AIError('CRITICAL_DATA_STALE')
                self.progress('GPT 外部研究與嚴格 JSON 決策')
                phase = 'gpt_decision'
                decision, research, decision_time = engine.run(snapshot)
                completed = self.clock().isoformat()
                # Quote retrieval STARTS after the completed final response.
                self.progress('Risk Gateway 與紙上成交（不是真實下單）')
                phase = 'risk_gateway_and_paper_broker'
                quotes = self.market.quotes()
                fill_prices = {a:(q['bid']+q['ask'])/2 for a,q in quotes.items()}
                frozen_pass = self.frozen_checker() and quant['frozen_hash_status']=='PASS'
                if genesis.get('strategy_mode') == 'v310_hybrid':
                    from ai_shadow.combined import combined_paper_execution
                    approved, end, orders = combined_paper_execution(
                        state, decision, quant, rows[-1], quotes, decision_id, completed,
                        risk_config=self.risk_config, broker_config=self.broker_config,
                        hard_floor=genesis['v310_hard_floor'], clock=self.clock,
                        frozen_hash_pass=frozen_pass)
                else:
                    approved = RiskGateway(self.risk_config).evaluate(decision, weights(state, fill_prices),
                        frozen_hash_pass=frozen_pass)
                    end, orders = PaperBroker(self.broker_config, clock=self.clock, risk_config=self.risk_config).execute(state, approved, quotes, decision_id, completed)
                bench = benchmark(genesis, rows, fill_prices, end['timestamp'])
                if self.benchmark_cost_reader:
                    # Post-decision diagnostics only. NEVER supplied to GPT.
                    try:
                        bench['costs'] = self.benchmark_cost_reader(genesis, end['timestamp'])
                    except Exception:
                        bench['costs'] = {'status':'ERROR', 'reason':'BENCHMARK_COST_UNAVAILABLE'}
                payload = {'decision_id':decision_id, 'day':day, 'experiment_id':genesis['experiment_id'],
                           'timestamp':end['timestamp'], 'policy_version':genesis['policy_version'],
                           'research_hash':canonical_hash(research), 'genesis_hash':canonical_hash(genesis),
                           'model_slug':engine.model, 'policy_hash':engine.policy_hash, 'snapshot_hash':snapshot['snapshot_hash'],
                           'snapshot':snapshot, 'source_v310_file_hash':source_hash, 'decision_time':decision_time,
                           'decision_completed_at':completed, 'decision':decision, 'research':research,
                           'risk_gateway':approved.to_dict(), 'orders':orders, 'contributions':[], 'state':end,
                           'benchmark':bench, 'metrics':performance(genesis, store.records(), end, bench)}
                validate_asof(snapshot, decision_time)
                phase = 'audit_commit'
                if not store.commit_cycle(payload):
                    return AIResult('DUPLICATE_DECISION_ID')
                self.progress('AI 完成，正在更新畫面')
                return AIResult('AI_COMPLETED', True, decision_id)
        except Exception as exc:
            code = exc.code if isinstance(exc, AIError) else str(exc) if str(exc) in SAFE_LOCAL_ERRORS else 'AI_INTERNAL_ERROR'
            if store and store.verify_chain():
                try:
                    import traceback
                    stack = [{'module':Path(f.filename).name, 'function':f.name, 'line':f.lineno}
                             for f in traceback.extract_tb(exc.__traceback__)[-20:]]
                    # Diagnostic stack WITHOUT raw exception/body/source text
                    # or locals, all of which could contain OAuth credentials.
                    store.error(code, self.clock().isoformat(), {'phase':phase,
                                'exception_type':type(exc).__name__, 'stack':stack,
                                'http_status':exc.http_status if isinstance(exc,AIError) else None})
                except Exception:
                    pass
            return AIResult(code)

    def view(self):
        """No HTTP, provider, inference, refresh token or paper execution."""
        settings = self.settings()
        try:
            store = self.storage()
        except (AIError, ValueError):
            return {'enabled':settings['enabled'], 'outcome':'AI_AUDIT_CHAIN_INVALID'}
        account = self.auth.active_account()
        result = {'enabled':settings['enabled'], 'model_slug':settings['model'], 'account':account,
                  'outcome':'GENESIS_REQUIRED' if settings['enabled'] else 'AI_DISABLED'}
        if store:
            if not store.verify_chain():
                return {**result, 'outcome':'AI_AUDIT_CHAIN_INVALID'}
            cycles = store.cycles()
            errors = [r['payload'] for r in store.records() if r['kind']=='ERROR']
            result.update(genesis=store.genesis(), state=store.state(), cycle=cycles[-1] if cycles else None,
                          last_error=errors[-1] if errors else None, export_warning=store.projection_warning())
            result['outcome'] = errors[-1]['code'] if errors and (not cycles or utc(errors[-1]['timestamp']) > utc(cycles[-1]['state']['timestamp'])) else 'AI_COMPLETED' if cycles else 'READY'
            if not settings['enabled']:
                result['outcome'] = 'AI_DISABLED'
        return result
