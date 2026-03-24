# Multi-User Isolation

nanobot supports multi-user isolation within a single instance, providing separate session history, memory, and optional configuration for each user.

## Directory Structure

```
workspace/
├── sessions/                    # Default user sessions (backward compatible)
├── memory/
│   ├── MEMORY.md               # Default user long-term memory
│   └── HISTORY.md              # Default user conversation history
├── users/
│   ├── user_id_1/
│   │   ├── sessions/           # User 1's conversation sessions
│   │   └── memory/
│   │       ├── MEMORY.md       # User 1's long-term memory
│   │       └── HISTORY.md      # User 1's conversation history
│   └── user_id_2/
│       └── ...
└── ...
```

## Configuration

Add user configurations in `config.json`:

```json
{
  "users": {
    "user123": {
      "model": "anthropic/claude-opus-4-5",
      "provider": "anthropic",
      "allow_tools": ["read_file", "web_search", "message"],
      "workspace": null
    },
    "user456": {
      "model": "openai/gpt-4",
      "provider": "openrouter",
      "allow_tools": ["*"]
    }
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `model` | string | User-specific model override |
| `provider` | string | User-specific provider override |
| `allow_tools` | list | Tools the user can access. `["*"]` allows all |
| `workspace` | string | Optional user-specific workspace path |

## How It Works

1. **Session Isolation**: Each user has their own session files stored in `workspace/users/{user_id}/sessions/`

2. **Memory Isolation**: Long-term memory (MEMORY.md) and conversation history (HISTORY.md) are stored per-user

3. **Automatic Routing**: The agent automatically routes messages to the correct user context based on `sender_id` from the channel

4. **Backward Compatibility**: Users not defined in config use the default workspace location

## Channel Integration

Each chat channel provides a `sender_id` that identifies the user:

| Channel | Sender ID Source |
|---------|------------------|
| Telegram | User ID from message |
| Discord | User ID from message |
| WhatsApp | Phone number |
| Feishu | Open ID |
| Slack | User ID |
| Email | Email address |
| QQ | Open ID |
| Matrix | User ID |

## Implementation Details

### Core Components

- **SessionManager**: Manages conversation sessions with user-aware directory paths
- **MemoryStore**: Stores long-term memory with user-specific directories
- **UserContext**: Provides user-specific configuration and resources
- **UserContextManager**: Factory for creating and caching user contexts

### Key Files

- `nanobot/session/manager.py` - Session management with user isolation
- `nanobot/agent/memory.py` - Memory consolidation with user isolation
- `nanobot/user/context.py` - User context management
- `nanobot/config/schema.py` - User configuration schema
- `nanobot/agent/loop.py` - Message processing with user routing

### API Changes

```python
# SessionManager now accepts user_id
session_manager = SessionManager(workspace, user_id="user123")

# MemoryStore now accepts user_id
memory_store = MemoryStore(workspace, user_id="user123")

# UserContextManager for multi-user setups
user_ctx_mgr = UserContextManager(workspace, users_config)
user_context = user_ctx_mgr.get_context("user123")
```

## Migration

Existing installations continue to work without changes. The default user (`_default`) uses the original directory structure:

- Sessions: `workspace/sessions/`
- Memory: `workspace/memory/`

New users automatically get isolated directories under `workspace/users/{user_id}/`.
