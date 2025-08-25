# standard library imports
import os
import json

# third party imports
from dotenv import load_dotenv
from flask import Flask, request, jsonify, Response
from miru_server_sdk import Miru, Webhook, WebhookVerificationError, types


app = Flask(__name__)


def get_env_var(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"{name} is not set")
    return value


load_dotenv()
API_KEY = get_env_var("MIRU_API_KEY")
WEBHOOK_SECRET = get_env_var("MIRU_WEBHOOK_SECRET")


miru_client = Miru(api_key=API_KEY)


@app.route("/webhooks/miru", methods=["POST"])
def webhook_endpoint() -> tuple[Response, int]:
    print("Webhook received")

    headers = dict(request.headers)
    payload = request.get_data()

    # verify the webhook signature
    try:
        wh = Webhook(WEBHOOK_SECRET)
        webhookPayload = wh.verify(payload, headers)
    except WebhookVerificationError as e:
        return jsonify({
            'valid': False,
            'message': str(e),
            'errors': []
        }), 400

    print("\nWebhook payload:")
    print(json.dumps(webhookPayload, indent=2, ensure_ascii=False))

    event = miru_client.webhooks.unwrap(webhookPayload)
    if event.type == "config_instance.target_status.validated":
        handle_config_instance_validation(event)
    # ignore events which aren't config instance target status validated
    else:
        return jsonify({'message': 'no action required'}), 200

    # return a valid response
    return jsonify({
        'message': 'config instance validation handled successfully'
    }), 200


def handle_config_instance_validation(event: types.UnwrapWebhookEvent):
    # retrieve the config instance with its content
    config_instance = miru_client.config_instances.retrieve(
        event.data.config_instance.id,
        expand=["content"]
    )

    # validate and deploy the config instance
    if is_config_instance_valid(config_instance):
        # approve the config instance
        miru_client.config_instances.approve(
            config_instance.id,
            message="Config instance is valid"
        )

        # deploy the config instance
        deploy_response = miru_client.config_instances.deploy(
            config_instance.id,
        )

        print("\nDeploying config instance response:")
        print(deploy_response.to_json())

    # reject the config instance
    else:
        miru_client.config_instances.reject(
            config_instance.id,
            message="Config instance is invalid",
            errors=[
                {
                    "message": "Expected a string but got a number",
                    "parameter_path": ["path", "to", "invalid", "parameter"],
                }
            ]
        )


def is_config_instance_valid(config_instance: types.ConfigInstance) -> bool:
    if config_instance.content is None:
        raise ValueError("Config instance content is None")

    print("\nConfig instance content:")
    print(json.dumps(config_instance.content, indent=2, ensure_ascii=False))

    return True


@app.route("/", methods=["GET"])
def health_check() -> tuple[Response, int]:
    return jsonify({'message': 'ok'}), 200


if __name__ == "__main__":
    app.run()
