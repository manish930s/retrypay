"""Application configuration and validation using Pydantic Settings."""

from enum import StrEnum

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnvironment(StrEnum):
    """Permitted application deployment environments."""

    TEST = "test"
    DEVELOPMENT = "development"
    DEMO = "demo"


class Settings(BaseSettings):
    """Validated application runtime configuration.

    Enforces critical safety constraints:
    - Never permits Razorpay live keys (keys beginning with 'rzp_live_').
    - Never permits raw webhook payload retention outside of 'test' environment.
    - Default safe mode has all LLM integrations disabled.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # Core Environment
    RETRYPAY_ENV: AppEnvironment = Field(
        default=AppEnvironment.TEST,
        description="Active application runtime environment",
    )
    DEBUG: bool = Field(default=False, description="Enable debug logging and diagnostics")

    # Database
    DATABASE_URL: str = Field(
        default="sqlite+aiosqlite:///./retrypay.db",
        description="Async SQLAlchemy database connection string",
    )

    # Razorpay Integration (Test Mode Only)
    RAZORPAY_PROVIDER_ENABLED: bool = Field(
        default=False,
        description="Enable real external Razorpay Test Mode API calls (default false)",
    )
    RAZORPAY_TEST_MODE_ONLY: bool = Field(
        default=True,
        description="Enforce that only Test Mode is allowed (must always be true)",
    )
    RAZORPAY_KEY_ID: str = Field(
        default="rzp_test_placeholder_key_id",
        description="Razorpay Key ID (must begin with rzp_test_)",
    )
    RAZORPAY_KEY_SECRET: str = Field(
        default="rzp_test_placeholder_secret",
        description="Razorpay Key Secret",
    )
    RAZORPAY_WEBHOOK_SECRET: str = Field(
        default="retrypay_dev_webhook_secret_key_123",
        description="Razorpay Webhook HMAC secret for signature verification",
    )

    # LLM / Gemini Configuration
    LLM_ENABLED: bool = Field(
        default=False,
        description="Enable LLM structured failure diagnosis adapter (default false)",
    )
    LLM_PROVIDER: str = Field(
        default="gemini",
        description="LLM provider identifier (default 'gemini')",
    )
    LLM_MODEL: str = Field(
        default="gemini-3.7-flash",
        description="LLM model identifier",
    )
    LLM_TIMEOUT_SECONDS: int = Field(
        default=5,
        ge=1,
        le=30,
        description="Timeout in seconds for LLM provider requests",
    )
    GEMINI_API_KEY: str | None = Field(
        default=None,
        description="API key for Gemini provider (required only when LLM_ENABLED is true)",
    )

    # Privacy & Safety Flags
    RETRYPAY_RETAIN_RAW_WEBHOOK_PAYLOAD: bool = Field(
        default=False,
        description="Retain raw webhook request payload bytes (strictly test environment only)",
    )

    # Merchant Policy Defaults
    RETRYPAY_POLICY_VERSION: str = Field(
        default="recovery-v1.3",
        description="Active recovery policy version",
    )
    RETRYPAY_MAX_AUTO_RECOVERY_PAISE: int = Field(
        default=1_000_000,
        description="Maximum order amount in paise for automated recovery (₹10,000)",
    )
    RETRYPAY_MAX_MSGS_PER_ORDER: int = Field(
        default=2,
        description="Maximum recovery messages per order",
    )
    RETRYPAY_MAX_MSGS_PER_CUSTOMER_30D: int = Field(
        default=3,
        description="Maximum recovery messages per customer in a rolling 30-day window",
    )
    RETRYPAY_QUIET_HOURS_START: str = Field(
        default="22:00",
        description="Quiet hours start time (HH:MM in merchant timezone)",
    )
    RETRYPAY_QUIET_HOURS_END: str = Field(
        default="08:00",
        description="Quiet hours end time (HH:MM in merchant timezone)",
    )
    RETRYPAY_MERCHANT_TIMEZONE: str = Field(
        default="Asia/Kolkata",
        description="Merchant timezone name for quiet hours evaluation",
    )

    # Reconciliation Configuration
    RETRYPAY_ATTRIBUTION_RECONCILIATION_WINDOW_MINUTES: int = Field(
        default=30,
        ge=1,
        le=1440,
        description="Reconciliation window in minutes for link & payment truth",
    )

    # Cross-Process Database Target Validation
    RETRYPAY_EXPECTED_DATABASE_TARGET: str | None = Field(
        default=None,
        description=(
            "Optional expected database target path. When set, all processes "
            "(API, worker, CLI) validate that their resolved DATABASE_URL "
            "matches this expected target. Prevents cross-process routing mismatches."
        ),
    )

    @field_validator("RAZORPAY_KEY_ID")
    @classmethod
    def validate_razorpay_test_key(cls, value: str) -> str:
        """Reject any live-mode Razorpay key to prevent live payment interactions."""
        if value.startswith("rzp_live_"):
            raise ValueError(
                "CRITICAL SECURITY VIOLATION: Razorpay live keys ('rzp_live_*') are strictly "
                "prohibited. ReTryPay must operate in Razorpay Test Mode ('rzp_test_*') only."
            )
        return value

    @field_validator("RETRYPAY_ENV", mode="before")
    @classmethod
    def validate_environment(cls, value: object) -> AppEnvironment:
        """Ensure the environment is a valid permitted AppEnvironment."""
        if isinstance(value, str):
            val_lower = value.lower().strip()
            if val_lower in [e.value for e in AppEnvironment]:
                return AppEnvironment(val_lower)
        raise ValueError(
            f"Invalid RETRYPAY_ENV '{value}'. Must be one of: {[e.value for e in AppEnvironment]}"
        )

    @model_validator(mode="after")
    def validate_razorpay_safety(self) -> "Settings":
        """Enforce strict Razorpay safety rules."""
        if not self.RAZORPAY_TEST_MODE_ONLY:
            raise ValueError(
                "CRITICAL SAFETY VIOLATION: RAZORPAY_TEST_MODE_ONLY must always be true."
            )
        if self.RAZORPAY_KEY_ID.startswith("rzp_live_"):
            raise ValueError(
                "CRITICAL SECURITY VIOLATION: Razorpay live keys ('rzp_live_*') are strictly "
                "prohibited. ReTryPay must operate in Razorpay Test Mode ('rzp_test_*') only."
            )
        if self.RAZORPAY_PROVIDER_ENABLED and not self.RAZORPAY_KEY_ID.startswith("rzp_test_"):
            raise ValueError(
                "RAZORPAY_KEY_ID must begin with 'rzp_test_' "
                "when RAZORPAY_PROVIDER_ENABLED is true."
            )
        return self

    @model_validator(mode="after")
    def validate_raw_payload_retention_policy(self) -> "Settings":
        """Disallow raw webhook payload retention outside of test environment."""
        if self.RETRYPAY_RETAIN_RAW_WEBHOOK_PAYLOAD and self.RETRYPAY_ENV != AppEnvironment.TEST:
            raise ValueError(
                "CRITICAL PRIVACY VIOLATION: RETRYPAY_RETAIN_RAW_WEBHOOK_PAYLOAD can only be true "
                "when RETRYPAY_ENV=test. Raw payloads must never be retained in other environments."
            )
        return self

    @model_validator(mode="after")
    def validate_llm_configuration(self) -> "Settings":
        """Ensure GEMINI_API_KEY is supplied when LLM_ENABLED is true and provider is gemini."""
        if self.LLM_ENABLED and self.LLM_PROVIDER == "gemini":
            if not self.GEMINI_API_KEY or not self.GEMINI_API_KEY.strip():
                raise ValueError(
                    "GEMINI_API_KEY must be provided when LLM_ENABLED is true and "
                    "LLM_PROVIDER is gemini."
                )
        return self


def get_settings() -> Settings:
    """Load and return validated application settings singleton."""
    return Settings()
