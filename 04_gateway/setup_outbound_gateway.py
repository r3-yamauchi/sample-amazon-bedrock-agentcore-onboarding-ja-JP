"""
AgentCore SDK を使って Lambda ターゲット付きの AgentCore Gateway を作成する
"""

import json
import logging
import argparse
import boto3
from pathlib import Path
from typing import Optional
from rich.console import Console
from rich.panel import Panel
from bedrock_agentcore_starter_toolkit.operations.gateway.client import GatewayClient

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

PROVIDER_NAME = "outbound-identity-for-cost-estimator-agent"
IDENTITY_FILE = Path("../03_identity/inbound_authorizer.json")
CONFIG_FILE = Path("outbound_gateway.json")


def setup_gateway(provider_name: str = PROVIDER_NAME, force: bool = False) -> dict:
    """
    AgentCore Gateway を作成して Lambda ターゲットを追加するユーティリティ

    この関数の概要（初心者向け）:
    1. 03_identity で作成した Inbound Authorizer（Cognito）を利用して Gateway を作成
    2. Gateway に Lambda をアウトバウンドターゲットとして登録
    3. 作成情報を `outbound_gateway.json` に保存

        引数:
            provider_name: 使用するクレデンシャルプロバイダ名（デフォルトを利用可）
            force: True の場合、既存 Gateway を削除して再作成する

        戻り値:
            dict: 作成・更新した設定
    """

    config = load_config()
    region = boto3.Session().region_name

    has_provider = config and 'provider' in config
    has_gateway = config and 'gateway' in config

    control_client = boto3.client('bedrock-agentcore-control', region_name=region)
    gateway_client = GatewayClient(region_name=region)
    
    # すべてが既に設定済みで --force が指定されていなければ終了
    if config and has_provider and has_gateway and not force:
        logger.info("すべてのコンポーネントは既に構成されています（再作成するには --force を使用してください）")
        return config
    elif config:
        if has_gateway and force:
            logger.info("既存の Gateway を削除しています...")
            delete_gateway(gateway_client, config)
            has_gateway = False
    
    if not has_gateway:
        logger.info("認証プロバイダー付きで Gateway を作成しています...")

        logger.info("ファイルから identity 設定を読み込んでいます...")
        if IDENTITY_FILE.exists():
            with open(IDENTITY_FILE) as f:
                identity_config = json.load(f)
        else:
            raise FileNotFoundError("Identity 設定ファイルが見つかりません")

        gateway_name = "AWSCostEstimatorGateway"
        authorizer_config = {
            "customJWTAuthorizer": {
                "discoveryUrl": identity_config["cognito"]["discovery_url"],
                "allowedClients": [identity_config["cognito"]["client_id"]]
            }
        }
        gateway = gateway_client.create_mcp_gateway(
            name=gateway_name,
            role_arn=None,
            authorizer_config=authorizer_config,
            enable_semantic_search=False
        )
            
        gateway_id = gateway["gatewayId"]
        gateway_url = gateway["gatewayUrl"]

        logger.info("Gateway を作成しました")

        logger.info("Gateway に Lambda ターゲットを追加しています...")
        tool_schema = [
            {
                "name": "markdown_to_email",
                "description": "Markdown コンテンツをメール形式に変換します",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "markdown_text": {
                            "type": "string",
                            "description": "メール形式に変換する Markdown コンテンツ"
                        },
                        "email_address": {
                            "type": "string",
                            "description": "受信者のメールアドレス"
                        },
                        "subject": {
                            "type": "string",
                            "description": "メールの件名"
                        }
                    },
                    "required": ["markdown_text", "email_address"]
                }
            }
        ]

        # Lambda ターゲットを作成（credentialProviderConfigurations が必要）
        # 注意: toolkit の create_mcp_gateway_target はカスタム target_payload + credentials を扱いません
        # 参照: https://github.com/aws/bedrock-agentcore-starter-toolkit/pull/57 
        target_name = gateway_name + "Target"
            
        create_request = {
            "gatewayIdentifier": gateway_id,
            "name": target_name,
            "targetConfiguration": {
                "mcp": {
                    "lambda": {
                        "lambdaArn": config["lambda_arn"],
                        "toolSchema": {
                            "inlinePayload": tool_schema
                        }
                    }
                }
            },
            "credentialProviderConfigurations": [{"credentialProviderType": "GATEWAY_IAM_ROLE"}]
        }

        target_response = control_client.create_gateway_target(**create_request)            
        target_id = target_response["targetId"]
        # 作成後すぐに Gateway 設定を保存
        save_config({
            "gateway": {
                "id": gateway_id,
                "url": gateway_url,
                "target_id": target_id
            }
        })
        logger.info("✅ Gateway 設定を保存しました")            
        logger.info("✅ Gateway のセットアップが完了しました！")
        logger.info("次のステップ: 'uv run python test_gateway.py' を実行して Gateway をテストしてください")
    
    config = load_config()
    return config


def delete_gateway(client, config):
    """既存の Gateway とターゲットを削除するユーティリティ（日本語説明）"""
    # Delete target first
    if 'target_id' in config and 'id' in config:
        client.delete_mcp_gateway_target(config['id'], config['target_id'])
        logger.info("Gateway のターゲットを削除しました")
    
    # Delete Gateway
    if 'id' in config:
        client.delete_mcp_gateway(config['id'])
        logger.info("Gateway を削除しました")


def load_config():
    """設定ファイルを読み込んで辞書で返す（outbound_gateway.json）"""
    config = {}
    with CONFIG_FILE.open('r') as f:
        config = json.load(f)
    return config


def save_config(updates: Optional[dict]=None, delete_key: str=""):
    """設定ファイルを更新して保存するユーティリティ関数"""
    config = load_config()
    
    if updates is not None:
        config.update(updates)
    elif delete_key:
        del config[delete_key]
    
    with CONFIG_FILE.open('w') as f:
        json.dump(config, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description='Create AgentCore Gateway')
    parser.add_argument('--force', action='store_true', help='Force recreation of resources')
    args = parser.parse_args()
    console = Console()
    
    try:
        config = setup_gateway(force=args.force)
    except Exception as e:
        logger.warning("❌ Gateway のセットアップに失敗しました:")
        logger.exception(e)

    console.print_json(json.dumps(config))
    console.print(Panel("uv run python test_gateway.py", title="Gateway でエージェントをテストしましょう！"))


if __name__ == "__main__":
    main()
