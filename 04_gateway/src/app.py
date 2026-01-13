"""
AgentCore Gateway 用のシンプルな Lambda 関数（Markdown を HTML に変換して SES で送信）

初心者向けの説明:
- この Lambda は Gateway のツールとして動作し、外部から受け取った Markdown と受信者アドレスを
    受け取って HTML メールに変換し Amazon SES で送信します。
- テストやデモ用途を想定しており、実運用ではバリデーションやエラーハンドリングを強化してください。
"""

import json
import logging
import os
import boto3
import markdown
from botocore.exceptions import ClientError

# Configure logging
logger = logging.getLogger()
logger.setLevel(os.environ.get('LOG_LEVEL', 'INFO'))


def lambda_handler(event, context):
    """
    Gateway からの `markdown_to_email` 呼び出しを処理する

    引数:
        event: Markdown テキストとメールアドレスを含む辞書
        context: Gateway メタデータを含む Lambda コンテキスト。`client_context` に次のような情報を持ちます。
            ClientContext(custom={
                'bedrockAgentCoreGatewayId': 'Y02ERAYBHB',
                'bedrockAgentCoreTargetId': 'RQHDN3J002',
                'bedrockAgentCoreMessageVersion': '1.0',
                'bedrockAgentCoreToolName': 'markdown_to_email',
                'bedrockAgentCoreSessionId': ''
            }, env=None, client=None)

    戻り値:
        メール送信の成功/失敗メッセージを含む辞書
    """
    try:
        # 受信リクエストをログに記録
        logger.info(f"受信イベント: {json.dumps(event)}")
        
        # Extract tool name from context
        if context and context.client_context:
            logger.info(f"コンテキスト: {context.client_context}")
            tool_name = context.client_context.custom.get('bedrockAgentCoreToolName', '')
            
            # Remove any prefix added by Gateway (format: targetName___toolName)
            if "___" in tool_name:
                tool_name = tool_name.split("___")[-1]
        else:
            tool_name = event.get('tool_name', '')

        logger.info(f"処理中のツール: {tool_name}")
        
        # Verify this is the markdown_to_email tool
        if tool_name != 'markdown_to_email':
            return {
                'statusCode': 400,
                'body': f"不明なツール: {tool_name}"
            }
        
        # イベントから必須パラメータを安全に取得します
        markdown_text = event.get('markdown_text', '')
        email_address = event.get('email_address', '')
        subject = event.get('subject', 'AWS Cost Estimation Result')
        
        if not markdown_text:
            return {
                'statusCode': 400,
                'body': "必須パラメータがありません: markdown_text"
            }
        
        if not email_address:
            return {
                'statusCode': 400,
                'body': "必須パラメータがありません: email_address"
            }

        # Markdown を HTML に変換し、SES で送信する補助関数を呼び出します
        result = convert_and_send_email(markdown_text, email_address, subject)

        return {
            'statusCode': 200,
            'body': result
        }
        
    except Exception as e:
        logger.exception(f"リクエスト処理中にエラーが発生しました: {e}")
        return {
            'statusCode': 500,
            'body': f"エラー: {str(e)}"
        }


def convert_and_send_email(markdown_text, email_address, subject):
    """
    Markdown を HTML に変換して Amazon SES で送信する

    引数:
        markdown_text: 変換する Markdown コンテンツ
        email_address: 受信者のメールアドレス
        subject: メールの件名

    戻り値:
        メッセージ ID を含む成功メッセージ
    """
    try:
        # Markdown を HTML に変換（テーブルサポートあり）
        logger.info("Markdown を HTML に変換しています")
        html_content = markdown.markdown(
            markdown_text,
            extensions=['tables', 'nl2br']
        )
        
        # Get sender email from environment variable
        sender_email = os.environ.get('SES_SENDER_EMAIL')
        if not sender_email:
            raise ValueError("SES_SENDER_EMAIL 環境変数が設定されていません")
        
        # SES クライアントを初期化
        ses_client = boto3.client('ses')
        
        # SES でメールを送信
        logger.info(f"メール送信先: {email_address}")
        response = ses_client.send_email(
            Source=sender_email,
            Destination={
                'ToAddresses': [email_address]
            },
            Message={
                'Subject': {
                    'Data': subject,
                    'Charset': 'UTF-8'
                },
                'Body': {
                    'Html': {
                        'Data': html_content,
                        'Charset': 'UTF-8'
                    },
                    'Text': {
                        'Data': markdown_text,  # Include plain text version
                        'Charset': 'UTF-8'
                    }
                }
            }
        )

        message_id = response['MessageId']
        logger.info(f"メール送信に成功しました。Message ID: {message_id}")

        return f"{email_address} にメールを送信しました。Message ID: {message_id}"
        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_message = e.response['Error']['Message']
        
        if error_code == 'MessageRejected':
            logger.error(f"SES によりメッセージが拒否されました: {error_message}")
            raise Exception(f"SES によってメールが拒否されました: {error_message}")
        elif error_code == 'MailFromDomainNotVerified':
            logger.error(f"送信元ドメインが未検証です: {error_message}")
            raise Exception(f"SES において送信元ドメインが検証されていません: {error_message}")
        else:
            logger.error(f"SES エラー ({error_code}): {error_message}")
            raise Exception(f"SES エラー: {error_message}")
            
    except Exception as e:
        logger.exception(f"メール送信中に予期しないエラーが発生しました: {e}")
        raise Exception(f"メール送信に失敗しました: {str(e)}")
