import sys
import os
"""
エントリポイント（非同期ストリーミング）モジュール

このモジュールはストリーミングレスポンスを返す非同期エントリポイントです。
長時間実行や段階的なレスポンスが期待される処理で利用します。
"""

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from cost_estimator_agent.cost_estimator_agent import AWSCostEstimatorAgent
from bedrock_agentcore.runtime import BedrockAgentCoreApp

app = BedrockAgentCoreApp()


@app.entrypoint
async def invoke(payload):
    """非同期エントリポイント（ストリーミング）

    引数:
        payload (dict): ランタイムから渡される辞書。`prompt` キーにユーザー入力を期待します。

    生成する値:
        dict: ストリーミングイベント（`data` や `error` を含む）
    """
    user_input = payload.get("prompt")
    agent = AWSCostEstimatorAgent()
    # 非同期ストリームを取得し、受信したイベントをそのまま返す
    stream = agent.estimate_costs_stream(user_input)
    async for event in stream:
        yield (event)


if __name__ == "__main__":
    app.run()
