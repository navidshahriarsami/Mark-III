"""
MARK III Brain Server — Configuration

All values read from environment variables with sensible defaults.
Copy .env.example → .env and fill in secrets before production use.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Server
    host:        str  = "0.0.0.0"
    port:        int  = 8000
    debug:       bool = True
    log_level:   str  = "INFO"

    # Security
    device_secret: str = ""

    # Database
    # SQLite local dev:   sqlite+aiosqlite:///./markiii.db
    # PostgreSQL prod:    postgresql+asyncpg://user:pass@localhost:5432/markiii
    database_url: str = "sqlite+aiosqlite:///./markiii.db"

    # Notifications — backend: "log" | "pushover" | "fcm"
    notification_backend:  str = "log"
    pushover_app_token:    str = ""
    pushover_user_key:     str = ""
    fcm_server_key:        str = ""

    # CORS
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:19006"]

    # AI Provider Layer (Phase 9)
    # Preferred provider: "claude" | "openai" | "local"
    ai_preferred_provider: str  = "claude"
    ai_timeout_seconds:    float = 30.0

    # Anthropic (Claude)
    anthropic_api_key: str = ""

    # OpenAI
    openai_api_key: str = ""

    # OpenRouter (Cognitive Council specialist models)
    openrouter_api_key: str = ""

    # Local model (Ollama or compatible)
    local_model_enabled: bool = False
    local_model_url:     str  = "http://localhost:11434"
    local_fast_model:    str  = "llama3.2:3b"
    local_deep_model:    str  = "llama3.2:8b"

    # Voice Core (Phase 11)
    voice_enabled:          bool  = False
    voice_mode:             str   = "push_to_talk"   # push_to_talk | always_listening | sleep | privacy

    # Wake word
    wake_word_engine:       str   = "openwakeword"   # openwakeword | porcupine | none
    wake_words:             list  = ["hey mark", "mark"]
    porcupine_access_key:   str   = ""
    porcupine_keyword_path: str   = ""               # path to .ppn file

    # STT — Faster-Whisper
    stt_engine:             str   = "faster_whisper" # faster_whisper | none
    whisper_model:          str   = "base"           # tiny|base|small|medium|large
    whisper_device:         str   = "cpu"            # cpu | cuda
    whisper_compute_type:   str   = "int8"           # int8 | float16 | float32

    # TTS
    tts_engine:             str   = "piper"          # piper | elevenlabs | none
    piper_binary:           str   = "piper"          # path or name on PATH
    piper_model:            str   = "en_US-amy-medium.onnx"
    piper_model_config:     str   = ""               # auto-derived if empty
    elevenlabs_api_key:     str   = ""
    elevenlabs_voice_id:    str   = "21m00Tcm4TlvDq8ikWAM"  # Rachel

    # Audio hardware
    default_mic_index:      int   = -1               # -1 = system default
    default_speaker_index:  int   = -1
    voice_sample_rate:      int   = 16000
    voice_chunk_ms:         int   = 30               # ms per audio chunk
    voice_silence_db:       float = -40.0            # dBFS below which = silence
    voice_silence_duration: float = 1.5              # seconds of silence → end of utterance
    voice_max_duration:     float = 30.0             # max seconds per utterance
    voice_vad_aggressiveness: int = 2                # WebRTC VAD level 0-3


settings = Settings()
