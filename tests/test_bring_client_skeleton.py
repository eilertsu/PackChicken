def test_import_bring_client():
    from packchicken.clients.bring_client import BringClient, BringResult
    assert BringClient is not None
    assert BringResult is not None
