"""Read-only adapter from existing Monitor data to the independent AI package."""
from pathlib import Path
import sys

# Development imports; packaged module is discovered with PyInstaller --paths.
if not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_shadow.orchestrator import AIOrchestrator
from ai_shadow.orchestrator import AIResult
from ai_shadow.errors import AIError
from ai_shadow.benchmark_costs import frozen_costs
from ai_shadow.configuration import FreshnessPolicy
from ai_shadow.paper_broker import BrokerConfig
from ai_shadow.risk_gateway import RiskConfig
from ai_shadow.storage import atomic_text
from ai_shadow.snapshot import canonical_json
from dataclasses import asdict
import json
from ai_shadow.snapshot import read_frozen_portfolio, utc
from parser import parse_status_file


class UnavailableAI:
    """Fail closed for AI without preventing the original quant App from opening."""
    def __init__(self, root):
        self.root = root
        self.auth = self
        self.progress = lambda _:None

    def settings(self):
        return {'enabled':False, 'model':None, 'experiment':None}

    def view(self):
        return {'outcome':'AI_CONFIGURATION_INVALID', 'enabled':False, 'account':None}

    def run(self):
        return AIResult('AI_CONFIGURATION_INVALID')

    def active_account(self):
        return None

    def metadata(self):
        return {'accounts':{}, 'active':None}

    def unavailable(self, *args, **kwargs):
        raise AIError('AI_CONFIGURATION_INVALID')

    configure = initialize = repair_exports = sign_in = logout = select = client_factory = unavailable


def create_ai(config):
    try:
        return _create_ai(config)
    except (OSError, ValueError, TypeError, KeyError, AIError):
        # Never overwrite broken user settings or silently loosen a constraint.
        return UnavailableAI(config.model_workdir/'ai_shadow/data')


def _create_ai(config):
    runtime_root = config.model_workdir/'ai_shadow/data'
    path = runtime_root/'runtime_config.json'
    if not path.exists():
        atomic_text(path, canonical_json({'broker':asdict(BrokerConfig()), 'risk':asdict(RiskConfig()),
                                         'freshness':asdict(FreshnessPolicy())})+'\n')
    runtime = json.loads(path.read_text(encoding='utf-8'))
    def read_forward():
        status = parse_status_file(config.status_file)
        rows, digest = read_frozen_portfolio(config.v310_portfolio_file)
        if utc(status.status_date) != utc(rows[-1]['timestamp']):
            raise ValueError('STATUS_LEDGER_MISMATCH')
        quant = {'status_date':status.status_date.isoformat(), 'v310_state':status.v310_state,
                 'v310_stage':status.v310_stage, 'target_exposure':status.v310_target_exposure/100,
                 'actual_exposure':status.v310_actual_exposure/100, 'drawdown':status.current_drawdown/100 if status.current_drawdown is not None else None,
                 'stage3_candidate':status.stage3_candidate, 'crash':status.crash, 'ahr999':status.ahr999,
                 'tactical_action':status.today_tactical_action, 'frozen_hash_status':status.frozen_hash_status}
        # No resolved candidates, forward outcome files, or raw status text.
        return quant, rows, digest
    return AIOrchestrator(config.model_workdir, runtime_root, read_forward,
                          broker_config=BrokerConfig(**runtime['broker']), risk_config=RiskConfig(**runtime['risk']),
                          freshness=FreshnessPolicy(**runtime['freshness']),
                          benchmark_cost_reader=lambda g,t:frozen_costs(config.model_workdir,g,t))
