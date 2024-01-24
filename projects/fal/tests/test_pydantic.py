# demo_4_pytest_subprocess.py
import subprocess
import sys
from typing import Callable

import dill
import dill._dill as dill_serialization
import pydantic
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic._internal._decorators import (
    FieldValidatorDecoratorInfo,
    ModelValidatorDecoratorInfo,
)
from pydantic.config import ConfigDict
from pydantic.fields import FieldInfo


def build_pydantic_model(
    name,
    model_config: ConfigDict,
    model_doc: str | None,
    base_cls,
    model_module: str,
    model_fields: dict[str, FieldInfo],
    model_validators: dict[str, tuple[Callable, ModelValidatorDecoratorInfo]],
    field_validators: dict[str, tuple[Callable, FieldValidatorDecoratorInfo]],
    class_fields: dict,
):
    """Recreate the Pydantic model from the deserialised validator info.

    Arguments:
        name: The name of the model.
        model_config: The model's configuration settings. (UNUSED)
        model_doc: The model's docstring.
        base_cls: The model's base class.
        model_module: The name of the module the model belongs to.
        model_fields: The model's fields.
        model_validators: The model validators of the model.
        field_validators: The field validators of the model.
        class_fields: Anything that is neither a field nor a validator.
    """
    import pydantic

    validators = {
        **{
            name: pydantic.model_validator(mode=info.mode)(func)
            for name, (func, info) in model_validators.items()
        },
        **{
            name: pydantic.field_validator(mode=info.mode)(func)
            for name, (func, info) in field_validators.items()
        },
    }

    model_cls = pydantic.create_model(
        name,
        # __config__=model_config, # UNUSED
        __doc__=model_doc,
        __base__=base_cls,
        __module__=model_module,
        __validators__=validators,
        **model_fields,
        **class_fields,
    )
    return model_cls


@dill.register(type(BaseModel))
def _dill_hook_for_pydantic_models(pickler: dill.Pickler, pydantic_model) -> None:
    if pydantic_model is BaseModel:
        dill_serialization.save_type(pickler, pydantic_model)
        return

    decorators = pydantic_model.__pydantic_decorators__
    model_validators = {
        validator_name: (decorator.func, decorator.info)
        for validator_name, decorator in decorators.model_validators.items()
    }
    field_validators = {
        # validator_name: (decorator.func, decorator.info)
        # for validator_name, decorator in decorators.field_validators.items()
    }

    class_fields = {
        "__annotations__": pydantic_model.__annotations__,
    }
    for class_field_name, class_field_value in pydantic_model.__dict__.items():
        if class_field_name.startswith("_"):
            continue
        elif class_field_name in ("model_fields", "model_config"):
            continue
        elif class_field_name in pydantic_model.model_fields:
            continue
        elif class_field_name in model_validators:
            continue
        elif class_field_name in field_validators:
            continue

        class_fields[class_field_name] = class_field_value

    pickled_model = {
        "name": pydantic_model.__name__,
        "model_config": pydantic_model.model_config,
        "model_doc": pydantic_model.__doc__,
        "base_cls": pydantic_model.__bases__[0],
        "model_module": pydantic_model.__module__,
        "model_fields": pydantic_model.model_fields,
        "model_validators": model_validators,
        "field_validators": field_validators,
        "class_fields": class_fields,
    }
    pickler.save_reduce(build_pydantic_model, tuple(pickled_model.values()))


class Input(BaseModel):
    """A simple Pydantic model used to demonstrate deserialisation via dill.

    Attributes:
        prompt: An input prompt for a generative AI model.
        num_steps: The number of steps to run a generative AI model for.
        validation_counter: A field initialised by default as 0 and incremented by
                            validators (for the purpose of testing).
    """

    prompt: str = ...
    num_steps: int = Field(default=2, ge=1, le=10)
    epochs: int = 10
    validation_counter: int = 0

    def steps_x2(self) -> int:
        """A method which is neither a validator nor provided by Pydantic.

        Computes double of the `num_steps` field value."""
        return self.num_steps * 2

    @field_validator("epochs")
    @classmethod
    def triple_epochs(cls, v: int) -> int:
        """A field validator that multiplies the validated field value by 10."""
        return v * 3

    @model_validator(mode="after")
    def increment(self) -> None:
        """A model post-validator that increments a counter."""
        self.validation_counter += 100


def deserialise_pydantic_model():
    """Serialise (`dill.dumps`) then deserialise (`dill.loads`) a Pydantic model.

    The `recurse` setting must be set, counterintuitively, to prevent excessive
    recursion (refer to e.g. dill issue
    [#482](https://github.com/uqfoundation/dill/issues/482#issuecomment-1139017499)):

        to limit the amount of recursion that dill is doing to pickle the function, we
        need to turn on a setting called recurse, but that is because the setting
        actually recurses over the global dictionary and finds the smallest subset that
        the function needs to run, which will limit the number of objects that dill
        needs to include in the pickle.
    """
    dill.settings["recurse"] = True
    serialized_cls = dill.dumps(Input)
    print("===== DESERIALIZING =====")
    model_cls = dill.loads(serialized_cls)
    print("===== INSTANTIATING =====")
    model = model_cls(prompt="a")
    return model


def validate_deserialisation(model: Input) -> None:
    prompt = model.prompt
    steps = model.num_steps
    steps_x2 = model.steps_x2()
    assert prompt == "a", f"Prompt not retrieved: expected 'a' got {prompt!r}"
    assert steps == 2, f"Steps not retrieved: expected 2 got {steps!r}"
    assert steps_x2 == 4, f"Incorrect `steps_x2()`: expected 4 got {steps_x2}"
    assert model.epochs == 30, "The `validate_epochs` field validator didn't run"
    assert model.validation_counter == 100, "The `increment` model validator didn't run"
    return


def test_deserialise_pydantic_model():
    """Test deserialisation of a Pydantic model succeeds.

    The deserialisation failure mode reproduction is incompatible with pytest (see
    [#29](https://github.com/fal-ai/fal/issues/29#issuecomment-1902241217) for
    discussion) so we directly invoke the current Python executable on this file.
    """
    subprocess_args = [sys.executable, __file__, "--run-deserialisation-test"]
    proc = subprocess.run(subprocess_args, capture_output=True, text=True)
    model_fields_ok = "model-field-missing-annotation" not in proc.stderr
    assert model_fields_ok, "Deserialisation failed (`model_fields` not deserialised)"
    # The return code should be zero or else the deserialisation failed
    deserialisation_ok = proc.returncode == 0
    assert deserialisation_ok, f"Pydantic model deserialisation failed:\n{proc.stderr}"


if __name__ == "__main__" and "--run-deserialisation-test" in sys.argv:
    model = deserialise_pydantic_model()
    validate_deserialisation(model)