# battle_mode_handler.py

import logging
import re
# from fastapi.responses import JSONResponse # No longer needed here

from .battle_db import get_or_create_battle_session, record_battle_result, check_rpid_exists

logger = logging.getLogger(__name__)

# --- 指令清理正则表达式 ---
# 匹配所有指令，包括可选的RPID部分
COMMAND_PATTERN = re.compile(
    r"^\$(startA|sA|startB|sB|battleA|A|battleB|B|winA|wA|winB|wB|tie|bad)\w*\s*"
)

def _clean_user_content(content: str) -> str:
    """从字符串开头移除指令前缀。"""
    if isinstance(content, str):
        return COMMAND_PATTERN.sub("", content, count=1)
    return content

def _prepare_generation_payload(rpid: str, request_body: dict, model_source_key: str, model_a: str, model_b: str):
    """
    统一的文本生成载荷准备函数。
    """
    extra_body = request_body.get("extra_body", {})
    model_source = extra_body.get(model_source_key)

    # 此处的验证现在由主处理函数负责，这里假定输入是正确的
    display_model_name = model_source[0]
    real_model_name = model_a if display_model_name == "Assistant A" else model_b
    logger.info(f"BATTLE MODE [rpid: {rpid}, cmd: {model_source_key[:-1]}]: 助手 '{display_model_name}' 映射到真实模型: '{real_model_name}'")

    modified_request = request_body.copy()
    modified_request["model"] = real_model_name
    
    # --- 清理用户输入 ---
    if "messages" in modified_request and isinstance(modified_request["messages"], list):
        for message in modified_request["messages"]:
            if message.get("role") == "user":
                original_content = message.get("content", "")
                cleaned_content = _clean_user_content(original_content)
                if original_content != cleaned_content:
                    logger.info(f"BATTLE MODE [rpid: {rpid}]: 清理用户消息: '{original_content[:50]}...' -> '{cleaned_content[:50]}...'")
                    message["content"] = cleaned_content

    if "extra_body" in modified_request:
        del modified_request["extra_body"]

    return modified_request, display_model_name

def handle_battle_mode_request(request_body: dict):
    """
    处理对战模式的特定逻辑。
    根据 extra_body 中的指令进行分发，并返回一个元组，由主程序统一格式化。
    返回元组格式: (TYPE, data)
    TYPE 可以是: 'GENERATE', 'WIN', 'ERROR'
    """
    extra_body = request_body.get("extra_body", {})
    rpid = extra_body.get("rpid")

    # --- 通用验证 ---
    if not extra_body.get("battle_mode_active") or extra_body.get("context_type") != "battle_simulation":
        return ('ERROR', "请求格式不正确：缺少 'battle_mode_active' 或 'context_type' 不匹配。")
    if not rpid or not isinstance(rpid, str):
        return ('ERROR', "对话ID异常：'rpid' 字段缺失或格式不正确。")

    # --- 指令分发 ---
    if "win_models" in extra_body:
        logger.info(f"BATTLE MODE [rpid: {rpid}, cmd: win]: 检测到结果提交请求。")
        win_models = extra_body["win_models"]
        if not isinstance(win_models, list):
            return ('ERROR', "'win_models' 必须是一个列表。")
        
        model_a, model_b = record_battle_result(rpid, win_models)
        if not model_a:
             return ('ERROR', f"无法为 rpid '{rpid}' 记录结果，可能该rpid不存在。")

        return ('WIN', {"model_a": model_a, "model_b": model_b, "rpid": rpid})
    
    # --- 生成类指令的通用验证 ---
    model_source_key = None
    if "start_models" in extra_body:
        model_source_key = "start_models"
    elif "battle_models" in extra_body:
        model_source_key = "battle_models"

    if model_source_key:
        model_source = extra_body.get(model_source_key)
        if not isinstance(model_source, list) or len(model_source) != 1 or model_source[0] not in ["Assistant A", "Assistant B"]:
            return ('ERROR', f"请求模型指令异常：'{model_source_key}' 字段不正确。")
    else:
        return ('ERROR', "对战模式请求缺少有效指令 (win_models, start_models, 或 battle_models)。")

    # --- 生成类指令的特定逻辑 ---
    if model_source_key == "start_models":
        logger.info(f"BATTLE MODE [rpid: {rpid}, cmd: start]: 检测到开始新对战请求。")
        if check_rpid_exists(rpid):
            return ('ERROR', f"rpid '{rpid}' 已存在，无法开始新的对战。请更换 rpid。")
        
        model_a, model_b, _ = get_or_create_battle_session(rpid)
        if not model_a:
            return ('ERROR', "服务器内部错误：无法创建对战会话。")
        
        payload, display_name = _prepare_generation_payload(rpid, request_body, "start_models", model_a, model_b)
        return ('GENERATE', (payload, display_name))

    elif model_source_key == "battle_models":
        logger.info(f"BATTLE MODE [rpid: {rpid}, cmd: battle]: 检测到继续对战请求。")
        model_a, model_b, status = get_or_create_battle_session(rpid)
        
        if not status:
            return ('ERROR', f"rpid '{rpid}' 不存在，无法继续对战。请先使用 start 指令。")
        if status == 'completed':
            return ('ERROR', f"rpid '{rpid}' 的对战已完成，无法继续。")
        
        payload, display_name = _prepare_generation_payload(rpid, request_body, "battle_models", model_a, model_b)
        return ('GENERATE', (payload, display_name))
    
    # 此处理论上不会到达
    return ('ERROR', "未知的服务器内部错误。")