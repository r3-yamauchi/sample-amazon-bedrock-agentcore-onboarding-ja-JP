import sys
import os
"""
エントリポイント（同期）モジュール

このモジュールは AgentCore ランタイムから呼び出される同期エントリポイントを提供します。
基本的な処理フロー:
- `payload` から `prompt` を取得
- `AWSCostEstimatorAgent` を初期化して `estimate_costs` を呼び出す

注意（初心者向け）:
- このエントリポイントは短時間で完了するバッチ処理向けです。長時間処理は非同期版を利用してください。
"""

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from cost_estimator_agent.cost_estimator_agent import AWSCostEstimatorAgent
from bedrock_agentcore.runtime import BedrockAgentCoreApp

app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload):
    """同期エントリポイント

    引数:
        payload (dict): ランタイムから渡される辞書。`prompt` キーにユーザー入力を期待します。

    戻り値:
        str: 見積り結果のテキスト
    """
    user_input = payload.get("prompt")
    # エージェントの生成（内部で Code Interpreter 等を初期化します）
    agent = AWSCostEstimatorAgent()

    # 同期でコスト見積りを実行して結果を返す
    return agent.estimate_costs(user_input)


if __name__ == "__main__":
    # ローカル実行時はランタイムを起動する
    app.run()
