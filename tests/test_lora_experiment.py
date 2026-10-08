import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from prepare_lora_data import build_dataset,validate
from train_lora import score_output


def test_source_family_holdout_detects_cross_split_leakage():
    data=build_dataset();validate(data)
    data['splits']['test'].append(data['splits']['train'][0])
    import pytest
    with pytest.raises(AssertionError):validate(data)


def test_selection_evaluation_rejects_invalid_ids_duplicates_and_extra_fields():
    row={'paragraphs':[{'id':'S1:P1','text':'synthetic'}],'selected':['S1:P1']}
    assert score_output('{"selected":["S1:P1"]}',row)['exact']
    for raw in ['{"selected":["invented"]}','{"selected":["S1:P1","S1:P1"]}',
                '{"selected":["S1:P1"],"command":"publish"}','not json']:
        assert not score_output(raw,row)['valid']
    assert score_output('{"selected":[]}',row)['fn']==1
