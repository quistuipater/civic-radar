"""Test for the get_db() FastAPI dependency generator itself. Every other
test overrides this dependency entirely (app.dependency_overrides), so its
own generator body -- yield a session, close it in finally -- has never
actually run.
"""

import app.db as db_module


class FakeSession:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def test_get_db_yields_a_session_and_closes_it_in_finally(monkeypatch):
    fake_session = FakeSession()
    monkeypatch.setattr(db_module, "SessionLocal", lambda: fake_session)

    gen = db_module.get_db()
    yielded = next(gen)

    assert yielded is fake_session
    assert fake_session.closed is False

    try:
        next(gen)
    except StopIteration:
        pass
    else:
        assert False, "expected the generator to be exhausted after one yield"

    assert fake_session.closed is True


def test_get_db_closes_the_session_even_if_the_caller_raises(monkeypatch):
    fake_session = FakeSession()
    monkeypatch.setattr(db_module, "SessionLocal", lambda: fake_session)

    gen = db_module.get_db()
    next(gen)

    try:
        gen.throw(RuntimeError("simulated error during request handling"))
    except RuntimeError:
        pass

    assert fake_session.closed is True
