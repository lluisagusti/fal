import time

import fal
import pytest
from fal import apps
from pydantic import BaseModel


class Input(BaseModel):
    lhs: int
    rhs: int
    wait_time: int = 0


class Output(BaseModel):
    result: int


@fal.function(
    keep_alive=0,
    machine_type="S",
    serve=True,
    max_concurrency=1,
)
def addition_app(input: Input) -> Output:
    print("starting...")
    for _ in range(input.wait_time):
        print("sleeping...")
        time.sleep(1)

    return Output(result=input.lhs + input.rhs)


@pytest.fixture(scope="module")
def temp_app_id():
    """Create a temporary app, register it, and return the ID of it."""
    from fal.cli import _get_user_id

    app_revision = addition_app.host.register(
        func=addition_app.func, options=addition_app.options
    )
    user_id = _get_user_id()
    yield f"{user_id}-{app_revision}"


def test_app_client(temp_app_id: str):
    """Add numbers together, with minimal args and then with `wait_time` too.

    Arguments:
      temp_app_id: app ID of the served calculator app (in a pytest fixture).
    """
    response = apps.run(temp_app_id, arguments={"lhs": 1, "rhs": 2})
    assert response["result"] == 3

    response = apps.run(temp_app_id, arguments={"lhs": 2, "rhs": 3, "wait_time": 1})
    assert response["result"] == 5
