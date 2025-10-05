# standard library imports
from dataclasses import dataclass
import os
import json

# third party imports
from dotenv import load_dotenv
from flask import Flask, request, jsonify, Response
from miru_server_sdk import Miru, types
from svix.webhooks import Webhook, WebhookVerificationError


app = Flask(__name__)


def get_env_var(name: str) -> str:
    load_dotenv()
    value = os.getenv(name)
    if not value:
        raise ValueError(f"{name} is not set")
    return value


miru_client = Miru(
    # swap the get_env_var helper for your secrets manager if needed
    api_key=get_env_var("MIRU_API_KEY"),
)


@app.route("/webhooks/miru", methods=["POST"])
def webhook_endpoint() -> tuple[Response, int]:
    print("Received webhook")
    headers = dict(request.headers)
    payload = request.get_data()

    try:
        # swap the get_env_var helper for your secrets manager if needed
        wh = Webhook(get_env_var("MIRU_WEBHOOK_SECRET"))
        payload = wh.verify(payload, headers)
    except WebhookVerificationError as e:
        print(f"Webhook verification error: {e}")
        return jsonify({
            'valid': False,
            'message': str(e),
            'errors': []
        }), 400

    print("\nWebhook payload:")
    print(json.dumps(payload, indent=2, ensure_ascii=False), end="\n\n")

    event = miru_client.webhooks.unwrap(payload)
    if event.type == "deployment.validate":
        handle_validate_deployment(event)
    # ignore events which aren't config instance target status validated
    else:
        return jsonify({'message': 'no action required'}), 200

    # return a valid response
    return jsonify({
        'message': 'deployment validation handled successfully'
    }), 200


def handle_validate_deployment(event: types.UnwrapWebhookEvent):
    # retrieve the deployment with its release and config instances
    deployment = miru_client.deployments.retrieve(
        event.data.deployment.id,
        expand=[
            "device",
            "release",
            "config_instances.content",  # type: ignore
        ],
    )
    if deployment.release is None:
        raise ValueError("Deployment release is None")
    release = deployment.release
    if deployment.config_instances is None:
        raise ValueError("Deployment config instances are None")
    config_instances = deployment.config_instances
    if deployment.device is None:
        raise ValueError("Deployment device is None")
    device = deployment.device

    print(
        f"Validating deployment to device {device.name}",
        f"for release {release.version}...\n"
    )

    result = validate_deployment(config_instances)

    response = miru_client.deployments.validate(
        deployment.id, **result.to_dict()
    )
    # Dictionary-based approach for handling validation effects
    effect_handlers = {
        "none": lambda msg: (
            "The validation had no effect on the deployment: {msg}"
        ),
        "stage": lambda msg: (
            "The deployment was successfully approved; since the deployment "
            "required approval to be staged, it is now staged!"
        ),
        "deploy": lambda msg: (
            "The deployment was successfully approved; since the deployment "
            "required approval to be deployed, it is now deploying!"
        ),
        "reject": lambda msg: (
            "The deployment was successfully rejected!"
        ),
        "void": lambda msg: (
            "The deployment was in an invalid state for validation: {msg}"
        ),
    }

    handler = effect_handlers.get(response.effect)
    if handler:
        print(handler(response.message))
    else:
        print(f"Validation effect: {response.effect}")
        print(f"Validation message: {response.message}")


@dataclass
class ParameterValidation:
    message: str
    path: list[str]


@dataclass
class ConfigInstanceValidation:
    id: str
    message: str
    parameters: list[ParameterValidation]


@dataclass
class DeploymentValidation:
    is_valid: bool
    message: str
    config_instances: list[ConfigInstanceValidation]

    def to_dict(self) -> dict:
        return {
            "is_valid": self.is_valid,
            "message": self.message,
            "config_instances": [
                {
                    "id": ci.id,
                    "message": ci.message,
                    "parameters": [
                        {
                            "message": p.message,
                            "path": p.path
                        }
                        for p in ci.parameters
                    ]
                }
                for ci in self.config_instances
            ]
        }


def validate_deployment(
    config_instances: list[types.ConfigInstance],
) -> DeploymentValidation:

    cfg_inst_validations: list[ConfigInstanceValidation] = []

    for config_instance in config_instances:
        # retrieve the config instance content
        if config_instance.content is None:
            raise ValueError("Config instance content is None")

        # do some validation on the config instance
        # ...
        _ = config_instance.content

        cfg_inst_validations.append(ConfigInstanceValidation(
            id=config_instance.id,
            message=(
                "Error message shown on the config instance level in the UI"
            ),
            parameters=[
                ParameterValidation(
                    message=(
                        "Error message shown on the parameter level in the UI"
                    ),
                    path=["path", "to", "invalid", "parameter"],
                )
            ],
        ))

    return DeploymentValidation(
        is_valid=True,
        message="Error message shown on the deployment level in the UI",
        config_instances=cfg_inst_validations,
    )


@app.route("/", methods=["GET"])
def health_check() -> tuple[Response, int]:
    return jsonify({'message': 'ok'}), 200


if __name__ == "__main__":
    app.run()
