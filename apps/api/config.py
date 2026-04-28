# from pydantic_settings import BaseSettings


# class Settings(BaseSettings):
#     openrouter_api_key: str = ""
#     nvidia_api_key: str = ""
#     gemini_api_key: str = ""
#     primary_model: str = "gemini/gemini-2.5-flash"
#     api_port: int = 8001
#     log_level: str = "INFO"
#     app_env: str = "development"
#     cors_origins: str = "*"
#     github_token: str = ""
#     github_default_repo: str = "owner/repo"
#     supabase_url: str = ""
#     supabase_service_role_key: str = ""

#     class Config:
#         env_file = ".env"
#         extra = "ignore"


# settings = Settings()

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    openrouter_api_key: str = ""
    nvidia_api_key: str = ""
    gemini_api_key: str = ""
    primary_model: str = "gemini/gemini-2.5-flash"
    # Railway injects PORT automatically — fallback to 8004 for local dev
    port: int = 8004
    api_port: int = 8004
    log_level: str = "INFO"
    app_env: str = "development"
    # Allow all origins — Forge CDN domains vary, * is safe since auth is via service role key
    cors_origins: str = "*"
    github_token: str = ""
    github_default_repo: str = "owner/repo"
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    groq_api_key: str = ""
    # Shared secret between Forge resolver and Railway backend.
    # Set as FORGETEST_API_SECRET env var on both Railway and Forge.
    forgetest_api_secret: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()