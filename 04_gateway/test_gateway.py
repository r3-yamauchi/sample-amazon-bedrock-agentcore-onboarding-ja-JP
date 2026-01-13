"""
Gateway を使って AWS コスト見積りツールを呼び出すテストスクリプト

このスクリプトは次を実演します:
1. Cognito から OAuth トークンを取得する
2. Gateway の MCP エンドポイントを呼び出す
3. aws_cost_estimation ツールを呼び出す
"""

import json
import os
import sys
import logging
import argparse
import asyncio
from pathlib import Path
import boto3
from strands import Agent
from strands import tool
from strands.tools.mcp import MCPClient
from mcp.client.streamable_http import streamablehttp_client
from bedrock_agentcore.identity.auth import requires_access_token

# ログを詳細に出力する設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add the parent directory to the path to import from 01_code_interpreter
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "01_code_interpreter"))
from cost_estimator_agent.cost_estimator_agent import AWSCostEstimatorAgent  # noqa: E402

IDENTITY_CONFIG_FILE = Path("../03_identity/inbound_authorizer.json")
GATEWAY_CONFIG_FILE = Path("outbound_gateway.json")
OAUTH_PROVIDER = ""
OAUTH_SCOPE = ""
GATEWAY_URL = ""
with IDENTITY_CONFIG_FILE.open('r') as f:
    config = json.load(f)
    OAUTH_PROVIDER = config["provider"]["name"]
    OAUTH_SCOPE = config["cognito"]["scope"]

with GATEWAY_CONFIG_FILE.open('r') as f:
    config = json.load(f)
    GATEWAY_URL = config["gateway"]["url"]


@tool(name="cost_estimator_tool", description="アーキテクチャ記述から AWS の費用を見積もるツール")
def cost_estimator_tool(architecture_description: str) -> str:
    region = boto3.Session().region_name
    cost_estimator = AWSCostEstimatorAgent(region=region)
    logger.info(f"次の内容について見積りを行います: {architecture_description}")
    result = cost_estimator.estimate_costs(architecture_description)
    return result

@requires_access_token(
    provider_name= OAUTH_PROVIDER,
    scopes= [OAUTH_SCOPE],
    auth_flow= "M2M",
    force_authentication= False)
async def get_access_token(access_token):
    """アクセストークン取得の補助関数（デバッグ用）"""
    if access_token:
        logger.info("✅ アクセストークンを正常に取得しました！")
    return access_token

def estimate_and_send(architecture_description, address):
    logger.info("MCP クライアント (Strands Agents) で Gateway をテストします...")

    # Get the access token first
    access_token = asyncio.run(get_access_token())
    # Create the transport callable that returns the HTTP client directly
    def create_transport():
        return streamablehttp_client(
            GATEWAY_URL,
            headers={"Authorization": f"Bearer {access_token}"}
        )

    mcp_client = MCPClient(create_transport)
    logger.info("エージェントのツールを準備しています...")
    tools = [cost_estimator_tool]
    with mcp_client:
        more_tools = True
        pagination_token = None
        while more_tools:
            tmp_tools = mcp_client.list_tools_sync(pagination_token=pagination_token)
            tools.extend(tmp_tools)
            if tmp_tools.pagination_token is None:
                more_tools = False
            else:
                more_tools = True 
                pagination_token = tmp_tools.pagination_token

        _names = [tool.tool_name for tool in tools]
        logger.info(f"見つかったツール一覧: {_names}")

        logger.info("\nエージェントに AWS コストの見積りを依頼します...")
        agent = Agent(
            system_prompt=(
                "あなたはプロのソリューションアーキテクトです。AWS プラットフォームのコストを見積もってください。"
                "1. 顧客の要件を 10〜50 語で `architecture_description` に要約してください。"
                "2. `architecture_description` を 'cost_estimator_tool' に渡してください。"
                "3. `markdown_to_email` で見積り結果を送信してください。"
            ),
            tools=tools
        )
        
        # Test by asking the agent to use the aws_cost_estimation tool

        prompt = f"requirements: {architecture_description}, address: {address}"
        result = agent(prompt) 
        logger.info("✅ エージェント呼び出しに成功しました！")
        
        return result


def main():
    """Main test function"""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='AgentCore Gateway のテスト')
    parser.add_argument(
        '--architecture',
        type=str,
        default="アプリケーションロードバランサを持ち、EC2 t3.medium 2 台と us-east-1 に配置された RDS MySQL を持つシンプルなウェブアプリケーション",
        help='コスト見積りのためのアーキテクチャ記述'
    )
    parser.add_argument(
        '--address',
        type=str,
        help='見積り結果を送信するメールアドレス'
    )

    args = parser.parse_args()
    
    try:
        estimate_and_send(args.architecture, args.address)
    except Exception as e:
        logger.error(f"❌ エラーが発生しました: {e}")

if __name__ == "__main__":
    main()
