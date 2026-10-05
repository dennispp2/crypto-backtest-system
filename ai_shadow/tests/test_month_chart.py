import json

import pytest


def test_incomplete_month_cannot_be_presented_as_a_completed_comparison(tmp_path):
    from scripts.plot_month_gpt_comparison import prepare
    run,output = tmp_path/'run',tmp_path/'chart'
    run.mkdir()
    (run/'run_receipt.json').write_text(json.dumps({'status':'WAITING_FOR_GPT','test_window_completed':False}),encoding='utf-8')
    with pytest.raises(ValueError,match='MONTH_NOT_COMPLETE'):
        prepare(run,output)
    assert not output.exists()
