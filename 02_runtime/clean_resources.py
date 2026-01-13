import boto3
import yaml
import os


def clean_resources():
    with open(".bedrock_agentcore.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    agent_name = config.get("default_agent")
    agent_id = config.get("agents").get(agent_name).get("bedrock_agentcore").get("agent_id")
    ecr_id = config.get("agents").get(agent_name).get("aws").get("ecr_repository")

    if not agent_id or not ecr_id:
        raise ValueError(".bedrock_agentcore.yaml に agent_id または ecr_id が見つかりません")

    region = boto3.Session().region_name

    agentcore_control_client = boto3.client(
        'bedrock-agentcore-control',
        region_name=region
    )
    ecr_client = boto3.client(
        'ecr',
        region_name=region
    )

    print(f"ランタイムを削除します: {agent_id}")
    runtime_delete_response = agentcore_control_client.delete_agent_runtime(
        agentRuntimeId=agent_id            
    )

    print(f"ECR を削除します: {ecr_id}")
    response = ecr_client.delete_repository(
        repositoryName=ecr_id.split('/')[-1],
        force=True
    )

    print(f"設定ファイルを削除します")
    os.remove(".bedrock_agentcore.yaml")
    os.remove("Dockerfile")


if __name__ == "__main__":
    clean_resources()
