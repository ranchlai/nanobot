# Nanobot Architecture

An ultra-lightweight personal AI assistant built on a pub/sub message bus architecture.

## Design Principles

1. **Minimalism**: Core agent functionality with 99% fewer lines than comparable projects
2. **Decoupling**: Pub/sub message bus separates channels from agent core
3. **Extensibility**: Channel adapters and LLM providers are pluggable
4. **Research-Ready**: Clean, readable code for easy modification and study

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Chat Platforms                                 │
│   Telegram  Discord  Slack  Feishu  WhatsApp  QQ  Matrix  DingTalk  Email  │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Channel Adapters (inbound)                          │
│                      BaseChannel._on_message()                              │
│                      BaseChannel.is_allowed()                               │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Message Bus (Inbound)                             │
│                         asyncio.Queue[InboundMessage]                       │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              AgentLoop                                       │
│     ContextBuilder → LLM Provider → Tool Execution → Session Manager        │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Message Bus (Outbound)                              │
│                        asyncio.Queue[OutboundMessage]                        │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          ChannelManager                                      │
│                    Channel Adapters (outbound)                              │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Chat Platforms                                     │
```

---

## Core Components

### 1. AgentLoop (`nanobot/agent/loop.py`)

The central processing engine that orchestrates:

| Responsibility | Implementation |
|----------------|----------------|
| Message consumption | `bus.consume_inbound()` |
| Context building | `ContextBuilder.build_messages()` |
| LLM interaction | `provider.chat()` |
| Tool execution | `ToolRegistry.execute()` |
| Session persistence | `SessionManager.save()` |
| Memory consolidation | `MemoryConsolidator.check_and_consolidate()` |

**Processing Pipeline:**
```
InboundMessage
    ↓
SessionManager.get_or_create(key)
    ↓
CommandHandler (/new, /stop, /restart, /help)
    ↓
ContextBuilder.build_messages()
    ↓
_run_agent_loop() ← [LLM + Tools loop]
    ↓
SessionManager.save()
    ↓
MemoryConsolidator.check_and_consolidate()
    ↓
OutboundMessage
```

### 2. MessageBus (`nanobot/bus/queue.py`)

Two asynchronous queues providing loose coupling:

| Queue | Direction | Purpose |
|-------|-----------|---------|
| `inbound` | Channels → Agent | Decouple message ingestion from processing |
| `outbound` | Agent → Channels | Decouple response generation from delivery |

```python
class MessageBus:
    inbound: asyncio.Queue[InboundMessage]
    outbound: asyncio.Queue[OutboundMessage]
```

### 3. Channels (`nanobot/channels/`)

Each platform inherits from `BaseChannel`:

| Channel | Protocol | Key Feature |
|---------|----------|-------------|
| Telegram | Long Polling API | Media handling, drafts |
| Discord | Discord Bot API | Thread isolation |
| Slack | Slack Web API | Thread support, rich text |
| Feishu | Feishu Open API | Multimodal files |
| WhatsApp | WhatsApp Business API | Media messages |
| QQ | CQHTTP | Group chats |
| Matrix | Matrix Client-Server API | Media handling |
| DingTalk | DingTalk Callback | Media messages |
| Email | IMAP/SMTP | Email receiving |
| CLI | Stdin/Stdout | Interactive mode |

**BaseChannel Interface:**
```python
class BaseChannel(ABC):
    async def start() -> None      # Begin listening
    async def stop() -> None       # Clean up
    async def send(msg) -> None    # Send response
    def is_allowed(sender_id) -> bool  # Access control
```

### 4. Providers (`nanobot/providers/`)

LLM abstraction layer with a common interface:

```python
class LLMProvider(ABC):
    @property
    def name(self) -> str
    
    @property
    def context_window(self) -> int
    
    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kwargs
    ) -> ChatResponse
```

| Provider | File | Features |
|----------|------|----------|
| OpenAI | `openai.py` | GPT-4, o1, o3, Codex |
| Anthropic | `anthropic.py` | Claude, prompt caching |
| Azure OpenAI | `azure_openai.py` | Azure deployment |
| Google Gemini | `gemini.py` | Gemini 2.0, thinking |
| DeepSeek | `deepseek.py` | Reasoning models |
| Ollama | `ollama.py` | Local models |
| vLLM | `vllm.py` | Local deployment |
| Custom | `custom_provider.py` | OpenAI-compatible |

### 5. Tools (`nanobot/agent/tools/`)

Plugin-based tool system:

```python
class Tool(ABC):
    @property
    def name(self) -> str
    @property
    def description(self) -> str
    @property
    def parameters(self) -> dict  # JSON Schema
    
    async def execute(self, **kwargs) -> str
```

**Built-in Tools:**

| Tool | Purpose |
|------|---------|
| `read_file` | Read file contents |
| `write_file` | Create/overwrite files |
| `edit_file` | Edit with string replacement |
| `list_dir` | List directory contents |
| `shell` | Execute shell commands |
| `web_fetch` | HTTP GET requests |
| `web_search` | Web search |
| `spawn` | Spawn subagents |
| `cron` | Schedule tasks |
| `message` | Send to channels |
| `mcp` | MCP server tools |

### 6. Skills (`nanobot/agent/skills.py`)

Markdown-based capability definitions (SKILL.md):

- **Location**: `workspace/skills/` (user) + `nanobot/skills/` (built-in)
- **Loading**: Progressive (summary at startup, full on demand)
- **Requirements**: CLI binaries, environment variables

### 7. Session Management (`nanobot/session/manager.py`)

```
Session (key: channel:chat_id)
    ├── messages: list[dict]
    ├── metadata: dict
    └── persistence: JSONL in workspace/sessions/
```

**Memory Layers:**
| Layer | Trigger | Purpose |
|-------|---------|---------|
| `MEMORY.md` | ~50% context | Facts & knowledge |
| `HISTORY.md` | ~50% context | Archived history |

---

## Extension Points

### Adding a New Channel

1. Create `nanobot/channels/newplatform.py`
2. Inherit from `BaseChannel`
3. Implement `start()`, `stop()`, `send()`
4. Register in `nanobot/channels/registry.py`

### Adding a New Provider

1. Create `nanobot/providers/newprovider.py`
2. Inherit from `LLMProvider`
3. Implement `chat()` method
4. Register in provider factory

### Adding New Tools

1. Create `nanobot/agent/tools/newtool.py`
2. Inherit from `Tool`
3. Implement `execute()` with JSON schema
4. Register in `AgentLoop.__init__()`

---

## Data Flow Details

### Inbound: Channel → Agent

```
Platform Webhook/Poll
    ↓
ChannelAdapter._on_message()
    ↓
ChannelAdapter.is_allowed(sender_id)
    ↓
ChannelAdapter._handle_message()
    ↓
MessageBus.publish_inbound(InboundMessage)
    ↓
AgentLoop.run() [consumes from inbound]
```

### Processing: Agent Loop

```
ContextBuilder.build_messages()
    ├── System prompt (identity, bootstrap)
    ├── Session history
    └── Current message + runtime context

for iteration in range(max_iterations):
    response = await provider.chat(messages, tools)
    
    if response.content:
        return response  # Final answer
    
    for tool_call in response.tool_calls:
        result = await tools.execute(tool_call.name, tool_call.args)
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": result
        })
```

### Outbound: Agent → Channel

```
AgentLoop._process_message()
    ↓
MessageBus.publish_outbound(OutboundMessage)
    ↓
ChannelManager._dispatch_outbound()
    ↓
ChannelAdapter.send(msg)
    ↓
Platform API
```

---

## Configuration Flow

```
config.yaml
    ↓
ConfigLoader (pydantic)
    ↓
┌────────────────────────────────────────────┐
│           Application Bootstrap            │
├────────────────────────────────────────────┤
│  MessageBus                                │
│  ProviderFactory → LLMProvider             │
│  SessionManager                            │
│  ToolRegistry                              │
│  SkillsLoader                              │
│  ChannelManager → [BaseChannel]            │
│  CronService                               │
└────────────────────────────────────────────┘
    ↓
asyncio.gather(agent.run(), channels.start_all())
```

---

## Entry Points

| Mode | Command | Use Case |
|------|---------|----------|
| Gateway | `nanobot gateway` | Full server with all channels |
| Agent | `nanobot agent` | Direct interaction (no channels) |
| CLI | `nanobot` | Interactive CLI chat |

---

## File Structure

```
nanobot/
├── __main__.py              # CLI entry point
├── agent/
│   ├── loop.py              # AgentLoop (core)
│   ├── context.py           # ContextBuilder
│   ├── memory.py            # MemoryConsolidator
│   ├── skills.py           # SkillsLoader
│   ├── subagent.py         # SubagentManager
│   └── tools/              # Tool implementations
│       ├── base.py         # Tool base class
│       ├── registry.py    # ToolRegistry
│       ├── filesystem.py  # File tools
│       ├── shell.py       # Shell execution
│       ├── web.py         # Web tools
│       ├── spawn.py       # Subagent spawning
│       ├── mcp.py         # MCP integration
│       └── ...
├── bus/
│   ├── queue.py            # MessageBus
│   └── events.py          # DTOs
├── channels/
│   ├── base.py            # BaseChannel
│   ├── manager.py         # ChannelManager
│   ├── registry.py        # Channel registry
│   └── [platform].py      # Platform adapters
├── providers/
│   ├── base.py            # LLMProvider
│   ├── registry.py       # Provider registry
│   └── [provider].py      # LLM implementations
├── session/
│   └── manager.py         # Session management
├── config/
│   ├── schema.py          # Config models
│   └── loader.py          # Config loading
├── heartbeat/
│   └── service.py         # Heartbeat service
├── cron/
│   └── service.py         # Cron scheduling
└── user/
    └── context.py         # User context
```

---

## Security Considerations

- **Access Control**: `is_allowed()` per channel (allow list/deny list)
- **Workspace Isolation**: `restrict_to_workspace` option
- **Tool Sandboxing**: Shell execution with configurable restrictions
- **Session Isolation**: Per-channel, per-chat session keys
