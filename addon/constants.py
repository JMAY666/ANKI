# -*- coding: utf-8 -*-

import os

# --- Addon Package Name ---
addon_package_name = "SynapsePro1"
ADDON_DISPLAY_NAME = "SynapsePro"
print(f"Constants: Addon package name set to '{addon_package_name}'.")

ADDON_VERSION = "1.6.0-local"
MIN_ANKI_VERSION = "25.09.4"
MIN_ANKI_POINT_VERSION = 250904

# --- Launcher Constants ---
ADDON_NAME_LAUNCHER = "Launcher_Sidebar" 
ICONS_SUBFOLDER = "media" 

# --- URLs ---
AI_ASSISTANT_URL = "https://synapse-pro.vercel.app/"

# --- Colors & Styling (Launcher) ---
# These values are kept for backwards-compatibility with MockConstants fallbacks
# in launcher_widget.py and other modules.  The canonical source of truth is
# now theme.py – do not add new colour constants here.
try:
    from .theme import LIGHT as _TL, DARK as _TD
    SIDEBAR_BG_COLOR_HEX       = _TL["surface"]
    BUTTON_HOVER_PRESSED_COLOR = _TL["blue"]
    BUTTON_ACTIVE_BG_COLOR     = _TL["blue"]
    DEFAULT_TEXT_COLOR         = _TL["text"]
    TIMER_LABEL_COLOR          = _TL["sep_accent"]
    TIMER_BUTTON_HOVER_COLOR   = _TL["grey_mid"]
    TIMER_BUTTON_PRESSED_COLOR = _TL["grey_dark"]
    SEPARATOR_LINE_COLOR       = _TL["sep_accent"]
except Exception:
    # Fallback values when theme.py is not yet available
    SIDEBAR_BG_COLOR_HEX       = "#FFFFFF"
    BUTTON_HOVER_PRESSED_COLOR = "#0071D3"
    BUTTON_ACTIVE_BG_COLOR     = "#0071D3"
    DEFAULT_TEXT_COLOR         = "#1D1D1F"
    TIMER_LABEL_COLOR          = "#888888"
    TIMER_BUTTON_HOVER_COLOR   = "#D0D0D0"
    TIMER_BUTTON_PRESSED_COLOR = "#B0B0B0"
    SEPARATOR_LINE_COLOR       = "#888888"

# --- Sizes & Layout (Launcher) ---
BUTTON_ICON_SIZE = 30
SIDEBAR_WIDTH = 55
BUTTON_BORDER_RADIUS = 8
TIMER_BUTTON_ICON_SIZE = 18
INFO_IMAGE_WIDTH = 200
INFO_IMAGE_FILENAME = "news-banner.png"

# Sidebar tools that can receive a user-defined keyboard shortcut.  The keys
# deliberately match their existing enable/disable setting so one persisted
# map can drive both the settings UI and the runtime registrations.
SIDEBAR_SHORTCUT_KEYS = (
    "gamification_sidebar_enabled",
    "music_player_enabled",
    "pomodoro_enabled",
    "ai_assistant_enabled",
)

# --- Filenames & Object Names (Launcher & Submodules) ---
LOGO_FILENAME = "logo.svg"
MUSIC_ICON_FILENAME = "music.svg"

AI_ASSISTANT_DOCK_OBJECT_NAME = "AIAssistantSidebarDock_Integrated_v1"

AI_TOOL_ICON_FILENAME = "ai_tool.svg"
GAME_ICON_FILENAME = "game.svg"
STUDY_PLAN_ICON_FILENAME = "study_plan.svg"; TIMER_ICON_FILENAME = "timer.svg"
START_ICON_FILENAME = "start.svg"; PAUSE_ICON_FILENAME = "pause.svg"
RESET_ICON_FILENAME = "reset.svg"; SKIP_ICON_FILENAME = "skip.svg"

# --- Background Music Constants ---
ADDON_NAME_MUSIC = "Background_Music"
MUSIC_FILES = [
    "alpha_waves.mp3", "beta_waves.mp3", "library_sounds.mp3",
    "jazz.mp3", "rain.mp3", "cozy.mp3",
]

# --- Pomodoro Constants ---
ADDON_NAME_POMODORO = "Pomodoro_Integrated"
CONFIG_KEY_POMODORO = f"addon_{ADDON_NAME_POMODORO}_config"
CONFIG_KEY_POMODORO_STATS = f"addon_{ADDON_NAME_POMODORO}_stats"
DEFAULT_POMODORO_CONFIG = { "work_minutes": 25, "short_break_minutes": 5, "long_break_minutes": 15, "pomodoros_before_long_break": 4, "sound_work_end": "bells.wav", "sound_break_end": "type.wav", "auto_start_next": False }
DEFAULT_POMODORO_STATS = { "total_pomodoros": 0, "total_focus_minutes": 0, "best_streak": 0, "daily_data": {} }
STATE_IDLE = 0; STATE_WORK = 1; STATE_SHORT_BREAK = 2; STATE_LONG_BREAK = 3; STATE_PAUSED = 4

# --- AI Assistant Sidebar Constants ---
ADDON_NAME_AI_ASSISTANT = "AI_Assistant_Sidebar"

# --- Color Theme ---
# Stores the user's chosen primary colour-theme for the addon UI.
# Valid values: "ocean" (default), "orchid", "forest", "deluge", "horizon", "dusty", "custom"
CONFIG_KEY_ACTIVE_COLOR_THEME = f"addon_{addon_package_name}_active_color_theme"
DEFAULT_ACTIVE_COLOR_THEME = "ocean"


# --- Set by init at runtime ---
addon_path: str = ""
icons_folder: str = ""
sound_available: bool = False
play_sound_function = lambda x: None
