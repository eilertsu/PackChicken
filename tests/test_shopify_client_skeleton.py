def test_import_shopify_client():
    from packchicken.clients.shopify_client import ShopifyClient
    assert ShopifyClient is not None
