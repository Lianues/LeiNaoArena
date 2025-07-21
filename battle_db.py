# battle_db.py

import sqlite3
import json
import random
import logging
import os
from datetime import datetime
import elo_manager

# --- 配置 ---
DB_PATH = 'battle_sessions.db'
MODEL_MAP_PATH = 'model_endpoint_map.json'
logger = logging.getLogger(__name__)

def init_db():
    """
    初始化数据库。如果表不存在，则创建它。
    """
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS battle_sessions (
                    rpid TEXT PRIMARY KEY,
                    model_a TEXT NOT NULL,
                    model_b TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    winner TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP
                )
            ''')
            conn.commit()
        logger.info(f"数据库 '{DB_PATH}' 初始化成功，表 'battle_sessions' 已准备就绪。")
    except sqlite3.Error as e:
        logger.error(f"数据库初始化失败: {e}", exc_info=True)
        raise

def _get_available_models():
    """
    从 model_endpoint_map.json 加载并返回可用的模型ID列表。
    """
    if not os.path.exists(MODEL_MAP_PATH):
        logger.error(f"模型映射文件 '{MODEL_MAP_PATH}' 未找到。")
        return []
    try:
        with open(MODEL_MAP_PATH, 'r', encoding='utf-8') as f:
            content = f.read()
            if not content.strip():
                return []
            model_map = json.loads(content)
            return list(model_map.keys())
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"加载或解析 '{MODEL_MAP_PATH}' 时出错: {e}", exc_info=True)
        return []

def get_or_create_battle_session(rpid: str) -> tuple[str | None, str | None, str | None]:
    """
    根据 rpid 获取或创建对战会话的模型分配和状态。
    - 如果 rpid 已存在，返回存储的模型 A、B 和当前状态。
    - 如果 rpid 不存在，随机选择两个不同的模型，存储后返回模型和 'active' 状态。
    - 如果模型不足或发生错误，返回 (None, None, None)。
    """
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            # 1. 检查 rpid 是否已存在
            cursor.execute("SELECT model_a, model_b, status FROM battle_sessions WHERE rpid = ?", (rpid,))
            result = cursor.fetchone()
            
            if result:
                logger.info(f"为 rpid '{rpid}' 找到现有会话，模型为: A='{result[0]}', B='{result[1]}', 状态: '{result[2]}'")
                return result[0], result[1], result[2]
            
            # 2. 如果不存在，创建新会话
            logger.info(f"未找到 rpid '{rpid}' 的现有会话，正在创建新条目...")
            available_models = _get_available_models()
            
            if len(available_models) < 2:
                logger.error("模型池中可用模型少于2个，无法创建对战会话。")
                return None, None, None
            
            # 随机选择两个不重复的模型
            model_a, model_b = random.sample(available_models, 2)
            
            # 插入新记录
            cursor.execute(
                "INSERT INTO battle_sessions (rpid, model_a, model_b, status, created_at) VALUES (?, ?, ?, ?, ?)",
                (rpid, model_a, model_b, 'active', datetime.now())
            )
            conn.commit()
            
            logger.info(f"为 rpid '{rpid}' 创建了新会话，随机分配模型: A='{model_a}', B='{model_b}'")
            return model_a, model_b, 'active'
            
    except sqlite3.Error as e:
        logger.error(f"处理 rpid '{rpid}' 时发生数据库错误: {e}", exc_info=True)
        return None, None, None

def record_battle_result(rpid: str, win_models: list) -> tuple[str | None, str | None]:
    """
    记录对战结果，更新会话状态为 'completed'，并返回双方的模型ID。
    """
    # 将 win_models 列表转换为标准化的 winner 字符串
    winner = "TIE" # 平局
    if len(win_models) == 1:
        if win_models[0] == "Assistant A":
            winner = "A"
        elif win_models[0] == "Assistant B":
            winner = "B"
    elif not win_models: # 空列表
        winner = "FLAG" # 标记/双方都输

    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            # 首先，获取模型ID
            cursor.execute("SELECT model_a, model_b FROM battle_sessions WHERE rpid = ?", (rpid,))
            models = cursor.fetchone()
            if not models:
                logger.error(f"尝试为不存在的 rpid '{rpid}' 记录结果。")
                return None, None
            
            # 然后，更新记录
            cursor.execute(
                "UPDATE battle_sessions SET status = ?, winner = ?, updated_at = ? WHERE rpid = ?",
                ('completed', winner, datetime.now(), rpid)
            )
            conn.commit()
            
            logger.info(f"已为 rpid '{rpid}' 记录对战结果。胜利者: {winner}。会话状态更新为 'completed'。")
            
            # --- ELO 更新 ---
            model_a_id, model_b_id = models[0], models[1]
            logger.info(f"正在为对战 rpid '{rpid}' 的模型更新ELO分数...")
            elo_manager.update_ratings(model_a_id, model_b_id, winner)
            
            return model_a_id, model_b_id
            
    except sqlite3.Error as e:
        logger.error(f"为 rpid '{rpid}' 记录结果时发生数据库错误: {e}", exc_info=True)
        return None, None

def check_rpid_exists(rpid: str) -> bool:
    """检查指定的 rpid 是否已存在于数据库中。"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM battle_sessions WHERE rpid = ?", (rpid,))
            return cursor.fetchone() is not None
    except sqlite3.Error as e:
        logger.error(f"检查 rpid '{rpid}' 是否存在时出错: {e}", exc_info=True)
        return False # 出错时保守地返回 False
