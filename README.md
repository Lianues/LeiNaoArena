# 🚀 LMArena Battle & Elo Ranking System ⚔️

欢迎使用 LMArena 对战与排位系统！🎉 这是一个专为 [LMArena.ai](https://lmarena.ai/) 设计的高性能工具集，允许您通过简单的指令驱动一个完整的模型对战、评分和排位工作流。

本系统基于 FastAPI 和 WebSocket，旨在提供一个稳定、自动化的模型评估与竞技平台。

## ✨ 核心功能

*   **⚔️ 指令驱动的对战流**: 通过在聊天内容中加入简单指令（如`$sA123`, `$B`, `$wA`），即可控制从开始新对战、指定模型回复到标记比赛结果的全过程。
*   **🏆 自动 ELO 排位系统**: 内置标准 ELO 算法，根据每场对战的结果（A胜、B胜、平局、双方皆负）自动更新参战模型的排位分数。
*   **📈 实时排行榜**: 提供一个 API 端点 (`/v1/leaderboard`)，可随时查看所有模型的 ELO 分数、对战次数和实时排名。
*   **🎭 匿名模型对战**: 在对战中，系统会自动随机抽取两个模型作为“助手A”和“助手B”，让您在不知晓具体模型的情况下进行盲测。
*   **📝 会话管理与锁定**: 每个对战会话由唯一的 RPID (Roleplay ID) 追踪。一旦对战结果被提交，该 RPID 将被锁定，防止重复提交或滥用。
*   **🤖 OpenAI 兼容接口**: 所有交互都通过兼容 OpenAI `v1/chat/completions` 的端点进行，方便与现有工具集成。
*   **⚙️ 浏览器自动化**: 配套的油猴脚本 (`LMArenaApiBridge.js`) 负责与后端服务器通信，并在浏览器中执行所有必要操作。

## ⚔️ 对战模式详解 (Battle Mode)

### 工作流程

一场典型的对战包含三个阶段：**开始 (Start)** -> **对战 (Battle)** -> **标记结果 (Outcome)**。

1.  **开始 (Start)**:
    *   您使用`$sA[RPID]`或`$sB[RPID]`指令发起一个新的对战。
    *   服务器会为这个`RPID`在数据库中创建一个新条目，并随机分配两个模型给A和B。
    *   如果`RPID`已存在，服务器会拒绝创建并提示错误。
    *   指令中指定的助手（A或B）会生成第一条回复。

2.  **对战 (Battle)**:
    *   您使用`$A`或`$B`指令，指定由哪个助手生成下一条回复。
    *   服务器会使用与当前`RPID`绑定的模型进行生成。

3.  **标记结果 (Outcome)**:
    *   在您认为对战可以结束时，使用`$wA`, `$wB`, `$tie`, 或`$bad`指令来标记比赛结果。
    *   服务器会将结果记录到数据库，**锁定**该`RPID`，并根据结果**自动更新**双方模型的ELO分数。
    *   服务器会返回一个包含双方真实模型ID的确认信息。

### 指令集

通过在用户消息**句首**添加指令来控制流程。服务器会自动解析并移除这些指令，确保发送给模型的只有纯净的用户输入。

**1. Start 指令 (开始新会话)**

*   `$startA[RPID]` 或 `$sA[RPID]`
    *   **作用**: 开始一个新会话，`RPID`为指定ID，并让**助手A**先手。
    *   **示例**: `$sA123 你好，我们来一场对决吧！`
*   `$startB[RPID]` 或 `$sB[RPID]`
    *   **作用**: 开始一个新会话，`RPID`为指定ID，并让**助手B**先手。
    *   **示例**: `$sBduel_alpha 讲个故事`

**2. Battle 指令 (在当前会话中继续)**

*   `$battleA` 或 `$A`
    *   **作用**: 在当前`RPID`的会话中，指定由**助手A**生成下一条回复。
*   `$battleB` 或 `$B`
    *   **作用**: 在当前`RPID`的会话中，指定由**助手B**生成下一条回复。

**3. Outcome 指令 (标记结果并结束会话)**

*   `$winA` 或 `$wA`
    *   **作用**: 标记**助手A**获胜。
*   `$winB` 或 `$wB`
    *   **作用**: 标记**助手B**获胜。
*   `$tie`
    *   **作用**: 标记平局。
*   `$bad`
    *   **作用**: 标记双方表现均不佳。

### API 请求体 (`extra_body`)

这些指令需要被客户端转换为注入到OpenAI请求体`extra_body`中的字段。

| 指令 | 注入字段 | 示例值 |
| :--- | :--- | :--- |
| `$sA123` | `rpid`, `start_models` | `"123"`, `["Assistant A"]` |
| `$B` | `rpid`, `battle_models` | `"[最近的RPID]"`, `["Assistant B"]` |
| `$wA` | `rpid`, `win_models` | `"[最近的RPID]"`, `["Assistant A"]` |
| `$tie` | `rpid`, `win_models` | `"[最近的RPID]"`, `["Assistant A", "Assistant B"]`|
| `$bad` | `rpid`, `win_models` | `"[最近的RPID]"`, `[]` |

**通用字段**: 所有对战模式请求的`extra_body`都必须包含：
*   `"battle_mode_active": true`
*   `"context_type": "battle_simulation"`

## 🛠️ 安装与使用

你需要准备好 Python 环境和一款支持油猴脚本的浏览器 (如 Chrome, Firefox, Edge)。

### 1. 准备工作

*   **安装 Python 依赖**: `pip install -r requirements.txt`
*   **安装油猴脚本管理器**: 为你的浏览器安装 [Tampermonkey](https://www.tampermonkey.net/) 扩展。
*   **安装本项目油猴脚本**: 将 [`TampermonkeyScript/LMArenaApiBridge.js`](TampermonkeyScript/LMArenaApiBridge.js) 的代码复制到 Tampermonkey 编辑器中并保存。

### 2. 运行主程序

1.  **启动本地服务器**: `python api_server.py`
2.  **保持 LMArena 页面开启**: 确保至少有一个 LMArena 页面是打开的，并且油猴脚本已成功连接（页面标题会以 `✅` 开头）。

### 3. 配置会话 ID

这是**最重要**的一步，用于让服务器能与 LMArena 通信。
1.  **确保主服务器正在运行**。
2.  **运行 ID 更新器**: `python id_updater.py`
3.  **激活与捕获**:
    *   浏览器中 LMArena 页面的标题会出现准星图标 (🎯)。
    *   在 LMArena 网站上**任意**一个模型的对话页面，**点击一次重试（Retry）按钮**。
    *   `id_updater.py` 脚本会捕获到所需的 ID 并自动更新 `config.jsonc` 文件。

### 4. 配置你的客户端

将你的客户端或应用的 OpenAI API 地址指向本地服务器：
*   **API Base URL**: `http://127.0.0.1:5102/v1`
*   **API Key**: 可选，在 `config.jsonc` 中配置。

### 5. 开始对战！ 💬

现在你可以通过发送带指令的消息来开始你的模型对战和评分了！

## 📖 API 端点

*   `POST /v1/chat/completions`: **核心对战端点**。所有对战指令都通过此端点发送。
*   `GET /v1/leaderboard`: **排行榜端点**。返回所有模型的 ELO 分数排名。
*   `GET /v1/models`: 返回 `models.json` 中定义的模型列表。

## 📂 文件结构

```
.
├── api_server.py               # 核心后端服务 (FastAPI) 🐍
├── battle_db.py                # 对战会话数据库管理器 🤺
├── battle_mode_handler.py      # 对战模式逻辑处理器 ⚔️
├── elo_manager.py              # ELO 分数管理器和排行榜 🏆
├── id_updater.py               # 一键式会话ID更新脚本 🆔
├── config.jsonc                # 全局功能配置文件 ⚙️
├── model_endpoint_map.json     # 定义了可用于对战的模型池 🎯
├── models.json                 # 模型名称到 LMArena 内部 ID 的映射表 🗺️
├── requirements.txt            # Python 依赖包列表 📦
├── README.md                   # 就是你现在正在看的这个文件 👋
└── TampermonkeyScript/
    └── LMArenaApiBridge.js     # 前端自动化油猴脚本 🐵
```

**享受在 LMArena 的模型世界中进行量化评估的乐趣吧！** 💖
