# api_server.py
# 新一代 LMArena - 对战专用服务器

import asyncio
import json
import logging
import os
import sys
import subprocess
import time
import uuid
import re
import random
from datetime import datetime
from contextlib import asynccontextmanager

import uvicorn
import requests
import httpx  # 用于向外部代理发送HTTP请求
from packaging.version import parse as parse_version
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, Response

# --- 导入自定义模块 ---
# image_generation 已被移除，因为它依赖于旧的代理逻辑
from modules import battle_db
from modules import battle_mode_handler
from modules import elo_manager

# --- 基础配置 ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- 全局状态与配置 ---
CONFIG = {} # 存储从 config.jsonc 加载的配置
last_activity_time = None # 记录最后一次活动的时间
main_event_loop = None # 主事件循环

# 新增: 外部代理服务地址
# 对战服务器将通过此地址调用模型生成回复
PROXY_URL = "http://127.0.0.1:5102" 

# --- 模型池 ---
MODEL_POOL = [] # 用于从 models.json 存储可用的模型ID
DEFAULT_MODEL_ID = "default-model" # 默认模型

def load_model_pool():
    """从 models.json 加载可用的模型列表。"""
    global MODEL_POOL
    try:
        with open('models.json', 'r', encoding='utf-8') as f:
            models = json.load(f)
            if isinstance(models, list):
                MODEL_POOL = models
                logger.info(f"成功从 'models.json' 加载了 {len(MODEL_POOL)} 个模型。")
            else:
                logger.error("'models.json' 的内容不是一个JSON列表。")
                MODEL_POOL = []
    except FileNotFoundError:
        logger.warning("'models.json' 文件未找到。将使用空模型池。")
        MODEL_POOL = []
    except json.JSONDecodeError as e:
        logger.error(f"加载或解析 'models.json' 失败: {e}。")
        MODEL_POOL = []

def load_config():
    """从 config.jsonc 加载配置，并处理 JSONC 注释。"""
    global CONFIG
    try:
        with open('config.jsonc', 'r', encoding='utf-8') as f:
            content = f.read()
            json_content = re.sub(r'//.*', '', content)
            json_content = re.sub(r'/\*.*?\*/', '', json_content, flags=re.DOTALL)
            CONFIG = json.loads(json_content)
        logger.info("成功从 'config.jsonc' 加载配置。")
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"加载或解析 'config.jsonc' 失败: {e}。将使用默认配置。")
        CONFIG = {}

# --- 更新检查 (保留) ---
GITHUB_REPO = "Lianues/LMArenaBridge"

def download_and_extract_update(version):
    """下载并解压最新版本到临时文件夹。"""
    update_dir = "update_temp"
    if not os.path.exists(update_dir):
        os.makedirs(update_dir)
    try:
        zip_url = f"https://github.com/{GITHUB_REPO}/archive/refs/heads/main.zip"
        logger.info(f"正在从 {zip_url} 下载新版本...")
        response = requests.get(zip_url, timeout=60)
        response.raise_for_status()
        import zipfile
        import io
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            z.extractall(update_dir)
        logger.info(f"新版本已成功下载并解压到 '{update_dir}' 文件夹。")
        return True
    except Exception as e:
        logger.error(f"下载或解压更新失败: {e}")
        return False

def check_for_updates():
    """从 GitHub 检查新版本。"""
    if not CONFIG.get("enable_auto_update", True):
        logger.info("自动更新已禁用，跳过检查。")
        return

    current_version = CONFIG.get("version", "0.0.0")
    logger.info(f"当前版本: {current_version}。正在从 GitHub 检查更新...")

    try:
        config_url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/config.jsonc"
        response = requests.get(config_url, timeout=10)
        response.raise_for_status()
        jsonc_content = response.text
        json_content = re.sub(r'//.*', '', jsonc_content)
        json_content = re.sub(r'/\*.*?\*/', '', json_content, flags=re.DOTALL)
        remote_config = json.loads(json_content)
        remote_version_str = remote_config.get("version")
        if not remote_version_str:
            logger.warning("远程配置文件中未找到版本号，跳过更新检查。")
            return

        if parse_version(remote_version_str) > parse_version(current_version):
            logger.info("="*60)
            logger.info(f"🎉 发现新版本! 🎉 (最新: {remote_version_str})")
            if download_and_extract_update(remote_version_str):
                logger.info("准备应用更新。服务器将在5秒后关闭并启动更新脚本。")
                time.sleep(5)
                update_script_path = os.path.join("modules", "update_script.py")
                subprocess.Popen([sys.executable, update_script_path])
                os._exit(0)
            else:
                logger.error(f"自动更新失败。请访问 https://github.com/{GITHUB_REPO}/releases/latest 手动下载。")
            logger.info("="*60)
        else:
            logger.info("您的程序已是最新版本。")
    except Exception as e:
        logger.error(f"检查更新时发生未知错误: {e}")

# --- FastAPI 生命周期事件 ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """在服务器启动时运行的生命周期函数。"""
    global last_activity_time, main_event_loop
    main_event_loop = asyncio.get_running_loop()
    load_config()
    check_for_updates()
    load_model_pool()
    
    # 初始化数据库
    battle_db.init_db()
    elo_manager.init_db()
    
    logger.info("="*60)
    logger.info("🚀 LMArena 对战服务器已成功启动 🚀")
    logger.info(f"将调用外部代理服务于: {PROXY_URL}")
    logger.info("="*60)

    last_activity_time = datetime.now()
    yield
    logger.info("服务器正在关闭。")

app = FastAPI(lifespan=lifespan)

# --- CORS 中间件配置 ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- OpenAI 格式化辅助函数 (用于即时返回) ---
def format_openai_chunk(content: str, model: str, request_id: str) -> str:
    """格式化为 OpenAI 流式块。"""
    chunk = {
        "id": request_id, "object": "chat.completion.chunk",
        "created": int(time.time()), "model": model,
        "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}]
    }
    return f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

def format_openai_finish_chunk(model: str, request_id: str, reason: str = 'stop') -> str:
    """格式化为 OpenAI 结束块。"""
    chunk = {
        "id": request_id, "object": "chat.completion.chunk",
        "created": int(time.time()), "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": reason}]
    }
    return f"data: {json.dumps(chunk, ensure_ascii=False)}\n\ndata: [DONE]\n\n"

def format_openai_non_stream_response(content: str, model: str, request_id: str, reason: str = 'stop') -> dict:
    """构建符合 OpenAI 规范的非流式响应体。"""
    return {
        "id": request_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": reason,
        }],
        "usage": { "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0 },
    }

# --- API 端点 ---
@app.get("/v1/models")
async def get_models():
    """提供一个固定的模型 'leinao_arena'，用于触发对战模式。"""
    return {
        "object": "list",
        "data": [
            {
                "id": "leinao_arena",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "API_Battle_Server"
            }
        ],
    }

@app.get("/v1/leaderboard")
async def get_leaderboard():
    """提供模型 ELO 排行榜。"""
    leaderboard_data = elo_manager.get_leaderboard()
    return JSONResponse(content=leaderboard_data)

async def stream_proxy_response(response: httpx.Response, display_model_name: str):
    """将来自外部代理的流式响应转发给客户端。"""
    request_id = f"chatcmpl-{uuid.uuid4()}"
    try:
        async for chunk in response.aiter_bytes():
            # 直接转发原始数据块
            yield chunk
    except Exception as e:
        logger.error(f"代理流转发时发生错误: {e}")
        # 如果出错，发送一个错误块
        error_content = f"\n\n[Battle Server Error]: 代理流在转发时中断: {e}"
        yield format_openai_chunk(error_content, display_model_name, request_id).encode('utf-8')
        yield format_openai_finish_chunk(display_model_name, request_id).encode('utf-8')

@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """
    处理聊天补全请求。此端点现在专用于对战模式。
    它会调用外部的代理服务来获取模型生成的内容。
    """
    global last_activity_time
    last_activity_time = datetime.now()

    # --- API Key 验证 ---
    api_key = CONFIG.get("api_key")
    if api_key:
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            raise HTTPException(
                status_code=401,
                detail="未提供 API Key。请在 Authorization 头部中以 'Bearer YOUR_KEY' 格式提供。"
            )
        
        provided_key = auth_header.split(' ')[1]
        if provided_key != api_key:
            raise HTTPException(
                status_code=401,
                detail="提供的 API Key 不正确。"
            )
    
    try:
        openai_req = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="无效的 JSON 请求体")

    # 新增：检查模型名称是否为 "leinao_arena"
    if openai_req.get("model") != "leinao_arena":
        raise HTTPException(status_code=400, detail="模型名称不正确，必须为 'leinao_arena'。")

    # 强制对战模式
    if not openai_req.get("extra_body", {}).get("battle_mode_active"):
        raise HTTPException(status_code=400, detail="此服务器仅接受对战模式 (battle_mode_active: true) 的请求。")
    
    logger.info("检测到对战模式请求，进入处理流程...")
    result = battle_mode_handler.handle_battle_mode_request(openai_req)
    result_type, result_data = result

    # --- 处理 WIN 或 ERROR 指令 ---
    # 这两种情况不需要调用外部代理，直接返回结果
    if result_type in ['WIN', 'ERROR']:
        is_stream = openai_req.get("stream", True)
        response_id = f"chatcmpl-{uuid.uuid4()}"

        if result_type == 'WIN':
            win_data = result_data
            response_content = (
                f"对战结果已成功记录。\nRPID: {win_data['rpid']}\n"
                f"--------------------\n"
                f"A: {win_data['model_a']} vs B: {win_data['model_b']}"
            )
            model_name_for_response = "battle_results"
        else: # ERROR
            response_content = f"[对战模式错误]: {result_data}"
            model_name_for_response = "battle_error"

        if is_stream:
            async def _instant_stream_response(content, model_name, request_id):
                yield format_openai_chunk(content, model_name, request_id)
                yield format_openai_finish_chunk(model_name, request_id)
            return StreamingResponse(
                _instant_stream_response(response_content, model_name_for_response, response_id),
                media_type="text/event-stream"
            )
        else:
            response_data = format_openai_non_stream_response(
                response_content, model_name_for_response, response_id
            )
            return JSONResponse(content=response_data)

    # --- 处理 GENERATE 指令 ---
    # 这种情况需要调用外部代理服务
    elif result_type == 'GENERATE':
        processed_req, display_model_name = result_data
        is_stream = processed_req.get("stream", True)
        
        # 确保请求体中包含 model 字段，代理服务需要它
        if "model" not in processed_req:
             raise HTTPException(status_code=400, detail="[Battle Server Error]: 生成请求中缺少 'model' 字段。")

        logger.info(f"正在向代理服务 ({PROXY_URL}) 请求模型 '{processed_req['model']}' 的响应...")

        try:
            async with httpx.AsyncClient(timeout=360.0) as client:
                # 准备请求头，如果原始请求有 Authorization，可以考虑转发
                headers = {"Content-Type": "application/json"}
                
                # 发起请求到代理服务
                proxy_response = await client.post(
                    f"{PROXY_URL}/v1/chat/completions",
                    json=processed_req,
                    headers=headers
                )
                proxy_response.raise_for_status()

                if is_stream:
                    # 将代理的流式响应直接转发给客户端
                    return StreamingResponse(
                        stream_proxy_response(proxy_response, display_model_name),
                        media_type="text/event-stream"
                    )
                else:
                    # 等待并返回非流式响应
                    response_data = await proxy_response.aread()
                    return Response(content=response_data, media_type="application/json")

        except httpx.ConnectError as e:
            logger.error(f"无法连接到代理服务: {e}")
            raise HTTPException(status_code=503, detail=f"无法连接到外部代理服务 ({PROXY_URL})。请确保代理服务正在运行。")
        except httpx.HTTPStatusError as e:
            # 尝试解析代理返回的错误信息
            error_detail = e.response.text
            logger.error(f"代理服务返回错误状态 {e.response.status_code}: {error_detail}")
            raise HTTPException(status_code=e.response.status_code, detail=f"代理服务出错: {error_detail}")
        except Exception as e:
            logger.error(f"调用代理服务时发生未知错误: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"调用代理服务时发生未知内部错误: {e}")
    
    else:
        raise HTTPException(status_code=500, detail=f"未知的 battle_mode_handler 返回类型: {result_type}")


# --- 主程序入口 ---
if __name__ == "__main__":
    # 使用 config.jsonc 中的端口或默认值
    load_config()
    api_port = CONFIG.get("battle_server_port", 5103) # 使用新端口避免与代理冲突
    
    logger.info(f"🚀 LMArena 对战服务器 v3.0 正在启动...")
    logger.info(f"   - 监听地址: http://127.0.0.1:{api_port}")
    
    uvicorn.run(app, host="0.0.0.0", port=api_port)
