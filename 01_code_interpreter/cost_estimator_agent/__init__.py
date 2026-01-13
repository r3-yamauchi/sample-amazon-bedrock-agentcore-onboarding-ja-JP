
"""
`cost_estimator_agent` パッケージ

このパッケージは AWS コスト見積りエージェントの主要コンポーネントをまとめます。

目的:
- モジュールの公開 API を明示するためのパッケージ初期化ファイルです。
- 開発者向けに、このパッケージが何を提供するかを説明します。

注意（初心者向け）:
- Python のパッケージで `__init__.py` はそのフォルダをパッケージとして扱うためのファイルです。
- 小さなプロジェクトでは空でも問題ありませんが、ドキュメントやエクスポートをここに追加すると
	他のモジュールでの import が分かりやすくなります。

例:
from .cost_estimator_agent import AWSCostEstimatorAgent

"""

from .cost_estimator_agent import AWSCostEstimatorAgent

# パッケージ利用者向けの簡単なエクスポートを定義しています。
# これにより `from cost_estimator_agent import AWSCostEstimatorAgent` のように
# シンプルに利用できます。

