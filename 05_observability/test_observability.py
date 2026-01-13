#!/usr/bin/env python3
"""
AgentCore 観測性テストスクリプト

このスクリプトは AgentCore の観測性機能を実演します:
1. `.bedrock_agentcore.yaml` からエージェント ARN を読み取る
2. 意味のある session ID（user_id + 日時形式）を使用する
3. 同一セッション内で複数の呼び出しをテストする
4. エラーを意図的に発生させてエラー検出をテストする
5. CloudWatch に観測可能なログを記録して監視する

使用方法:
    python test_observability.py
"""

import json
import logging
import boto3
import yaml
from datetime import datetime
from pathlib import Path
from typing import Dict, Any
from botocore.config import Config

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ObservabilityTester:
    """意味のあるセッション追跡で AgentCore の観測性をテストする"""
    
    def __init__(self, agent_arn: str, region: str = ""):
        self.agent_arn = agent_arn
        self.region = region
        if not self.region:
            # 指定がない場合は boto3 セッションのデフォルトリージョンを使用
            self.region = boto3.Session().region_name
        config = Config(
            region_name=self.region,
            read_timeout=600 
        )
        self.client = boto3.client('bedrock-agentcore', config=config)
    
    def generate_session_id(self, user_id: str) -> str:
        """最小長を満たす意味のあるセッション ID を生成する"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        # AgentCore はセッション ID に最低 16 文字を要求するため十分な長さを確保します
        session_id = f"{user_id}_{timestamp}_observability_test"
        logger.info(f"生成したセッション ID: {session_id} (長さ: {len(session_id)})")
        return session_id
    
    def invoke_agent(self, session_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """単一呼び出しを実行し、エラー処理を行う"""
        try:
            response = self.client.invoke_agent_runtime(
                agentRuntimeArn=self.agent_arn,
                runtimeSessionId=session_id,
                payload=json.dumps(payload).encode('utf-8'),
                traceId=session_id[:128]  # Ensure trace ID is within limit
            )
            
            result = self._process_response(response)
            return {
                'status': 'success',
                'result': result
            }
            
        except Exception as e:
            logger.error(f"❌ 呼び出し中にエラーが発生しました: {e}")
            return {
                'status': 'error',
                'error': str(e)
            }
    
    def test_multiple_invocations_same_session(self, user_id: str) -> Dict[str, Any]:
        """同一セッション内で複数回の呼び出しをテストする"""
        session_id = self.generate_session_id(user_id)
        
        # Define multiple test prompts
        test_prompts = [
            "SSH 用に小さな EC2 を準備したいです。費用はどのくらいですか？",
            "中規模の RDS MySQL データベースの費用はどうなりますか？",
            "100GB のストレージを持つ単純な S3 バケットの費用を見積もっていただけますか？"
        ]
        
        logger.info(f"ユーザー {user_id} の複数呼び出しをテストしています")
        logger.info(f"セッション ID: {session_id}")
        logger.info(f"呼び出し回数: {len(test_prompts)}")
        
        results = []
        
        for i, prompt in enumerate(test_prompts, 1):
            logger.info(f"\n--- 呼び出し {i}/{len(test_prompts)} ---")
            logger.info(f"プロンプト: {prompt}")
            
            payload = {"prompt": prompt}
            result = self.invoke_agent(session_id, payload)
            
            result.update({
                'invocation_number': i,
                'prompt': prompt
            })
            results.append(result)
            
            if result['status'] == 'success':
                logger.info(f"✅ 呼び出し {i} は正常に完了しました")
            else:
                logger.error(f"❌ 呼び出し {i} が失敗しました: {result['error']}")
        
        return {
            'session_id': session_id,
            'user_id': user_id,
            'total_invocations': len(test_prompts),
            'results': results
        }

    
    def _process_response(self, response: Dict[str, Any]) -> str:
        """AgentCore ランタイムの応答を処理する"""
        content = []
        
        if "text/event-stream" in response.get("contentType", ""):
            # Handle streaming response
            for line in response["response"].iter_lines(chunk_size=10):
                if line:
                    line = line.decode("utf-8")
                    if line.startswith("data: "):
                        line = line[6:]
                        content.append(line)
        
        elif response.get("contentType") == "application/json":
            # Handle JSON response
            for chunk in response.get("response", []):
                content.append(chunk.decode('utf-8'))
        
        else:
            content = response.get("response", [])
        
        return ''.join(content)


def load_agent_arn() -> str:
    """`.bedrock_agentcore.yaml` からエージェント ARN を読み込む"""
    yaml_path = Path("../02_runtime/.bedrock_agentcore.yaml")
    
    if not yaml_path.exists():
        raise FileNotFoundError(f"設定ファイルが見つかりません: {yaml_path}")
    
    with open(yaml_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    default_agent = config.get('default_agent')
    if not default_agent:
        raise ValueError("設定に default_agent が指定されていません")
    
    agent_config = config.get('agents', {}).get(default_agent, {})
    agent_arn = agent_config.get('bedrock_agentcore', {}).get('agent_arn')
    
    if not agent_arn:
        raise ValueError(f"エージェント {default_agent} の agent_arn が見つかりません")
    
    return agent_arn


def main():
    """観測性テストを実行するメイン関数（日本語説明）"""
    logger.info("🚀 AgentCore 観測性テストを開始します")
    
    try:
        # Load agent ARN from configuration
        agent_arn = load_agent_arn()
        logger.info(f"読み込んだ Agent ARN: {agent_arn}")
        
        # Extract region from ARN
        region = agent_arn.split(':')[3]
        logger.info(f"リージョン: {region}")
        
        tester = ObservabilityTester(agent_arn, region)
        
        # Test 1: Multiple successful invocations in same session
        logger.info("\n" + "="*60)
        logger.info("同一セッション内での呼び出しテストを実行します")
        logger.info("="*60)
        tester.test_multiple_invocations_same_session("user0001")
        
    except Exception as e:
        logger.error(f"❌ テスト実行に失敗しました: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    main()
