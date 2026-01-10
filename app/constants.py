# Application constants and configuration values
# Centralizes magic strings and numbers for better maintainability

# Task statuses
class TaskStatus:
    # Task lifecycle states
    QUEUED = "queued"
    RESOLVING = "resolving"
    WAITING_SELECTION = "waiting_selection"
    DOWNLOADING = "downloading"
    READY = "ready"
    DONE = "done"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"
    
    # Statuses that indicate task completion
    COMPLETED_STATUSES = [READY, DONE, COMPLETED]
    
    # Statuses that indicate active processing
    ACTIVE_STATUSES = [DOWNLOADING, WAITING_SELECTION]
    
    # All valid statuses
    ALL_STATUSES = [QUEUED, RESOLVING, WAITING_SELECTION, DOWNLOADING, 
                    READY, DONE, COMPLETED, FAILED, CANCELED]


# File states
class FileState:
    # File processing states
    LISTED = "listed"
    SELECTED = "selected"
    DOWNLOADING = "downloading"
    DONE = "done"
    FAILED = "failed"
    
    # States that indicate file is being processed
    ACTIVE_STATES = [SELECTED, DOWNLOADING]
    
    # States that reserve storage space
    RESERVED_STATES = [LISTED, SELECTED, DOWNLOADING]
    
    # All valid states
    ALL_STATES = [LISTED, SELECTED, DOWNLOADING, DONE, FAILED]


# Task modes
class TaskMode:
    # Task download modes
    AUTO = "auto"
    SELECT = "select"
    
    ALL_MODES = [AUTO, SELECT]


# Source types
class SourceType:
    # Task source types
    MAGNET = "magnet"
    LINK = "link"
    
    ALL_TYPES = [MAGNET, LINK]


# Log levels
class LogLevel:
    # Logging levels
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    PROGRESS = "progress"


# Event types
class EventType:
    # Redis pub/sub event types
    HELLO = "hello"
    STATE = "state"
    FILE_STATE = "file.state"
    FILE_PROGRESS = "file.progress"
    FILE_DONE = "file.done"
    FILE_FAILED = "file.failed"
    FILES_LISTED = "files.listed"


# Limits and thresholds
class Limits:
    # Various limits and thresholds
    # SSE token expiry in seconds (1 hour)
    SSE_TOKEN_EXPIRY = 60 * 60  # 1 hour
    
    # Maximum magnet resolution attempts
    MAX_RESOLVE_ATTEMPTS = 240
    
    # Delay between resolve attempts in seconds
    RESOLVE_POLL_DELAY = 5
    
    # Progress monitor update interval in seconds
    PROGRESS_MONITOR_INTERVAL = 1
    
    # Worker main loop interval in seconds
    WORKER_LOOP_INTERVAL = 2
    
    # SSE heartbeat interval in seconds
    SSE_HEARTBEAT_INTERVAL = 25
    
    # SSE periodic refresh interval in seconds
    SSE_REFRESH_INTERVAL = 5.0
    
    # SSE empty files poll interval in seconds
    SSE_EMPTY_FILES_POLL = 0.5
    
    # Maximum time to aggressively poll for files in seconds
    SSE_MAX_EMPTY_WAIT = 60.0
    
    # Default task list limit
    DEFAULT_TASK_LIMIT = 100
    
    # Maximum request body size (100MB)
    MAX_REQUEST_SIZE = 100 * 1024 * 1024
    
    # Rate limit: requests per minute
    RATE_LIMIT_PER_MINUTE = 60
    
    # Maximum label length
    MAX_LABEL_LENGTH = 500
    
    # Maximum file path length
    MAX_PATH_LENGTH = 4096
    
    # Maximum magnet link length
    MAX_MAGNET_LENGTH = 10000
    
    # Maximum filename length (filesystem standard)
    MAX_FILENAME_LENGTH = 255
    
    # Maximum URL length (HTTP standard)
    MAX_URL_LENGTH = 2048
    
    # Maximum number of sources in multi-source submission
    MAX_SOURCES_PER_SUBMISSION = 10
    
    # Maximum torrent file size (10MB)
    MAX_TORRENT_FILE_SIZE = 10 * 1024 * 1024


# HTTP constants
class HTTPHeaders:
    # Common HTTP headers
    WORKER_KEY = "X-Worker-Key"
    CONTENT_TYPE = "Content-Type"
    CACHE_CONTROL = "Cache-Control"
    CONNECTION = "Connection"
    X_ACCEL_BUFFERING = "X-Accel-Buffering"


# Providers
class Provider:
    # Supported debrid providers
    ALLDEBRID = "alldebrid"
    
    ALL_PROVIDERS = [ALLDEBRID]


# File extensions and patterns
class Patterns:
    # Regex patterns and file extensions
    # Matches BitTorrent info hash in magnet links
    MAGNET_BTIH = r'btih:([0-9A-Fa-f]{40}|[A-Z2-7]{32})'
    
    # UUID format pattern
    UUID_PATTERN = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    
    # Allowed file extensions for downloads (security)
    ALLOWED_EXTENSIONS = {
        '.mkv', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm',  # Video
        '.mp3', '.flac', '.wav', '.aac', '.ogg', '.m4a',  # Audio
        '.zip', '.rar', '.7z', '.tar', '.gz', '.bz2',  # Archives
        '.pdf', '.epub', '.mobi', '.azw3',  # Documents
        '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.svg',  # Images
        '.iso', '.img',  # Disk images
        '.exe', '.dmg', '.apk', '.deb', '.rpm',  # Executables (be careful)
    }
