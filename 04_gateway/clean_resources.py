import json
import os
from pathlib import Path
import boto3


def clean_resources():
    """作成した Gateway リソースをすべてクリーンアップするユーティリティ

    説明:
    - `outbound_gateway.json` に保存された Gateway 設定を読み取り、関連ターゲットを削除して Gateway 本体を削除します。
    - 開発・テスト用に作成した一時的なリソースを整理するための簡易スクリプトです。
    """
    config_file = Path("outbound_gateway.json")

    with config_file.open("r", encoding="utf-8") as f:
        config = json.load(f)

    region = boto3.Session().region_name
    gateway_client = boto3.client('bedrock-agentcore-control', region_name=region)

    gateway_id = config["gateway"]["id"]

    print(f"Gateway {gateway_id} のすべてのターゲットを削除しています。")
    list_response = gateway_client.list_gateway_targets(
        gatewayIdentifier=gateway_id,
        maxResults=100
    )
    for item in list_response['items']:
        target_id = item["targetId"]
        print(f"ターゲット {target_id} を削除しています。")
        gateway_client.delete_gateway_target(
            gatewayIdentifier=gateway_id,
            targetId=target_id
        )
    print(f"Gateway {gateway_id} を削除しています。")
    gateway_client.delete_gateway(gatewayIdentifier=gateway_id)

    os.remove(".agentcore.yaml")
    os.remove("outbound_gateway.json")


if __name__ == "__main__":
    clean_resources()
