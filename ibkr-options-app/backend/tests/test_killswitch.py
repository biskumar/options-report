from app.killswitch import KillSwitch


def test_starts_disengaged():
    ks = KillSwitch()
    assert ks.engaged is False
    assert ks.as_dict()["engaged"] is False


def test_engage_sets_reason_and_timestamp():
    ks = KillSwitch()
    ks.engage("manual test")
    assert ks.engaged is True
    assert ks.reason == "manual test"
    assert ks.engaged_at is not None
    assert ks.as_dict()["engagedAt"] is not None


def test_disengage_clears_state():
    ks = KillSwitch()
    ks.engage("manual test")
    ks.disengage()
    assert ks.engaged is False
    assert ks.reason is None
    assert ks.engaged_at is None
