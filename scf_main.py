# -*- coding: utf-8 -*-
"""
量子密信 DeepSeek 机器人 - 腾讯云函数版
部署方式：腾讯云函数 SCF + API网关触发器
"""
import json
import os
import base64
import logging
import requests

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# 从环境变量读取配置
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1/chat/completions")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
BOT_NAME = os.environ.get("BOT_NAME", "DeepSeek助手")


def call_deepseek(user_message):
    """调用 DeepSeek API 获取回复"""
    if not DEEPSEEK_API_KEY:
        return "错误：未配置 DEEPSEEK_API_KEY，请在环境变量中设置。"

    system_prompt = (
        f"你是{BOT_NAME}，一个运行在量子密信群聊中的AI助手。"
        "请用简洁专业的中文回复用户问题。"
        "如果问题超出你的能力范围，请诚实说明。"
    )

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ],
        "max_tokens": 2000,
        "temperature": 0.7
    }

    try:
        resp = requests.post(DEEPSEEK_BASE_URL, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        reply = data["choices"][0]["message"]["content"]
        logger.info(f"DeepSeek 回复成功，长度: {len(reply)}")
        return reply
    except requests.exceptions.Timeout:
        return "抱歉，DeepSeek 响应超时，请稍后再试。"
    except requests.exceptions.HTTPError as e:
        logger.error(f"DeepSeek API HTTP 错误: {e}, 响应: {resp.text}")
        return f"DeepSeek API 调用失败（HTTP {resp.status_code}），请联系管理员。"
    except Exception as e:
        logger.error(f"DeepSeek API 异常: {e}")
        return "内部错误，请稍后再试。"


def reply_to_mixin(callback_url, callback_method, text):
    """将回复推送到量子密信群聊"""
    if not callback_url:
        logger.warning("callBackUrl 为空，无法回复")
        return False

    payload = {
        "type": "text",
        "textMsg": {"content": text}
    }

    try:
        if callback_method and callback_method.upper() == "GET":
            resp = requests.get(callback_url, timeout=10)
        else:
            resp = requests.post(callback_url, json=payload, timeout=10)

        logger.info(f"回复密信状态: {resp.status_code}")
        return resp.status_code == 200
    except Exception as e:
        logger.error(f"回复密信失败: {e}")
        return False


def main_handler(event, context):
    """腾讯云函数入口 - 处理API网关触发器的事件"""
    logger.info(f"收到事件: {json.dumps(event, ensure_ascii=False)[:500]}")

    # 解析请求路径
    path = event.get("path", "/")
    http_method = event.get("httpMethod", "GET")

    # 首页
    if path == "/" and http_method == "GET":
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "name": BOT_NAME,
                "description": "量子密信 DeepSeek 机器人回调服务",
                "endpoints": {
                    "/webhook": "POST - 密信回调入口",
                    "/health": "GET - 健康检查"
                }
            }, ensure_ascii=False)
        }

    # 健康检查
    if path == "/health" and http_method == "GET":
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "status": "ok",
                "message": "服务运行正常",
                "deepseek_configured": bool(DEEPSEEK_API_KEY),
                "model": DEEPSEEK_MODEL
            }, ensure_ascii=False)
        }

    # 密信回调入口
    if path == "/webhook" and http_method == "POST":
        # 解析请求体
        body = event.get("body", "{}")
        if event.get("isBase64Encoded", False):
            body = base64.b64decode(body).decode("utf-8")

        try:
            data = json.loads(body)
        except Exception as e:
            logger.error(f"解析请求体失败: {e}")
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"status": "error", "message": "无法解析请求"})
            }

        # 提取关键字段
        callback_url = data.get("callBackUrl", "")
        callback_method = data.get("callBackMethod", "POST")
        phone = data.get("phone", "")
        group_id = data.get("groupId", "")
        text_msg = data.get("textMsg", {})
        user_content = text_msg.get("content", "")

        if not user_content:
            logger.warning("收到空消息")
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"status": "ok", "message": "空消息已忽略"})
            }

        logger.info(f"用户 {phone} 在群 {group_id} @机器人: {user_content}")

        # 调用 DeepSeek
        reply_text = call_deepseek(user_content)

        # 回复到密信群
        if callback_url:
            reply_to_mixin(callback_url, callback_method, reply_text)

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"status": "ok", "message": "已处理"})
        }

    # 404
    return {
        "statusCode": 404,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"status": "error", "message": "路径不存在"})
    }
