"""
AgentCore Memory を組み込んだ AWS コスト見積りエージェント

この実装は、短期および長期メモリ機能を追加した AWS コスト見積りエージェントにより
AgentCore Memory の機能を示します。

主な特徴:
1. 短期メモリ: セッション内で複数の見積りを保存し比較可能にする
2. 長期メモリ: 時間経過でユーザーの意思決定パターンや好みを学習する
3. 比較機能: 複数の見積りを横並びで比較できる
4. 意思決定インサイト: 過去のパターンに基づくパーソナライズされた推奨を提供する

`AgentWithMemory` クラスは、既存のコスト見積りエージェントにメモリ機能を統合し、
メモリ利用の実践的な例を提供します。
"""

import sys
import os
import logging
import traceback
import argparse
import json
import boto3
from datetime import datetime

# Configure logging for debugging and monitoring
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Add the parent directory to the path to import from 01_code_interpreter
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "01_code_interpreter"))

from strands import Agent, tool  # noqa: E402
from bedrock_agentcore.memory.client import MemoryClient  # noqa: E402
from cost_estimator_agent.cost_estimator_agent import AWSCostEstimatorAgent  # noqa: E402

# Prompt Templates
SYSTEM_PROMPT = """あなたはメモリ機能を備えた AWS コスト見積りエージェントです。

以下の支援が可能です:
1. estimate: AWS アーキテクチャのコストを算出する
2. compare: 複数のコスト見積りを横並びで比較する
3. propose: ユーザーの好みと履歴に基づき最適なアーキテクチャを推奨する

常に詳細な説明を提供し、推奨時にはユーザーの履歴的な好みを考慮してください。"""

COMPARISON_PROMPT_TEMPLATE = """以下の AWS コスト見積りを比較し、インサイトを提供してください:

ユーザーのリクエスト: {request}

見積り:
{estimates}

出力内容:
1. 各見積りの要約
2. アーキテクチャ間の主要な違い
3. コスト比較の考察
4. 比較に基づく推奨事項
"""

PROPOSAL_PROMPT_TEMPLATE = """以下に基づき AWS アーキテクチャの提案を生成してください:

ユーザー要件: {requirements}

過去の好み・パターン:
{historical_data}

出力内容:
1. 推奨アーキテクチャの概要
2. 主要コンポーネントとサービス
3. 推定コスト（概算）
4. スケーラビリティに関する考慮点
5. セキュリティのベストプラクティス
6. コスト最適化の推奨

利用可能な過去の好みに基づいて提案をパーソナライズしてください。
"""


class AgentWithMemory:
    """
    AgentCore Memory 機能を統合した AWS コスト見積りエージェント

    説明（初心者向け）:
    - 短期メモリ: セッション内で実行した見積りを保存し、その場で比較できるようにします。
    - 長期メモリ: 時間をかけてユーザーの好みや判断パターンを学習し、将来の提案に活用します。
    - このクラスは上記の違いを実演し、見積り・比較・提案のワークフローを提供します。
    """
    
    def __init__(self, actor_id: str, region: str = "", force_recreate: bool = False):
        """
        メモリ機能付きエージェントを初期化します

        引数:
            actor_id: ユーザー / アクターを一意に識別する文字列（メモリのネームスペースに使用）
            region: AgentCore サービスを利用する AWS リージョン
            force_recreate: True の場合、既存のメモリを削除して新規作成します
        """
        self.actor_id = actor_id
        self.region = region
        if not self.region:
            # Use default region from boto3 session if not specified
            self.region = boto3.Session().region_name
        self.force_recreate = force_recreate
        self.memory_id = None
        self.memory = None
        self.memory_client = None
        self.agent = None
        self.bedrock_runtime = None
        self.session_id = f"session-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        
        logger.info(f"AgentWithMemory を初期化します (actor: {actor_id})")
        if force_recreate:
            logger.info("🔄 強制再作成モードが有効です - 既存メモリを削除します")
        
        # Initialize AgentCore Memory with user preference strategy
        try:
            logger.info("AgentCore Memory を初期化しています...")
            self.memory_client = MemoryClient(region_name=self.region)
            
            # Check if memory already exists
            memory_name = "cost_estimator_memory"
            existing_memories = self.memory_client.list_memories()
            existing_memory = None
            for memory in existing_memories:
                if memory.get('memoryId').startswith(memory_name):
                    existing_memory = memory
                    break

            if existing_memory:
                if not force_recreate:
                    # 既存メモリを再利用（デフォルト）
                    self.memory_id = existing_memory.get('id')
                    self.memory = existing_memory
                    logger.info(f"🔄 既存メモリを再利用: {memory_name} (ID: {self.memory_id})")
                    logger.info("✅ メモリの再利用に成功しました - 作成処理をスキップします")
                else:
                    # force_recreate が True の場合は既存メモリを削除
                    memory_id_to_delete = existing_memory.get('id')
                    logger.info(f"🗑️ 既存メモリを強制削除します: {memory_name} (ID: {memory_id_to_delete})")
                    self.memory_client.delete_memory_and_wait(memory_id_to_delete, max_wait=300)
                    logger.info("✅ 既存メモリを正常に削除しました")
                    existing_memory = None

            if existing_memory is None:
                # 新しいメモリを作成
                logger.info("新しい AgentCore Memory を作成しています...")
                self.memory = self.memory_client.create_memory_and_wait(
                    name=memory_name,
                    strategies=[{
                        "userPreferenceMemoryStrategy": {
                            "name": "UserPreferenceExtractor",
                            "description": "Extracts user preferences for AWS architecture decisions",
                            "namespaces": [f"/preferences/{self.actor_id}"]
                        }
                    }],
                    event_expiry_days=7,  # Minimum allowed value
                )
                self.memory_id = self.memory.get('memoryId')
                logger.info(f"✅ AgentCore Memory を作成しました (ID: {self.memory_id})")

            # Bedrock Runtime クライアントを初期化して AI 生成機能を利用可能にします
            self.bedrock_runtime = boto3.client('bedrock-runtime', region_name=self.region)
            logger.info("✅ Bedrock Runtime クライアントを初期化しました")
            
            # Create the agent with cost estimation tools and callback handler
            self.agent = Agent(
                tools=[self.estimate, self.compare, self.propose],
                system_prompt=SYSTEM_PROMPT
            )
            
        except Exception as e:
            logger.exception(f"❌ AgentWithMemory の初期化に失敗しました: {e}")

    def __enter__(self):
        """コンテキストマネージャのエントリ"""
        return self.agent

    def __exit__(self, exc_type, exc_val, exc_tb):
        """コンテキストマネージャの終了 - デフォルトでメモリを保持（デバッグ用）"""
        # デバッグを高速化するため、デフォルトではメモリを保持します
        # 必要に応じて --force を使ってメモリを再作成してください
        try:
            if self.memory_client and self.memory_id:
                logger.info("🧹 メモリは再利用のため保持されました（再作成するには --force を使用）")
                logger.info("✅ コンテキストマネージャの終了処理が完了しました")
        except Exception as e:
            logger.warning(f"⚠️ コンテキストマネージャ終了時にエラーが発生しました: {e}")

    def list_memory_events(self, max_results: int = 10):
        """デバッグ用にメモリイベントを確認する補助メソッド"""
        try:
            if not self.memory_client or not self.memory_id:
                return "❌ メモリが利用できません"
            
            events = self.memory_client.list_events(
                memory_id=self.memory_id,
                actor_id=self.actor_id,
                session_id=self.session_id,
                max_results=max_results
            )
            
            logger.info(f"📋 メモリ内で {len(events)} 件のイベントを検出しました")
            for i, event in enumerate(events):
                logger.info(f"Event {i+1}: {json.dumps(event, indent=2, default=str)}")
            
            return events
        except Exception as e:
            logger.error(f"❌ イベント一覧の取得に失敗しました: {e}")
            return []

    @tool
    def estimate(self, architecture_description: str) -> str:
        """AWS アーキテクチャのコストを見積もる"""
        try:
            logger.info(f"🔍 以下のコストを見積もります: {architecture_description}")
            
            # 既存のコスト見積りエージェントを使用
            cost_estimator = AWSCostEstimatorAgent(region=self.region)
            result = cost_estimator.estimate_costs(architecture_description)
            # イベントを短期メモリに保存
            logger.info("短期メモリにイベントを保存します")
            self.memory_client.create_event(
                memory_id=self.memory_id,
                actor_id=self.actor_id,
                session_id=self.session_id,
                messages=[
                    (architecture_description, "USER"),
                    (result, "ASSISTANT")
                ]
            )

            # メモリフックがこの対話を自動的に保存します
            logger.info("✅ コスト見積りが完了しました")
            return result
            
        except Exception as e:
            logger.exception(f"❌ コスト見積りに失敗しました: {e}")
            return f"❌ コスト見積りに失敗しました: {e}"

    @tool
    def compare(self, request: str = "Compare my recent estimates") -> str:
        """メモリ内の複数のコスト見積りを比較する"""
        logger.info("📊 比較のために見積りを取得しています...")
        
        if not self.memory_client or not self.memory_id:
            return "❌ 比較のためのメモリが利用できません"
        
        # メモリから最近の見積りイベントを取得
        events = self.memory_client.list_events(
            memory_id=self.memory_id,
            actor_id=self.actor_id,
            session_id=self.session_id,
            max_results=4
        )
        
        # Filter and parse estimate tool calls
        estimates = []
        for event in events:
            try:
                # Extract payload data
                _input = ""
                _output = ""
                for payload in event.get('payload', []):
                    if 'conversational' in payload:
                        _message = payload['conversational']
                        _role = _message.get('role', 'unknown')
                        _content = _message.get('content')["text"]

                        if _role == 'USER':
                            _input = _content
                        elif _role == 'ASSISTANT':
                            _output = _content
                    
                    if _input and _output:
                        estimates.append(
                            "\n".join([
                                "## Estimate",
                                f"**Input:**:\n{_input}",
                                f"**Output:**:\n{_output}"
                            ])
                        )
                        _input = ""
                        _output = ""

            except Exception as parse_error:
                logger.warning(f"イベントの解析に失敗しました: {parse_error}")
                continue
        
        if not estimates:
            raise Exception("ℹ️ 比較対象となる過去の見積りが見つかりません。まずいくつかの見積りを実行してください。") 
        
        # Bedrock を使って比較を生成
        logger.info(f"🔍 {len(estimates)} 件の見積りを比較します... {estimates}")
        comparison_prompt = COMPARISON_PROMPT_TEMPLATE.format(
            request=request,
            estimates="\n\n".join(estimates)
        )
        
        comparison_result = self._generate_with_bedrock(comparison_prompt)

        logger.info(f"✅ {len(estimates)} 件の見積りの比較が完了しました")
        return comparison_result

    @tool
    def propose(self, requirements: str) -> str:
        """ユーザーの好みと履歴に基づいて最適なアーキテクチャを提案する"""
        try:
            logger.info("💡 ユーザー履歴に基づいてアーキテクチャ提案を生成しています...")
            
            if not self.memory_client or not self.memory_id:
                return "❌ パーソナライズされた推奨に利用できるメモリがありません"
            
            # 長期メモリからユーザーの好みやパターンを取得
            memories = self.memory_client.retrieve_memories(
                memory_id=self.memory_id,
                namespace=f"/preferences/{self.actor_id}",
                query=f"User preferences and decision patterns for: {requirements}",
                top_k=3
            )
            contents = [memory.get('content', {}).get('text', '') for memory in memories]

            # Bedrock を用いて提案を生成
            logger.info(f"🔍 要件で提案を生成しています: {requirements}\n過去データ: {contents}")
            proposal_prompt = PROPOSAL_PROMPT_TEMPLATE.format(
                requirements=requirements,
                historical_data="\n".join(contents) if memories else "No historical data available"
            )
            
            proposal = self._generate_with_bedrock(proposal_prompt)

            logger.info("✅ アーキテクチャ提案を生成しました")
            return proposal
            
        except Exception as e:
            logger.exception(f"❌ 提案生成に失敗しました: {e}")
            return f"❌ 提案生成に失敗しました: {e}"

    def _generate_with_bedrock(self, prompt: str) -> str:
        """Amazon Bedrock Converse API を用いてプロンプトからテキストを生成するヘルパー"""
        try:
            # 高速かつコスト効率の良い生成を意図して Claude Sonnet 4 を指定しています
            model_id = "us.anthropic.claude-sonnet-4-20250514-v1:0"
            
            # Prepare the message
            messages = [
                {
                    "role": "user",
                    "content": [{"text": prompt}]
                }
            ]
            
            # Converse API を用いてモデルを呼び出す
            response = self.bedrock_runtime.converse(
                modelId=model_id,
                messages=messages,
                inferenceConfig={
                    "maxTokens": 4000,
                    "temperature": 0.9
                }
            )
            
            # レスポンステキストを抽出
            output_message = response['output']['message']
            generated_text = output_message['content'][0]['text']

            return generated_text

        except Exception as e:
            logger.error(f"Bedrock による生成が失敗しました: {e}")
            # Bedrock が失敗した場合のフォールバック
            return f"⚠️ AI 生成が失敗しました。エラー: {str(e)}"


def main():
    parser = argparse.ArgumentParser(
        description="AgentCore Memory を利用した AWS コスト見積りエージェント",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
例:
  python test_memory.py              # 既存メモリを再利用（デバッグに高速）
  python test_memory.py --force      # メモリを強制再作成（クリーンな開始）
        """
    )
    parser.add_argument(
        '--force', 
        action='store_true',
        help='既存メモリを削除して再作成します（遅いがクリーンな開始）'
    )
    
    args = parser.parse_args()
    
    print("🚀 AgentCore Memory を利用した AWS コスト見積りエージェント")
    print("=" * 60)
    
    if args.force:
        print("🔄 強制モード: 既存メモリを削除して再作成します")
    else:
        print("⚡ 高速モード: 既存メモリを再利用します")
    
    try:
        # Use context manager to ensure proper cleanup
        with AgentWithMemory(actor_id="user123", force_recreate=args.force) as agent:
            print("\n📝 異なるアーキテクチャのコスト見積りを実行します...")
            
            # Estimate costs for three different architectures
            architectures = [
                "Single EC2 t3.micro instance with RDS MySQL for a small blog",
                "Load balanced EC2 t3.small instances with RDS MySQL for medium traffic web app"
            ]
            
            print("\n🔍 見積りを生成しています...")
            for i, architecture in enumerate(architectures, 1):
                print(f"\n--- 見積り #{i} ---")
                result = agent(f"以下のアーキテクチャを見積もってください: {architecture}")
                print(result)
                result_text = result.message["content"] if result.message else "見積り結果がありません。"
                print(f"アーキテクチャ: {architecture}")
                print(f"結果: {result_text[:200]}..." if len(result_text) > 200 else result_text)

            print("\n" + "="*60)
            print("📊 すべての見積りを比較します...")
            comparison = agent("先ほど生成した見積りを比較してください")
            print(comparison)

            print("\n" + "="*60)
            print("💡 パーソナライズされた推奨を取得しています...")
            proposal = agent("私の好みに合った最適なアーキテクチャを提案してください")
            print(proposal)
            
    except Exception as e:
        logger.exception(f"❌ デモが失敗しました: {e}")
        print(f"\n❌ デモが失敗しました: {e}")
        print(f"スタックトレース:\n{traceback.format_exc()}")


if __name__ == "__main__":
    main()
