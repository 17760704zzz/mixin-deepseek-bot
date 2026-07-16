"""
量子密信 DeepSeek 机器人 - 回调服务
部署到 Render/Railway 等免费云平台
"""
import os
import json
import logging
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

# 日志配置
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 从环境变量读取配置
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1/chat/completions")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
# 机器人身份标识（可选，用于区分多个机器人）
BOT_NAME = os.environ.get("BOT_NAME", "DeepSeek助手")


def call_deepseek(user_message: str, system_prompt: str = None) -> str:
    """调用 DeepSeek API 获取回复"""
    if not DEEPSEEK_API_KEY:
        return "错误：未配置 DEEPSEEK_API_KEY，请在环境变量中设置。"

    if not system_prompt:
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


def reply_to_mixin(callback_url: str, callback_method: str, text: str) -> bool:
    """将回复推送到量子密信群聊"""
    if not callback_url:
        logger.warning("callBackUrl 为空，无法回复")
        return False

    payload = {
        "type": "text",
        "textMsg": {"content": text}
    }

    try:
        method = callback_method.upper() if callback_method else "POST"
        if method == "POST":
            resp = requests.post(callback_url, json=payload, timeout=10)
        else:
            resp = requests.get(callback_url, timeout=10)

        logger.info(f"回复密信状态: {resp.status_code}")
        return resp.status_code == 200
    except Exception as e:
        logger.error(f"回复密信失败: {e}")
        return False


@app.route("/webhook", methods=["POST"])
def webhook():
    """量子密信回调入口"""
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
    has_key = bool(DEEPSEEK_API_KEY)
    return jsonify({
        "status": "ok",
        "message": "服务运行正常",
        "deepseek_configured": has_key,
        "model": DEEPSEEK_MODEL
    })


@app.route("/", methods=["GET"])
def index():
    """首页"""
    return jsonify({
        "name": BOT_NAME,
        "description": "量子密信 DeepSeek 机器人回调服务",
        "endpoints": {
            "/webhook": "POST - 密信回调入口",
            "/health": "GET - 健康检查"
        }
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
