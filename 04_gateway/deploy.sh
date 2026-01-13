#!/bin/bash
# Deploy the AgentCore Gateway Lambda function using AWS SAM

set -e

# Activate virtual environment if it exists
if [ -f "../.venv/bin/activate" ]; then
    echo "親ディレクトリの仮想環境を有効化しています..."
    source ../.venv/bin/activate
    echo "仮想環境を有効化しました"
else
    echo "警告: 仮想環境が見つかりません。システムの Python を使用します。"
fi

STACK_NAME="AWS-Cost-Estimator-Tool-Markdown-To-Email"
REGION=$(aws configure get region 2>/dev/null || true)
if [ $# -lt 1 ]; then
    echo "使用法: $0 <ses-送信元メールアドレス>"
    exit 1
fi
SES_SENDER_EMAIL="$1"


echo "Gateway 用 Markdown→Email Lambda をデプロイしています..."
echo "送信元メール: $SES_SENDER_EMAIL"
echo "スタック名: $STACK_NAME"
echo "リージョン: $REGION"

# Verify sender email in SES
echo "Amazon SES で送信元メールを検証しています..."
aws ses verify-email-identity --email-address "$SES_SENDER_EMAIL" --region "$REGION" || {
    echo "警告: メールアドレスの検証に失敗しました。手動で検証する必要があるかもしれません。"
    echo "Amazon SES からの検証メールを確認してください。"
}


# Build the SAM application
echo "SAM アプリケーションをビルドしています..."
sam build

# Deploy the SAM application
echo "SAM アプリケーションをデプロイしています..."
sam deploy \
    --stack-name $STACK_NAME \
    --region $REGION \
    --parameter-overrides "SenderEmail=$SES_SENDER_EMAIL" \
    --capabilities CAPABILITY_IAM \
    --no-confirm-changeset \
    --no-fail-on-empty-changeset \
    --resolve-s3

# Get the Lambda function ARN from stack outputs
LAMBDA_ARN=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query "Stacks[0].Outputs[?OutputKey=='AgentCoreGatewayFunctionArn'].OutputValue" \
    --output text)

if [ -z "$LAMBDA_ARN" ]; then
    echo "Error: Could not retrieve Lambda function ARN from stack outputs"
    exit 1
fi

# Save Lambda ARN to gateway configuration for create_gateway.py
CONFIG_FILE="outbound_gateway.json"
    echo "Lambda ARN を $CONFIG_FILE に保存しています..."

# Create or update the configuration file with Lambda ARN
cat > $CONFIG_FILE << EOF
{
  "lambda_arn": "$LAMBDA_ARN",
  "sender_email": "$SES_SENDER_EMAIL",
  "deployment_timestamp": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "stack_name": "$STACK_NAME",
  "region": "$REGION",
  "tool_name": "markdown_to_email"
}
EOF

echo ""
echo "デプロイが完了しました！"
echo "Lambda 関数 ARN: $LAMBDA_ARN"
echo "送信元メール: $SES_SENDER_EMAIL"
echo "構成は次に保存されました: $CONFIG_FILE"
echo ""
echo "次のステップ:"
echo "1. 送信元メール ($SES_SENDER_EMAIL) が Amazon SES で検証済みであることを確認してください"
echo "2. 'uv run setup_outbound_gateway.py' を実行して Gateway をセットアップしてください（Lambda ARN は設定ファイルから読み取られます）"
echo "3. Gateway は Markdown を HTML に変換してメール送信する 'markdown_to_email' ツールを提供します"
echo ""
echo "ツールの使い方:"
echo "- markdown_text: 変換する Markdown コンテンツ"
echo "- email_address: 受信者のメールアドレス"
echo "- subject: メールの件名（省略可）"

# Deactivate virtual environment if it was activated
if [ ! -z "$VIRTUAL_ENV" ]; then
    echo "仮想環境を無効化しています..."
    deactivate
fi
