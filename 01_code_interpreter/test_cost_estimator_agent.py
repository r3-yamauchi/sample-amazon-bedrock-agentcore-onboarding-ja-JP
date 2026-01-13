#!/usr/bin/env python3
"""AWS コスト見積りエージェントの簡易テスト

このスクリプトは開発者向けの簡単なテストランナーです。
- `estimate_costs`（同期）と `estimate_costs_stream`（非同期ストリーミング）の基本動作を確認します。

使い方例:
  python3 01_code_interpreter/test_cost_estimator_agent.py --tests regular streaming --architecture "EC2 t3.micro 1台" --verbose

注意: ネットワークや AWS 認証が必要です。事前に環境を設定してください。
"""

import asyncio
import argparse
from cost_estimator_agent.cost_estimator_agent import AWSCostEstimatorAgent


async def test_streaming(architecture: str, verbose: bool = True) -> bool:
    """非同期ストリーミング API (`estimate_costs_stream`) をテストします

    戻り値: 成功時は True、失敗やエラー時は False を返します。
    """
    if verbose:
        print('\n🔄 ストリーミングコスト見積りをテストしています...')
    agent = AWSCostEstimatorAgent()
    try:
        total_chunks = 0
        total_length = 0
        async for event in agent.estimate_costs_stream(architecture):
            if 'data' in event:
                chunk = str(event['data'])
                if verbose:
                    print(chunk, end='', flush=True)
                total_chunks += 1
                total_length += len(chunk)
            elif 'error' in event:
                if verbose:
                    print(f"\n❌ ストリーミングエラー: {event.get('error')}")
                return False
        if verbose:
            print(f"\n📊 ストリーミング完了: {total_chunks} チャンク, 合計 {total_length} 文字")
        return total_length > 0
    except Exception as e:
        if verbose:
            print(f"❌ ストリーミングテストが失敗しました: {e}")
        return False


def test_regular(architecture: str = "常時稼働する EC2 t3.micro インスタンス 1 台", verbose: bool = True) -> bool:
    """同期 API (`estimate_costs`) をテストします"""
    if verbose:
        print('📄 通常のコスト見積りをテストしています...')
    agent = AWSCostEstimatorAgent()
    try:
        result = agent.estimate_costs(architecture)
        if verbose:
            print(f"📊 通常レスポンス長: {len(result)} 文字")
            print(f"結果プレビュー: {result[:150]}...")
        return len(result) > 0
    except Exception as e:
        if verbose:
            print(f"❌ 通常テストが失敗しました: {e}")
        return False


def parse_arguments():
    parser = argparse.ArgumentParser(description='AWS コスト見積りエージェントをテストします')
    parser.add_argument('--architecture', type=str, default="常時稼働する EC2 t3.micro インスタンス 1 台")
    parser.add_argument('--tests', nargs='+', choices=['regular', 'streaming', 'debug'], default=['regular'])
    parser.add_argument('--verbose', action='store_true', default=True)
    parser.add_argument('--quiet', action='store_true')
    return parser.parse_args()


async def main():
    args = parse_arguments()
    verbose = args.verbose and not args.quiet
    if verbose:
        print('🚀 テスト開始')
        print(f'アーキテクチャ: {args.architecture}')
        print(f"実行するテスト: {', '.join(args.tests)}")
    results = {}
    if 'regular' in args.tests:
        results['regular'] = test_regular(args.architecture, verbose)
    if 'streaming' in args.tests:
        results['streaming'] = await test_streaming(args.architecture, verbose)
    if verbose:
        print('\n📋 テスト結果:')
        for name, ok in results.items():
            print(f'  {name}: {'✅' if ok else '❌'}')
    return 0 if results and all(results.values()) else 1


if __name__ == '__main__':
    import sys
    sys.exit(asyncio.run(main()))
