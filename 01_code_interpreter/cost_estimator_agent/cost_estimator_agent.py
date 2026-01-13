"""
Amazon Bedrock AgentCore Code Interpreter を使用した AWS コスト見積りエージェント

このエージェントは以下を示します:
1. AWS Pricing MCP サーバーを使用して価格データを取得する方法
2. AgentCore Code Interpreter を用いた安全な計算方法
3. AWS アーキテクチャに対する包括的なコスト見積りの提供

主な特徴:
- AgentCore サンドボックスでの安全なコード実行
- リアルタイムの AWS 価格データ取得
- 十分なログ記録とエラー処理
- 段階的な複雑度の拡張
"""

import logging
import traceback
import boto3
from contextlib import contextmanager
from typing import Generator, AsyncGenerator
from strands import Agent, tool
from strands.models import BedrockModel
from strands.tools.mcp import MCPClient
from strands.handlers.callback_handler import null_callback_handler
from botocore.config import Config
from mcp import stdio_client, StdioServerParameters
from bedrock_agentcore.tools.code_interpreter_client import CodeInterpreter
from cost_estimator_agent.config import (
    SYSTEM_PROMPT,
    COST_ESTIMATION_PROMPT,
    DEFAULT_MODEL,
    LOG_FORMAT
)

# ロギングの基本設定
logging.basicConfig(
    level=logging.ERROR,
    format=LOG_FORMAT,
    handlers=[logging.StreamHandler()]
)

logging.getLogger("strands").setLevel(logging.ERROR)

logger = logging.getLogger(__name__)


class AWSCostEstimatorAgent:
    """
    AWS コスト見積りエージェント（AgentCore Code Interpreter 利用）

    このエージェントは以下を組み合わせます:
    - MCP 価格ツール（リアルタイムの価格データ）
    - AgentCore Code Interpreter（セキュアな計算）
    - Strands Agents フレームワークによる実装の簡潔化
    """

    def __init__(self, region: str = ""):
        """エージェントを初期化する

        引数:
            region: AgentCore Code Interpreter に使用する AWS リージョン
        """
        # 初期化の説明:
        # - `region` が指定されなければ、boto3 のデフォルトリージョンを使用します。
        # - `code_interpreter` は AgentCore の Code Interpreter セッションを管理するオブジェクトで、
        #   実際のコード実行を行うために後で初期化されます。
        self.region = region
        if not self.region:
            self.region = boto3.Session().region_name
        self.code_interpreter = None

        logger.info(f"初期化: AWS Cost Estimator Agent (region={region})")

    def _setup_code_interpreter(self) -> None:
        """AgentCore Code Interpreter をセットアップする"""
        # 解説:
        # - `CodeInterpreter` は AgentCore 上で安全にコードを実行するためのラッパーです。
        # - `start()` を呼ぶことで内部プロセスや必要な接続が確立されます。
        # - 失敗した場合はログにエラーを残して処理を中断します（呼び出し元での例外処理に委ねます）。
        try:
            logger.info("AgentCore Code Interpreter をセットアップしています...")
            self.code_interpreter = CodeInterpreter(self.region)
            self.code_interpreter.start()
            logger.info("✅ AgentCore Code Interpreter のセッションが正常に開始されました")
        except Exception as e:
            logger.error(f"❌ Code Interpreter のセットアップに失敗しました: {e}")
            return

    def _get_aws_credentials(self) -> dict:
        """現在の AWS 認証情報を取得する（セッショントークンを含む）"""
        # 解説:
        # - boto3.Session を使って現在の認証情報を取得します。
        # - 一時的なセッショントークンが付与されている場合は `AWS_SESSION_TOKEN` も返します。
        # - この情報は外部プロセス（MCP サーバーなど）に環境変数として渡されます。
        try:
            logger.info("現在の AWS 認証情報を取得しています...")

            session = boto3.Session()
            credentials = session.get_credentials()

            if credentials is None:
                raise Exception("AWS 認証情報が見つかりません")

            sts_client = boto3.client('sts', region_name=self.region)
            identity = sts_client.get_caller_identity()
            logger.info(f"使用中の AWS アイデンティティ: {identity.get('Arn', 'Unknown')}")

            frozen_creds = credentials.get_frozen_credentials()

            credential_dict = {
                "AWS_ACCESS_KEY_ID": frozen_creds.access_key,
                "AWS_SECRET_ACCESS_KEY": frozen_creds.secret_key,
                "AWS_REGION": self.region
            }

            if frozen_creds.token:
                credential_dict["AWS_SESSION_TOKEN"] = frozen_creds.token
                logger.info("✅ セッショントークン付きの AWS 認証情報を使用しています（おそらく EC2 インスタンスロール）")
            else:
                logger.info("✅ セッショントークンなしの AWS 認証情報を使用しています")

            return credential_dict

        except Exception as e:
            logger.error(f"❌ AWS 認証情報の取得に失敗しました: {e}")
            return {}

    def _setup_aws_pricing_client(self) -> MCPClient:
        """現在の AWS 認証情報で AWS Pricing MCP クライアントをセットアップする"""
        # 解説:
        # - MCPClient は外部プロセス（uvx で実行される MCP サーバー）とやり取りするためのクライアントです。
        # - `env_vars` に認証情報を渡すことで、MCP サーバー側から AWS API にアクセスできます。
        # - エラー時は None を返し、呼び出し側で適切にハンドリングする必要があります。
        try:
            logger.info("AWS Pricing MCP クライアントをセットアップしています...")

            aws_credentials = self._get_aws_credentials()

            env_vars = {
                "FASTMCP_LOG_LEVEL": "ERROR",
                **aws_credentials
            }

            aws_pricing_client = MCPClient(
                lambda: stdio_client(StdioServerParameters(
                    command="uvx",
                    args=["awslabs.aws-pricing-mcp-server@latest"],
                    env=env_vars
                ))
            )
            logger.info("✅ AWS 認証情報で AWS Pricing MCP クライアントが正常にセットアップされました")
            return aws_pricing_client
        except Exception as e:
            logger.error(f"❌ AWS Pricing MCP クライアントのセットアップに失敗しました: {e}")
            return None

    @tool
    def execute_cost_calculation(self, calculation_code: str, description: str = "") -> str:
        """AgentCore Code Interpreter を用いてコスト計算を実行する"""
        # 解説:
        # - `calculation_code` は実行する Python コードの文字列です。通常は数値計算や集計処理が含まれます。
        # - `invoke("executeCode", ...)` は Code Interpreter にコードを渡して実行させます。
        # - 返却される `response` はストリーム形式でイベントを含むため、テキスト結果を順次収集します。
        # - ここで注意すべき点:
        #   * 実行されるコードはサンドボックス内で動作しますが、外部リソースアクセスの挙動は環境依存です。
        #   * 長時間実行や例外発生に備え、呼び出し元でタイムアウトや再試行を設計してください。
        if not self.code_interpreter:
            return "❌ Code Interpreter が初期化されていません"

        try:
            logger.info(f"🧮 計算を実行しています: {description}")
            logger.debug(f"実行するコード:\n{calculation_code}")

            response = self.code_interpreter.invoke("executeCode", {
                "language": "python",
                "code": calculation_code
            })

            results = []
            for event in response.get("stream", []):
                if "result" in event:
                    result = event["result"]
                    if "content" in result:
                        for content_item in result["content"]:
                            if content_item.get("type") == "text":
                                results.append(content_item["text"])

            result_text = "\n".join(results)
            logger.info("✅ 計算が正常に完了しました")
            logger.debug(f"計算結果: {result_text}")

            return result_text

        except Exception as e:
            logger.exception(f"❌ 計算が失敗しました: {e}")

    @contextmanager
    def _estimation_agent(self) -> Generator[Agent, None, None]:
        """コスト見積りコンポーネント用のコンテキストマネージャ"""
        # 解説:
        # - このコンテキストマネージャは、Code Interpreter と MCP クライアントを初期化し、
        #   それらをまとめて `Agent` に渡します。
        # - `pricing_tools` は MCP サーバーが提供するツール群（価格取得用）で、
        #   エージェントに組み込むことでモデルから価格情報を取得可能になります。
        # - `yield agent` により、呼び出し元は `with` ブロック内で `agent(prompt)` などを実行できます。
        try:
            logger.info("🚀 AWS コスト見積りエージェントを初期化しています...")

            self._setup_code_interpreter()
            aws_pricing_client = self._setup_aws_pricing_client()

            with aws_pricing_client:
                pricing_tools = aws_pricing_client.list_tools_sync()
                logger.info(f"見つかった AWS 価格ツール数: {len(pricing_tools)}")

                all_tools = [self.execute_cost_calculation] + pricing_tools
                agent = Agent(
                    BedrockModel(
                        boto_client_config=Config(
                            read_timeout=900,
                            connect_timeout=900,
                            retries=dict(max_attempts=3, mode="adaptive"),
                        ),
                        model_id=DEFAULT_MODEL
                    ),
                    tools=all_tools,
                    system_prompt=SYSTEM_PROMPT
                )

                yield agent

        except Exception as e:
            logger.exception(f"❌ コンポーネントのセットアップに失敗しました: {e}")
            raise
        finally:
            self.cleanup()

    def estimate_costs(self, architecture_description: str) -> str:
        """指定されたアーキテクチャ記述についてコストを見積もる"""
        # 解説:
        # - `architecture_description` をプロンプトに埋め込み、モデルに見積りタスクを依頼します。
        # - `agent(prompt)` の戻り値はモデルの応答オブジェクトで、メッセージの `content` に結果が含まれます。
        # - エラー発生時はスタックトレースを含む文字列を返すため、呼び出し側でログや UI に表示できます。
        logger.info("📊 コスト見積りを開始します...")
        logger.info(f"アーキテクチャ: {architecture_description}")

        try:
            with self._estimation_agent() as agent:
                prompt = COST_ESTIMATION_PROMPT.format(
                    architecture_description=architecture_description
                )
                result = agent(prompt)

                logger.info("✅ コスト見積りが完了しました")

                if result.message and result.message.get("content"):
                    text_parts = []
                    for content_block in result.message["content"]:
                        if isinstance(content_block, dict) and "text" in content_block:
                            text_parts.append(content_block["text"])
                    return "".join(text_parts) if text_parts else "テキストコンテンツが見つかりません。"
                else:
                    return "見積り結果がありません。"

        except Exception as e:
            logger.exception(f"❌ コスト見積りに失敗しました: {e}")
            error_details = traceback.format_exc()
            return f"❌ コスト見積りに失敗しました: {e}\n\nスタックトレース:\n{error_details}"

    async def estimate_costs_stream(self, architecture_description: str) -> AsyncGenerator[dict, None]:
        """ストリーミングレスポンスで指定されたアーキテクチャのコストを見積もる"""
        # 解説:
        # - ストリーミング版は部分的な出力を逐次返すため、UI 側で段階的に表示できます。
        # - `previous_output` を使って前回送信済みの内容を保持し、差分だけを返すようにしています。
        # - 非同期ジェネレータなので、呼び出し側は `async for` で受け取ります。
        logger.info("📊 ストリーミングコスト見積りを開始します...")
        logger.info(f"アーキテクチャ: {architecture_description}")

        try:
            with self._estimation_agent() as agent:
                prompt = COST_ESTIMATION_PROMPT.format(
                    architecture_description=architecture_description
                )

                logger.info("🔄 ストリーミングコスト見積りの応答を処理しています...")

                previous_output = ""

                agent_stream = agent.stream_async(prompt, callback_handler=null_callback_handler)

                async for event in agent_stream:
                    if "data" in event:
                        current_chunk = str(event["data"])

                        if current_chunk.startswith(previous_output):
                            delta_content = current_chunk[len(previous_output):]
                            if delta_content:
                                previous_output = current_chunk
                                yield {"data": delta_content}
                        else:
                            previous_output = current_chunk
                            yield {"data": current_chunk}
                    else:
                        yield event

                logger.info("✅ ストリーミングコスト見積りが完了しました")

        except Exception as e:
            logger.exception(f"❌ ストリーミングコスト見積りが失敗しました: {e}")
            yield {
                "error": True,
                "data": f"❌ ストリーミングコスト見積りが失敗しました: {e}\n\nスタックトレース:\n{traceback.format_exc()}"
            }

    def cleanup(self) -> None:
        """リソースをクリーンアップする"""
        # 解説:
        # - 長時間実行後や例外発生後にこのメソッドを呼ぶことで、外部セッションやプロセスを確実に解放します。
        # - 実運用では追加のクリーンアップ（MCP クライアントの終了等）をここに実装すると良いでしょう。
        logger.info("🧹 リソースのクリーンアップを行います...")

        if self.code_interpreter:
            try:
                self.code_interpreter.stop()
                logger.info("✅ Code Interpreter セッションを停止しました")
            except Exception as e:
                logger.warning(f"⚠️ Code Interpreter の停止中にエラーが発生しました: {e}")
            finally:
                self.code_interpreter = None
