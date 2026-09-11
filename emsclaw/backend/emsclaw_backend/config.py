import os

from dotenv import load_dotenv
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "local")
    if ENVIRONMENT == "local":
        load_dotenv(".env")

    model_ds_name: str = os.environ.get("DS_MODEL") or "deepseek-chat"
    model_ds_api_key: str = os.environ.get("DS_API_KEY") or ""
    model_ds_base_url: str = os.environ.get("DS_URL") or "https://api.deepseek.com/v1"
    max_tokens: int = int(os.environ.get("MAX_TOKENS", "100000"))
    # 单次 LLM 输出 token 预算硬上限(逐用户 task_settings.max_tokens 可能配到 200000,
    # 一次对话可产生 ~200k 输出 → 计费失控;引擎 get_llm_model 对 max_tokens 钳制到此值)。
    max_output_tokens_cap: int = int(os.environ.get("MAX_OUTPUT_TOKENS_CAP", "32768"))
    context_window: int = int(os.environ.get("CONTEXT_WINDOW", "131072"))

    # Agent 图执行步数上限（LangGraph recursion_limit）。必须显式传给运行时 config：
    # astream_events v2 事件流会绕过图 bound config(deepagents 默认 9999)，直接落回
    # LangGraph 默认 25，主图(Lead 多轮 task 分派)容易撞 GraphRecursionError。
    agent_recursion_limit: int = int(os.environ.get("AGENT_RECURSION_LIMIT", "9999"))

    https_only: bool = os.environ.get("HTTPS_ONLY", "false").lower() == "true"
    session_cookie: str = os.environ.get("SESSION_COOKIE") or "zdtc-agent-session"
    session_max_age: int = int(os.environ.get("SESSION_MAX_AGE", str(3600 * 24 * 7)))

    auth_provider: str = os.environ.get("AUTH_PROVIDER", "local")

    bootstrap_admin_enabled: bool = os.environ.get("BOOTSTRAP_ADMIN_ENABLED", "true").lower() == "true"
    bootstrap_admin_username: str = os.environ.get("BOOTSTRAP_ADMIN_USERNAME", "admin")
    bootstrap_admin_password: str = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD", "admin123")
    bootstrap_admin_fullname: str = os.environ.get("BOOTSTRAP_ADMIN_FULLNAME", "Admin")
    bootstrap_admin_email: str = os.environ.get("BOOTSTRAP_ADMIN_EMAIL", "admin@localhost")
    bootstrap_update_admin_password: bool = os.environ.get("BOOTSTRAP_UPDATE_ADMIN_PASSWORD", "false").lower() == "true"

    postgres_host: str = os.environ.get("POSTGRES_HOST", "localhost")
    postgres_port: int = int(os.environ.get("POSTGRES_PORT", "5432"))
    postgres_db: str = os.environ.get("POSTGRES_DB", "ai_agent")
    postgres_user: str = os.environ.get("POSTGRES_USER", "agentone")
    postgres_password: str = os.environ.get("POSTGRES_PASSWORD", "")

    xelatex_cmd: str = os.environ.get("XELATEX_CMD", "/usr/local/texlive/2025/bin/universal-darwin/xelatex")
    pandoc_cmd: str = os.environ.get("PANDOC_CMD", "/usr/local/bin/pandoc")

    # 沙盒服务（MCP 协议）
    sandbox_mcp_url: str = os.environ.get("SANDBOX_MCP_URL", "http://sandbox:8080/mcp")

    # 任务调度服务调用聊天接口时的 API Key（可选）
    task_service_api_key: str = os.environ.get("TASK_SERVICE_API_KEY", "")
    im_enabled: bool = os.environ.get("IM_ENABLED", "false").lower() == "true"
    im_response_timeout: int = int(os.environ.get("IM_RESPONSE_TIMEOUT", "300"))
    im_max_message_length: int = int(os.environ.get("IM_MAX_MESSAGE_LENGTH", "4000"))

    lark_enabled: bool = os.environ.get("LARK_ENABLED", "false").lower() == "true"
    lark_app_id: str = os.environ.get("LARK_APP_ID", "")
    lark_app_secret: str = os.environ.get("LARK_APP_SECRET", "")

    # Langfuse 可观测性（自托管或云端）。LANGFUSE_ENABLED=false 时彻底关闭，
    # 不会创建 CallbackHandler、不会发起任何上报，Agent 运行零影响。
    langfuse_enabled: bool = os.environ.get("LANGFUSE_ENABLED", "false").lower() == "true"
    langfuse_public_key: str = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    langfuse_secret_key: str = os.environ.get("LANGFUSE_SECRET_KEY", "")
    langfuse_base_url: str = os.environ.get("LANGFUSE_BASE_URL") or os.environ.get("LANGFUSE_HOST", "")

    # Agent 版本：用于 Langfuse trace 按 tag 区分不同版本（改了提示词/skill 后 bump）
    # 默认 0.1 起步；未设置环境变量时用此默认值，保证老部署行为可预测
    agent_version: str = os.environ.get("AGENT_VERSION", "0.1")

    # class Config:
    #     env_prefix = 'APP_'


# 全局配置实例
settings = Settings()
