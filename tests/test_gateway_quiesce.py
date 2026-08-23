from tests.fake_gateway import FakeGateway


def test_fake_gateway_quiesce_records() -> None:
    gw = FakeGateway(projects=[])
    gw.quiesce_guest("i-1")
    assert gw._quiesced == ["i-1"]
    gw.unquiesce_guest("i-1")
    assert gw._unquiesced == ["i-1"]


def test_sdk_gateway_has_quiesce_methods() -> None:
    from osbak.discovery.gateway import SDKGateway

    assert hasattr(SDKGateway, "quiesce_guest")
    assert hasattr(SDKGateway, "unquiesce_guest")
