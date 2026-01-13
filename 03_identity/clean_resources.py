import json
import os
from pathlib import Path
import boto3


def clean_resources():
    """Identity セットアップで作成したすべてのリソースを削除する"""
    config_file = Path("inbound_authorizer.json")

    with config_file.open("r", encoding="utf-8") as f:
        config = json.load(f)

    region = boto3.Session().region_name
    
    # AgentCore の OAuth2 クレデンシャルプロバイダを削除
    client = boto3.client("bedrock-agentcore-control", region_name=region)
    provider_name = config["provider"]["name"]
    print(f"OAuth2 クレデンシャルプロバイダを削除します: {provider_name}")
    client.delete_oauth2_credential_provider(name=provider_name)
    print(f"OAuth2 クレデンシャルプロバイダ {provider_name} を削除しました")

    # Cognito リソースを削除
    cognito_client = boto3.client("cognito-idp", region_name=region)
    user_pool_id = config["cognito"]["user_pool_id"]
    client_id = config["cognito"]["client_id"]

    # ユーザープールクライアントを削除
    print(f"ユーザープールクライアントを削除します: {client_id}")
    cognito_client.delete_user_pool_client(
        UserPoolId=user_pool_id,
        ClientId=client_id
    )
    print(f"ユーザープールクライアント {client_id} を削除しました")

    user_pool_details = cognito_client.describe_user_pool(UserPoolId=user_pool_id)
    domain = user_pool_details.get("UserPool", {}).get("Domain")
    
    if domain:
        print(f"ユーザープールのドメインを削除します: {domain}")
        cognito_client.delete_user_pool_domain(Domain=domain, UserPoolId=user_pool_id)
        print(f"ドメイン {domain} を削除しました")
    else:
        print("ユーザープールにドメインは登録されていません")

    # 削除保護を無効にしてユーザープールを削除
    print(f"ユーザープールの削除保護を無効化します: {user_pool_id}")
    cognito_client.update_user_pool(
        UserPoolId=user_pool_id,
        DeletionProtection="INACTIVE"
    )

    print(f"ユーザープールを削除します: {user_pool_id}")
    cognito_client.delete_user_pool(UserPoolId=user_pool_id)
    print(f"ユーザープール {user_pool_id} を削除しました")

    runtime_id = config["runtime"]["id"]
    runtime_delete_response = client.delete_agent_runtime(
        agentRuntimeId=runtime_id
    )

    os.remove(".agentcore.yaml")
    os.remove("inbound_authorizer.json")


if __name__ == "__main__":
    clean_resources()
