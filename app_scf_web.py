# -*- coding: utf-8 -*-
"""
量子密信 DeepSeek 机器人 - 腾讯云函数 Web 函数版（带鉴权）
部署方式：腾讯云 SCF Web 函数 + 函数URL
依赖：仅 Flask（SCF自带），HTTP请求用urllib零额外依赖
"""
import os
import json
import logging
import urllib.request
import urllib.error
from flask import Flask, request, jsonify

app = Flask(__name__)

# 日志配置
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===== 从环境变量读取配置 =====
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1/chat/completions")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
BOT_NAME = os.environ.get("BOT_NAME", "DeepSeek助手")
# webhook鉴权密钥（防止公网裸调消耗余额）
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")


def call_deepseek(user_message: str) -> str:
    """调用 DeepSeek API 获取回复（使用urllib，无需安装requests）"""
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
        req_data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            DEEPSEEK_BASE_URL,
            data=req_data,
            headers=headers,
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            reply = data["choices"][0]["message"]["content"]
            logger.info(f"DeepSeek 回复成功，长度: {len(reply)}")
            return reply
    except urllib.error.HTTPError as e:
        error_body = ""
        try:
            error_body = e.read().decode("utf-8")
        except Exception:
            pass
        logger.error(f"DeepSeek API HTTP 错误: {e.code}, 响应: {error_body}")
        if e.code == 402:
            return "DeepSeek 余额不足，请联系管理员充值。"
        return f"DeepSeek API 调用失败（HTTP {e.code}），请联系管理员。"
    except Exception as e:
        logger.error(f"DeepSeek API 异常: {type(e).__name__}: {e}")
        # 超时类异常
        if "timeout" in str(e).lower() or "timed out" in str(e).lower():
            return "抱歉，DeepSeek 响应超时，请稍后再试。"
        return "内部错误，请稍后再试。"


def reply_to_mixin(callback_url: str, callback_method: str, text: str) -> bool:
    """将回复推送到量子密信群聊（使用urllib）"""
    if not callback_url:
        logger.warning("callBackUrl 为空，无法回复")
        return False

    payload = {
        "type": "text",
        "textMsg": {"content": text}
    }

    try:
        method = (callback_method or "POST").upper()
        req_data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            callback_url,
            data=req_data,
            headers={"Content-Type": "application/json"},
            method=method
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            logger.info(f"回复密信状态: {resp.status}")
            return resp.status == 200
    except Exception as e:
        logger.error(f"回复密信失败: {e}")
        return False


@app.route("/webhook", methods=["POST"])
def webhook():
    """量子密信回调入口（带鉴权）"""

    # ===== 鉴权校验 =====
    if WEBHOOK_SECRET:
        # 支持query参数 ?key=xxx 和 header x-webhook-key
        provided_key = request.args.get("key", "") or request.headers.get("x-webhook-key", "")
        if provided_key != WEBHOOK_SECRET:
            logger.warning(f"鉴权失败，IP: {request.remote_addr}")
            return jsonify({"status": "error", "message": "Unauthorized"}), 403

    try:
        data = request.get_json(force=True)
        logger.info(f"收到密信回调: {json.dumps(data, ensure_ascii=False)[:500]}")
    except Exception as e:
        logger.error(f"解析请求失败: {e}")
        return jsonify({"status": "error", "message": "无法解析请求"}), 400

    # 提取关键字段
    msg_type = data.get("type", "")
    callback_url = data.get("callBackUrl", "")
    callback_method = data.get("callBackMethod", "POST")
    phone = data.get("phone", "")
    group_id = data.get("groupId", "")
    robot_id = data.get("robotId", "")
    text_msg = data.get("textMsg", {})
    user_content = text_msg.get("content", "")

    if not user_content:
        logger.warning("收到空消息")
        return jsonify({"status": "ok", "message": "空消息已忽略"})

    logger.info(f"用户 {phone} 在群 {group_id} @机器人: {user_content}")

    # 调用 DeepSeek
    reply_text = call_deepseek(user_content)

    # 回复到密信群
    if callback_url:
        success = reply_to_mixin(callback_url, callback_method, reply_text)
        if success:
            logger.info("回复成功")
        else:
            logger.warning("回复失败")

    return jsonify({"status": "ok", "message": "已处理"})


@app.route("/health", methods=["GET"])
def health():
    """健康检查接口"""
    return jsonify({
        "status": "ok",
        "message": "服务运行正常",
        "deepseek_configured": bool(DEEPSEEK_API_KEY),
        "model": DEEPSEEK_MODEL,
        "auth_enabled": bool(WEBHOOK_SECRET)
    })


@app.route("/", methods=["GET"])
def index():
    """首页"""
    return jsonify({
        "name": BOT_NAME,
        "description": "量子密信 DeepSeek 机器人回调服务",
        "endpoints": {
            "/webhook": "POST - 密信回调入口（需鉴权）",
            "/health": "GET - 健康检查"
        }
    })
