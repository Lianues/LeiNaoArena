# elo_manager.py

import sqlite3
import logging
import math

# --- 配置 ---
DB_PATH = 'elo_ratings.db'
INITIAL_RATING = 1000
K_FACTOR = 32
logger = logging.getLogger(__name__)

def init_db():
    """初始化ELO评分数据库。"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS ratings (
                    model_id TEXT PRIMARY KEY,
                    rating INTEGER NOT NULL,
                    num_battles INTEGER NOT NULL DEFAULT 0
                )
            ''')
            conn.commit()
        logger.info(f"ELO数据库 '{DB_PATH}' 初始化成功。")
    except sqlite3.Error as e:
        logger.error(f"ELO数据库初始化失败: {e}", exc_info=True)
        raise

def get_rating(model_id: str) -> int:
    """
    获取模型的ELO分数。如果模型不存在，则为其创建初始分数。
    """
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT rating FROM ratings WHERE model_id = ?", (model_id,))
            result = cursor.fetchone()
            
            if result:
                return result[0]
            else:
                # 模型不存在，创建新记录
                logger.info(f"模型 '{model_id}' 不在ELO数据库中，为其创建初始分数 {INITIAL_RATING}。")
                cursor.execute(
                    "INSERT INTO ratings (model_id, rating) VALUES (?, ?)",
                    (model_id, INITIAL_RATING)
                )
                conn.commit()
                return INITIAL_RATING
    except sqlite3.Error as e:
        logger.error(f"获取模型 '{model_id}' 的分数时出错: {e}", exc_info=True)
        return INITIAL_RATING # 出错时返回默认值

def update_ratings(model_a_id: str, model_b_id: str, winner: str):
    """
    根据比赛结果更新两个模型的ELO分数。
    :param winner: 'A', 'B', 'TIE', 或 'FLAG'
    """
    rating_a = get_rating(model_a_id)
    rating_b = get_rating(model_b_id)

    # 1. 计算期望胜率
    expected_a = 1 / (1 + math.pow(10, (rating_b - rating_a) / 400))
    expected_b = 1 / (1 + math.pow(10, (rating_a - rating_b) / 400))

    # 2. 确定实际得分
    if winner == 'A':
        score_a, score_b = 1.0, 0.0
    elif winner == 'B':
        score_a, score_b = 0.0, 1.0
    elif winner == 'TIE':
        score_a, score_b = 0.5, 0.5
    elif winner == 'FLAG': # 双方皆负
        score_a, score_b = 0.0, 0.0
    else:
        logger.warning(f"未知的胜利者类型 '{winner}'，本次比赛不计分。")
        return

    # 3. 计算新分数
    new_rating_a = round(rating_a + K_FACTOR * (score_a - expected_a))
    new_rating_b = round(rating_b + K_FACTOR * (score_b - expected_b))

    logger.info(f"ELO更新: '{model_a_id}' ({rating_a} -> {new_rating_a}), '{model_b_id}' ({rating_b} -> {new_rating_b})")

    # 4. 更新数据库
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE ratings SET rating = ?, num_battles = num_battles + 1 WHERE model_id = ?",
                (new_rating_a, model_a_id)
            )
            cursor.execute(
                "UPDATE ratings SET rating = ?, num_battles = num_battles + 1 WHERE model_id = ?",
                (new_rating_b, model_b_id)
            )
            conn.commit()
    except sqlite3.Error as e:
        logger.error(f"更新ELO分数时出错: {e}", exc_info=True)

def get_leaderboard() -> list[dict]:
    """获取按ELO分数降序排列的模型排行榜。"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT model_id, rating, num_battles FROM ratings ORDER BY rating DESC")
            rows = cursor.fetchall()
            leaderboard = [
                {"rank": i + 1, "model_id": row[0], "rating": row[1], "battles": row[2]}
                for i, row in enumerate(rows)
            ]
            return leaderboard
    except sqlite3.Error as e:
        logger.error(f"获取排行榜时出错: {e}", exc_info=True)
        return []