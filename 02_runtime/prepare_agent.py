#!/usr/bin/env python3
"""
AgentCore Runtime - エージェント登録および管理ツール

このスクリプトはローカルのエージェントソースをデプロイ用ディレクトリにコピーし、
AgentCore 実行のために必要な IAM ロールを作成します。

主な操作フロー（初心者向け）:
1. ソースディレクトリの存在を確認し、`./deployment/<agent_name>` にコピーする
2. 必要な IAM ロール（実行権限）を作成または既存ロールを再利用する
3. `uv run agentcore configure` 向けのコマンド文字列を出力する
"""

import json
import shutil
import logging
from pathlib import Path
import boto3
import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from botocore.exceptions import ClientError

# Configure logging
logging.basicConfig(
    level=logging.ERROR,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
console = Console()

# Constants
DEFAULT_REGION = boto3.Session().region_name
DEPLOYMENTS_DIR = Path('./deployment')


class AgentPreparer:
    """デプロイのためにエージェントを準備するハンドラ

    このクラスは初心者が理解しやすいように各メソッドに分割されています:
    - `prepare`: 全体のオーケストレーション（コピーとロール作成）を行い、設定コマンドを返します
    - `create_source_directory`: 指定したソースをデプロイ用ディレクトリにコピーします
    - `create_agentcore_role`: AgentCore が実行するための IAM ロールとポリシーを作成します
    """
    
    def __init__(self, source_dir: str, region: str = DEFAULT_REGION):
        self.source_dir = Path(source_dir)
        self.region = region
        self.iam_client = boto3.client('iam', region_name=region)
    
    @property
    def agent_name(self) -> str:
        """
        ソースディレクトリからエージェント名を抽出（最後のフォルダ名）

        Returns:
            str: エージェント名
        """
        return self.source_dir.name if self.source_dir.is_dir() else self.source_dir.stem

    def prepare(self) -> str:
        """
        デプロイ用にエージェントを準備（デプロイディレクトリ作成と IAM ロール作成）

        戻り値:
            str: `agentcore configure` 用のコマンド文字列
        """
        # デプロイディレクトリを作成（ソースのコピー）
        # 戻り値は `./deployment` のパスを返します（内部で agent_name を利用）
        deployment_dir = self.create_source_directory()
        
        # Create IAM role
        role_info = self.create_agentcore_role()

        # Build agentcore configure command
        command = "\n".join([
            "",
            f"uv run agentcore configure --entrypoint {deployment_dir}/invoke.py \\",
            f"--name {self.agent_name} \\",
            f"--execution-role {role_info['role_arn']} \\",
            f"--requirements-file {deployment_dir}/requirements.txt \\",
            f"--region {self.region} "
        ])

        return command

    def create_source_directory(self) -> str:
        """
        ソースディレクトリ全体をコピーしてデプロイ用ディレクトリを作成する

        戻り値:
            デプロイディレクトリへのパス
        """
        # 説明:
        # - ここでは簡易的に `*.py` ファイルをコピーしています。依存パッケージや追加ファイルが
        #   必要な場合は、この処理を拡張して `requirements.txt` や静的資産もコピーしてください。
        logger.info(f"{self.source_dir} からデプロイディレクトリを作成します")

        # ソースディレクトリが存在するか検証
        if not self.source_dir.exists():
            raise FileNotFoundError(f"ソースディレクトリが見つかりません: {self.source_dir}")

        # デプロイディレクトリを作成
        target_dir = DEPLOYMENTS_DIR / self.agent_name
        target_dir.mkdir(parents=True, exist_ok=True)

        # ソースディレクトリから Python ファイルをコピー
        logger.info(f"{self.source_dir} から {target_dir} に Python ファイルをコピーします")
        for file_path in self.source_dir.glob("*.py"):
            dest_path = target_dir / file_path.name
            shutil.copy2(file_path, dest_path)
            logger.info(f"コピーしました: {file_path.name}")

        logger.info(f"ソースディレクトリがデプロイ先にコピーされました: {DEPLOYMENTS_DIR}")
        return str(DEPLOYMENTS_DIR)

    def create_agentcore_role(self) -> dict:
        """
        AgentCore 用の IAM ロールを作成する
        (参考: https://github.com/awslabs/amazon-bedrock-agentcore-samples)

        戻り値:
            ロール情報（ARN を含む）
        """
        # ここでは IAM ロール名をユニークにするためにエージェント名を付与します。
        # 実運用では命名規則を組織ルールに合わせてください。
        role_name = f"AgentCoreRole-{self.agent_name}"
        logger.info(f"IAM ロールを作成します: {role_name}")
        
        # Get account ID
        sts_client = boto3.client('sts', region_name=self.region)
        account_id = sts_client.get_caller_identity()['Account']
        
        # 信頼ポリシーを作成
        trust_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {
                        "Service": "bedrock-agentcore.amazonaws.com"
                    },
                    "Action": "sts:AssumeRole",
                    "Condition": {
                        "StringEquals": {
                            "aws:SourceAccount": account_id
                        },
                        "ArnLike": {
                            "aws:SourceArn": f"arn:aws:bedrock-agentcore:{self.region}:{account_id}:*"
                        }
                    }
                }
            ]
        }
        
        # 実行用ポリシーを作成
        execution_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "BedrockPermissions",
                    "Effect": "Allow",
                    "Action": [
                        "bedrock:InvokeModel",
                        "bedrock:InvokeModelWithResponseStream"
                    ],
                    "Resource": "*"
                },
                {
                    "Sid": "ECRImageAccess",
                    "Effect": "Allow",
                    "Action": [
                        "ecr:BatchGetImage",
                        "ecr:GetDownloadUrlForLayer"
                    ],
                    "Resource": [
                        f"arn:aws:ecr:{self.region}:{account_id}:repository/*"
                    ]
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "logs:DescribeLogStreams",
                        "logs:CreateLogGroup"
                    ],
                    "Resource": [
                        f"arn:aws:logs:{self.region}:{account_id}:log-group:/aws/bedrock-agentcore/runtimes/*"
                    ]
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "logs:DescribeLogGroups"
                    ],
                    "Resource": [
                        f"arn:aws:logs:{self.region}:{account_id}:log-group:*"
                    ]
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "logs:CreateLogStream",
                        "logs:PutLogEvents"
                    ],
                    "Resource": [
                        f"arn:aws:logs:{self.region}:{account_id}:log-group:/aws/bedrock-agentcore/runtimes/*:log-stream:*"
                    ]
                },
                {
                    "Sid": "ECRTokenAccess",
                    "Effect": "Allow",
                    "Action": [
                        "ecr:GetAuthorizationToken"
                    ],
                    "Resource": "*"
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "xray:PutTraceSegments",
                        "xray:PutTelemetryRecords",
                        "xray:GetSamplingRules",
                        "xray:GetSamplingTargets"
                        ],
                    "Resource": [ "*" ]
                },
                {
                    "Effect": "Allow",
                    "Resource": "*",
                    "Action": "cloudwatch:PutMetricData",
                    "Condition": {
                        "StringEquals": {
                            "cloudwatch:namespace": "bedrock-agentcore"
                        }
                    }
                },
                {
                    "Sid": "GetAgentAccessToken",
                    "Effect": "Allow",
                    "Action": [
                        "bedrock-agentcore:GetWorkloadAccessToken",
                        "bedrock-agentcore:GetWorkloadAccessTokenForJWT",
                        "bedrock-agentcore:GetWorkloadAccessTokenForUserId"
                    ],
                    "Resource": [
                        f"arn:aws:bedrock-agentcore:{self.region}:{account_id}:workload-identity-directory/default*",
                        f"arn:aws:bedrock-agentcore:{self.region}:{account_id}:workload-identity-directory/default/workload-identity/{self.agent_name}-*"
                    ]
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "bedrock-agentcore:CreateCodeInterpreter",
                        "bedrock-agentcore:StartCodeInterpreterSession",
                        "bedrock-agentcore:InvokeCodeInterpreter",
                        "bedrock-agentcore:StopCodeInterpreterSession",
                        "bedrock-agentcore:DeleteCodeInterpreter",
                        "bedrock-agentcore:ListCodeInterpreters",
                        "bedrock-agentcore:GetCodeInterpreter",
                        "bedrock-agentcore:GetCodeInterpreterSession",
                        "bedrock-agentcore:ListCodeInterpreterSessions"
                    ],
                    "Resource": "arn:aws:bedrock-agentcore:*:*:*"
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "pricing:*"
                    ],
                    "Resource": "*"
                }
            ]
        }
        
        role_exists = False
        response = None

        try:
            response = self.iam_client.get_role(RoleName=role_name)
            logger.info(f"ロールは既に存在します: {role_name}")
            role_exists = True
        except ClientError:
            pass

        if not role_exists:
            try:
                # ロールを作成
                response = self.iam_client.create_role(
                    RoleName=role_name,
                    AssumeRolePolicyDocument=json.dumps(trust_policy),
                    Description=f'AgentCore execution role for {self.agent_name}'
                )
                logger.info(f"IAM ロールを作成しました: {role_name}")
                
            except ClientError as e:
                logger.error(f"IAM ロールの作成に失敗しました: {e}")
                return {}  # 失敗を示す空辞書を返す

            # 新規/既存を問わず実行ポリシーをアタッチする
            try:
                self.iam_client.put_role_policy(
                    RoleName=role_name,
                    PolicyName=f'{role_name}-ExecutionPolicy',
                    PolicyDocument=json.dumps(execution_policy)
                )
                    
                logger.info(f"実行ポリシーをロールにアタッチしました: {role_name}")
                
            except ClientError as e:
                logger.error(f"実行ポリシーのアタッチに失敗しました: {e}")
                return {}  # 失敗を示す空辞書を返す

        return {
            'agent_name': self.agent_name,
            'role_name': role_name,
            'role_arn': response['Role']['Arn']
        }


@click.command()
@click.option('--source-dir', default="../01_code_interpreter/cost_estimator_agent", required=True, help='コピーするソースディレクトリ')
@click.option('--region', default=DEFAULT_REGION, help='AWS リージョン')
def prepare(source_dir: str, region: str):
    """ソースディレクトリをコピーしてエージェントをデプロイ準備する"""
    # CLI の簡単な説明を表示
    console.print(f"[bold blue]準備中: {source_dir}[/bold blue]")
    
    preparer = AgentPreparer(source_dir, region)
    
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            transient=True,
        ) as progress:
            _ = progress.add_task("[cyan]Preparing agent...", total=None)
            configure_command = preparer.prepare()
            progress.stop()
        
        # 成功時の出力（視認性の高い表示）
        console.print("\n[bold green]✓ エージェント準備が正常に完了しました![/bold green]")
        console.print(f"\n[bold]エージェント名:[/bold] {preparer.agent_name}")
        console.print(f"[bold]デプロイディレクトリ:[/bold] {DEPLOYMENTS_DIR}")
        console.print(f"[bold]リージョン:[/bold] {region}")

        # 次のステップを明示
        console.print("\n[bold yellow]📋 次の手順:[/bold yellow]")
        console.print("\n[bold]1. エージェントランタイムの設定:[/bold]")
        console.print(f"   [cyan]{configure_command}[/cyan]")

        console.print("\n[bold]2. エージェントを起動:[/bold]")
        console.print("   [cyan]uv run agentcore launch[/cyan]")

        console.print("\n[bold]3. エージェントをテスト:[/bold]")
        console.print("   [cyan]uv run agentcore invoke '{\"prompt\": \"ローカルの PC から t3.micro に接続したい。費用はいくらですか？\"}'[/cyan]")

        # 補足のヒント
        console.print("\n[dim]💡 補足: 上記コマンドはそのままターミナルに貼り付けて実行できます。[/dim]")
        
    except Exception as e:
        console.print(f"\n[bold red]❌ エラー: {e}[/bold red]")
        raise click.Abort()


if __name__ == '__main__':
    prepare()
