"""Run the built EXE against a temporary isolated config; NO login/GPT/engine."""
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ai_shadow.storage import atomic_text


def main():
    exe = ROOT/'CryptoForwardMonitor/dist/CryptoForwardMonitor.exe'
    output = ROOT/'artifacts/ai_shadow_local/exe_smoke.json'
    with tempfile.TemporaryDirectory(prefix='CFM-exe-smoke-') as directory:
        temp = Path(directory)
        config = json.loads((ROOT/'CryptoForwardMonitor/config.example.json').read_text(encoding='utf-8'))
        config.update(model_workdir=str(temp),app_data_dir=str(temp/'monitor'),status_file=str(temp/'status.md'),
                      v310_portfolio_file=str(temp/'q.csv'),v31_portfolio_file=str(temp/'b.csv'),auto_refresh=False)
        path = temp/'config.json'
        atomic_text(path,json.dumps(config))
        result = subprocess.run([str(exe),'--config',str(path),'--smoke-ui-receipt',str(temp/'receipt.json')],
                                timeout=45,creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode==0, f'EXE exited {result.returncode}'
        receipt = json.loads((temp/'receipt.json').read_text(encoding='utf-8'))
        assert receipt['status']=='PASS' and receipt['packaged'] and not receipt['ai_enabled']
        assert receipt['policy_resource'] and receipt['gpt_requests']==0 and receipt['vault_operations']==0
        receipt.update(exe_sha256=hashlib.sha256(exe.read_bytes()).hexdigest(),exe_bytes=exe.stat().st_size,
                       exit_code=result.returncode)
        atomic_text(output,json.dumps(receipt,ensure_ascii=False,indent=2))
    print(json.dumps(receipt,ensure_ascii=False))


if __name__=='__main__':
    main()
