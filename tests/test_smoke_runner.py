from scripts.run_live_checks import smoke_identity


def test_smoke_cache_cannot_reuse_another_namespace_model_or_code():
    original=smoke_identity('stage-a','model-a','code-a')[1]
    assert original!=smoke_identity('stage-b','model-a','code-a')[1]
    assert original!=smoke_identity('stage-a','model-b','code-a')[1]
    assert original!=smoke_identity('stage-a','model-a','code-b')[1]
