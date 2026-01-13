"""
AgentCore Identity を使ったテスト（cost_estimator_agent_with_identity の呼び出し）

このスクリプトは以下を示します:
1. AgentCore Identity から OAuth トークンを取得する方法
2. 取得したトークンでランタイムを呼び出す方法
"""

import json
import base64
import logging
import argparse
import asyncio
from pathlib import Path
from datetime import datetime, timezone
import requests
from strands import Agent
from strands import tool
from bedrock_agentcore.identity.auth import requires_access_token

# ロギングを詳細モードで設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


CONFIG_FILE = Path("inbound_authorizer.json")
OAUTH_PROVIDER = ""
OAUTH_SCOPE = ""
RUNTIME_URL = ""
BASE64_BLOCK_SIZE = 4 # Base64 encoding processes data in 4-character blocks
with CONFIG_FILE.open('r') as f:
    config = json.load(f)
    OAUTH_PROVIDER = config["provider"]["name"]
    OAUTH_SCOPE = config["cognito"]["scope"]
    RUNTIME_URL = config["runtime"]["url"]


def log_jwt_token_details(access_token: str) -> None:
    """
    デバッグ用に JWT トークンの内容を Base64 デコードしてログ出力する

        引数:
        access_token: JWT のアクセストークン

        注意:
        JWT はヘッダ / ペイロード / シグネチャの 3 部分で構成されます。
        セキュリティ上の理由によりシグネチャ部分はデコードしません。
    """
        # デバッグ用に JWT トークンの各パートを解析してログ出力します
    token_parts = access_token.split(".")
    for i, part in enumerate(token_parts[:2]):  # Only decode header and payload, not signature
        try:
            # Add padding if needed (JWT Base64 encoding may omit trailing '=' characters)
            num_padding_chars = BASE64_BLOCK_SIZE - (len(part) % BASE64_BLOCK_SIZE)
            if num_padding_chars != BASE64_BLOCK_SIZE:
                part_for_decode = part + '=' * num_padding_chars
            else:
                part_for_decode = part

            decoded = base64.b64decode(part_for_decode)
            logger.info(f"\tトークンパート {i}: {json.loads(decoded.decode())}")
        except Exception as e:
            logger.error(f"\t❌ トークンパート {i} のデコードに失敗しました: {e}")


# 認証デコレータ付きの内部関数（アクセストークンを受け取り API を呼び出す）
@requires_access_token(
    provider_name=OAUTH_PROVIDER,
    scopes=[OAUTH_SCOPE],
    auth_flow="M2M",
    force_authentication=False
)
async def _cost_estimator_with_auth(architecture_description: str, access_token: str = None) -> str:
    """認証付きでランタイム API を呼び出す内部関数（日本語説明）

    この関数は AgentCore Identity から渡された `access_token` を使って、
    ランタイムのエンドポイントにリクエストを投げ、応答テキストを返します。
    """
    session_id = f"runtime-with-identity-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"

    if access_token:
        logger.info("✅ AgentCore Identity からアクセストークンを正常に読み込みました")
        # デバッグ目的で JWT の内容を解析してログに出力
        log_jwt_token_details(access_token)

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": session_id,
        "X-Amzn-Trace-Id": session_id,
    }

    response = requests.post(
        RUNTIME_URL,
        headers=headers,
        data=json.dumps({"prompt": architecture_description})
    )

    response.raise_for_status()
    return response.text


# Tool function exposed to LLM (without access_token parameter)
@tool(
    name="cost_estimator_tool",
    description="アーキテクチャ記述から AWS の費用を見積もるツール"
)
async def cost_estimator_tool(architecture_description: str) -> str:
    """
    アーキテクチャの記述を受け取り、コスト見積りを行うツールラッパー

        引数:
        architecture_description: コスト見積りの対象となるアーキテクチャ説明文

        戻り値:
        コスト見積り結果の文字列
    """
    # Call the internal function with authentication
    # We call internal function to conceal access token argument from agent
    return await _cost_estimator_with_auth(architecture_description)


async def main():
    """メインのテスト関数"""
    # コマンドライン引数を解析
    parser = argparse.ArgumentParser(description='AgentCore Identity のテスト')
    parser.add_argument(
        '--architecture',
        type=str,
        default="アプリケーションロードバランサを持ち、EC2 t3.medium インスタンス 2 台と us-east-1 に配置された RDS MySQL を持つシンプルなウェブアプリケーション",
        help='コスト見積り対象のアーキテクチャ説明（デフォルト: ALB + EC2 x2 + RDS MySQL）'
    )
    args = parser.parse_args()

    agent = Agent(
        system_prompt=(
            "あなたはプロのソリューションアーキテクトです。"
            " 顧客からアーキテクチャの記述や要件を受け取り、"
            " 'cost_estimator_tool' を使って見積りを提供してください。"
        ),
        tools=[cost_estimator_tool]
    )

    logger.info("Identity を用いてランタイムを呼び出すエージェントを実行します...")
    await agent.invoke_async(args.architecture)
    logger.info("✅ エージェントの呼び出しに成功しました")


if __name__ == "__main__":
    asyncio.run(main())
