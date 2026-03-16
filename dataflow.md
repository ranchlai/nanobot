# Nanobot Dataflow Architecture

This document describes the data flow architecture of nanobot, an ultra-lightweight personal AI assistant.

## Overview

Nanobot uses a **pub/sub message bus architecture** that decouples chat channels from the agent core:

```
Chat Platforms (Telegram/Discord/Slack/Feishu/WhatsApp/QQ/Matrix/DingTalk/Email)
    ↓
Channel Adapters (receive, validate sender, download media)
    ↓
MessageBus.inbound (asyncio.Queue)
    ↓
AgentLoop (process messages, run LLM + tools)
    ↓
MessageBus.outbound (asyncio.Queue)
    ↓
ChannelManager (dispatch to correct channel)
    ↓
Channel Adapters (send response)
```

---

## 1. Message Flow: Channel → Agent

### 1.1 Channel Adapters (`nanobot/channels/`)

Each chat platform has its own adapter inheriting from `BaseChannel`:

| Channel | File | Protocol |
|---------|------|----------|
| Telegram | `channels/telegram.py` | Long Polling API |
| Discord | `channels/discord.py` | Discord Bot API |
| Slack | `channels/slack.py` | Slack Web API |
| Feishu | `channels/feishu.py` | Feishu Open API |
| WhatsApp | `channels/whatsapp.py` | WhatsApp Business API |
| QQ | `channels/qq.py` | CQHTTP |
| Matrix | `channels/matrix.py` | Matrix Client-Server API |
| DingTalk | `channels/dingtalk.py` | DingTalk Callback |
| Email | `channels/email.py` | IMAP/SMTP |
| CLI | `channels/cli.py` | Stdin/Stdout |

**BaseChannel Key Methods:**
- `_on_message()` - Entry point for incoming messages
- `is_allowed()` - Validate sender permissions
- `_handle_message()` - Publish to message bus
- `send()` - Send response to user

### 1.2 InboundMessage DTO (`nanobot/bus/events.py`)

```python
@dataclass
class InboundMessage:
    channel: str           # telegram, discord, slack, etc.
    sender_id: str         # User identifier
    chat_id: str          # Chat/channel identifier
    content: str          # Message text
    media: list[str]      # Media URLs
    metadata: dict        # Channel-specific data (reply_to, thread_id, etc.)
    session_key_override: str | None  # For thread-scoped sessions
```

### 1.3 MessageBus (`nanobot/bus/queue.py`)

```python
class MessageBus:
    def __init__(self):
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()
    
    async def publish_inbound(self, msg: InboundMessage) -> None
    async def consume_inbound(self) -> InboundMessage
    async def publish_outbound(self, msg: OutboundMessage) -> None
    async def consume_outbound(self) -> OutboundMessage
```

**Two-Queue Design:**
- **Inbound Queue**: Channels → Agent (decouples message ingestion from processing)
- **Outbound Queue**: Agent → Channels (decouples response generation from delivery)

---

## 2. Agent Processing Pipeline

### 2.1 AgentLoop (`nanobot/agent/loop.py`)

The main processing loop runs continuously:

```python
async def run(self) -> None:
    while self._running:
        msg = await asyncio.wait_for(self.bus.consume_inbound(), timeout=1.0)
        asyncio.create_task(self._process_message(msg))
```

### 2.2 Message Processing Pipeline (`_process_message()`)

```
┌─────────────────────────────────────────────────────────────┐
│ 1. Get/Create Session                                      │
│    → SessionManager.get_or_create(key)                     │
│    → Key format: channel:chat_id or channel:chat_id:topic  │
├─────────────────────────────────────────────────────────────┤
│ 2. Handle Slash Commands                                    │
│    → /new - Clear session, start fresh                     │
│    → /stop - Cancel active tasks                           │
│    → /restart - Restart the bot                           │
│    → /help - Show commands                                 │
├─────────────────────────────────────────────────────────────┤
│ 3. Build Context                                            │
│    → ContextBuilder.build_messages()                       │
│      - System prompt (identity, bootstrap files)           │
│      - Session history                                     │
│      - Current user message + runtime context              │
├─────────────────────────────────────────────────────────────┤
│ 4. Run Agent Loop                                           │
│    → _run_agent_loop()                                      │
│      - Send messages to LLM with tool definitions           │
│      - Execute tool calls → add results → continue         │
│      - Return final text response                          │
├─────────────────────────────────────────────────────────────┤
│ 5. Save Session                                             │
│    → _save_turn()                                           │
│      - Truncate large tool results                         │
│      → sessions.save(session)                              │
├─────────────────────────────────────────────────────────────┤
│ 6. Memory Consolidation                                     │
│    → Check if context window filling up                    │
│    → Consolidate to MEMORY.md / HISTORY.md                │
└─────────────────────────────────────────────────────────────┘
```

### 2.3 Agent Loop Iteration (`_run_agent_loop()`)

```python
async def _run_agent_loop(self, messages: list[dict]) -> str:
    for i in range(self.max_iterations):
        # 1. Call LLM with current messages + tools
        response = await self.provider.chat(
            messages=messages,
            tools=self.tools.get_definitions()
        )
        
        # 2. If text response, return as final answer
        if response.content:
            return response.content
        
        # 3. If tool calls, execute each
        for tool_call in response.tool_calls:
            result = await self.tools.execute(tool_call.name, tool_call.args)
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result
            })
        
        # 4. Continue loop with tool results
```

---

## 3. Tools & Skills

### 3.1 Tool Architecture

#### Base Class (`nanobot/agent/tools/base.py`)

```python
class Tool(ABC):
    @property
    @abstractmethod
    def name(self) -> str: pass          # Tool name for function calls
    
    @property
    @abstractmethod
    def description(self) -> str: pass   # What the tool does
    
    @property
    @abstractmethod
    def parameters(self) -> dict: pass    # JSON Schema
    
    @abstractmethod
    async def execute(self, **kwargs) -> str: pass
```

#### ToolRegistry (`nanobot/agent/tools/registry.py`)

```python
class ToolRegistry:
    def register(self, tool: Tool) -> None
    def get_definitions(self) -> list[dict]  # OpenAI function format
    async def execute(self, name: str, params: dict) -> str
```

**Tool Execution Flow:**
```
LLM returns tool_calls
    ↓
ToolRegistry.execute(name, params)
    ↓
Cast parameters to match schema types (cast_params)
    ↓
Validate parameters against JSON schema (validate_params)
    ↓
tool.execute(**params)
    ↓
Add error hint if failed: "[Analyze the error above and try a different approach.]"
    ↓
Return result string to LLM
```

#### Parameter Validation (`base.py`)

The base `Tool` class provides:
- `cast_params()` - Type coercion (string→int, string→bool, etc.)
- `validate_params()` - JSON Schema validation with error messages
- `to_schema()` - Convert to OpenAI function calling format

### 3.2 Built-in Tools

| Tool | File | Purpose |
|------|------|---------|
| `read_file` | `tools/filesystem.py` | Read file contents |
| `write_file` | `tools/filesystem.py` | Create/overwrite files |
| `edit_file` | `tools/filesystem.py` | Edit files with exact string replacement |
| `list_dir` | `tools/filesystem.py` | List directory contents |
| `shell` | `tools/shell.py` | Execute shell commands |
| `web_fetch` | `tools/web.py` | HTTP GET requests |
| `web_search` | `tools/web.py` | Web search |
| `spawn` | `tools/spawn.py` | Spawn subagents |
| `cron` | `tools/cron.py` | Manage scheduled tasks |
| `message` | `tools/message.py` | Send messages to channels |
| `mcp` | `tools/mcp.py` | MCP server tool invocation |

### 3.3 MCP Tools (`nanobot/agent/tools/mcp.py`)

Nanobot supports the **Model Context Protocol (MCP)** for dynamic tool discovery:

```
MCP Server
    ↓ (JSON-RPC over SSE or stdio)
MCPClient
    ↓
ToolRegistry
    ↓
AgentLoop
```

### 3.4 Skills System (`nanobot/agent/skills.py`)

Skills are **Markdown files (SKILL.md)** that teach the agent capabilities.

#### Skill Structure:
```
skill_name/
├── SKILL.md    # Skill definition with frontmatter
```

**Frontmatter Example:**
```yaml
---
description: "Extract text from images using OCR"
always: true
metadata: |
  {
    "nanobot": {
      "requires": {
        "bins": ["tesseract"],
        "env": ["OCR_API_KEY"]
      }
    }
  }
---
# Skill content here...
```

#### SkillsLoader Features:

1. **Two Sources:**
   - `workspace/skills/` - User-defined skills
   - `nanobot/skills/` - Built-in skills

2. **Progressive Loading:**
   - Summary provided in system prompt
   - Full content loaded on demand

3. **Requirement Checking:**
   - CLI binaries (`bins`)
   - Environment variables (`env`)

4. **Always-Loaded Skills:**
   - Skills marked `always: true` are loaded at startup

```python
class SkillsLoader:
    def list_skills(self) -> list[dict]          # All available skills
    def load_skill(self, name: str) -> str      # Load specific skill
    def build_skills_summary(self) -> str       # XML summary for prompt
    def get_always_skills(self) -> list[str]     # Always-loaded skills
```

---

## 4. Session Management

### 4.1 Session (`nanobot/session/manager.py`)

```python
@dataclass
class Session:
    key: str                    # channel:chat_id
    messages: list[dict]        # Conversation history
    created_at: datetime
    updated_at: datetime
    metadata: dict
    last_consolidated: int     # Offset for memory consolidation
```

### 4.2 SessionManager

**Key Operations:**
- `get_or_create(key)` - Get existing or create new session
- `save(session)` - Persist to disk
- `get_history(session, max_messages)` - Retrieve history

**Persistence Format:** JSONL in `workspace/sessions/`
```
metadata.json  # Session metadata
session.jsonl  # Message history
```

**History Retrieval:**
- Aligns to user turn boundaries
- Drops orphan tool_results
- Limits to max_messages

### 4.3 Memory Consolidation (`nanobot/agent/memory.py`)

Two-layer long-term memory:

| Layer | File | Purpose |
|-------|------|---------|
| `MEMORY.md` | Facts & knowledge | Summarized facts extracted from conversations |
| `HISTORY.md` | Conversation log | Archived message history |

**Trigger:** When prompt tokens exceed ~50% of context window

---

## 5. Message Flow: Agent → Channel

### 5.1 OutboundMessage DTO

```python
@dataclass
class OutboundMessage:
    channel: str           # Target channel
    chat_id: str          # Target chat
    content: str          # Response text
    reply_to: str | None = None  # Message to reply to
    metadata: dict = field(default_factory=dict)
```

### 5.2 ChannelManager (`nanobot/channels/manager.py`)

```python
async def _dispatch_outbound(self) -> None:
    while True:
        msg = await self.bus.consume_outbound()
        channel = self.channels.get(msg.channel)
        await channel.send(msg)
```

### 5.3 Progress Messages

Tool hints and progress updates use special metadata:
```python
metadata={"_progress": True}  # Enable progress messages
```

Controlled by config:
- `channels.send_tool_hints` - Show tool names being executed
- `channels.send_progress` - Show execution progress

---

## 6. Providers (LLM Abstraction)

### 6.1 Provider Interface (`nanobot/providers/base.py`)

```python
class LLMProvider(ABC):
    @property
    def name(self) -> str: pass
    
    @property
    def context_window(self) -> int: pass
    
    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kwargs
    ) -> ChatResponse: pass
```

### 6.2 Supported Providers

| Provider | File | Notes |
|----------|------|-------|
| OpenAI | `providers/openai.py` | GPT-4, GPT-4o, o1, o3 |
| Anthropic | `providers/anthropic.py` | Claude with prompt caching |
| Azure OpenAI | `providers/azure_openai.py` | Azure deployment |
| Google Gemini | `providers/gemini.py` | Gemini 2.0 with thinking |
| Moonshot | `providers/moonshot.py` | Kimi |
| MiniMax | `providers/minimax.py` | |
| DeepSeek | `providers/deepseek.py` | |
| Ollama | `providers/ollama.py` | Local models |
| vLLM | `providers/vllm.py` | Local deployment |
| OpenAI Compatible | `providers/openai_compatible.py` | Custom endpoints |

---

## 7. Key Classes Summary

| Component | Class | File | Purpose |
|-----------|-------|------|---------|
| **Agent Core** | `AgentLoop` | `agent/loop.py` | Main processing loop |
| **Context** | `ContextBuilder` | `agent/context.py` | Build system prompts |
| **Sessions** | `Session` | `session/manager.py` | Conversation state |
| **Session Mgmt** | `SessionManager` | `session/manager.py` | Session persistence |
| **Memory** | `MemoryConsolidator` | `agent/memory.py` | Long-term memory |
| **Tools** | `Tool` | `tools/base.py` | Tool base class |
| **Tool Registry** | `ToolRegistry` | `tools/registry.py` | Tool management |
| **Skills** | `SkillsLoader` | `skills.py` | Skill loading |
| **Bus** | `MessageBus` | `bus/queue.py` | Async queues |
| **Events** | `InboundMessage` | `bus/events.py` | Message DTOs |
| **Events** | `OutboundMessage` | `bus/events.py` | Response DTOs |
| **Channels** | `BaseChannel` | `channels/base.py` | Channel base |
| **Channel Mgmt** | `ChannelManager` | `channels/manager.py` | Dispatcher |
| **Providers** | `LLMProvider` | `providers/base.py` | LLM abstraction |

---

## 8. Entry Points

### 8.1 Gateway Mode (`nanobot gateway`)

Full server with all channels:

```python
async def main():
    bus = MessageBus()
    provider = create_provider(config)
    sessions = SessionManager(workspace)
    agent = AgentLoop(bus, provider, sessions, tools, skills)
    channels = ChannelManager(bus, config)
    
    await asyncio.gather(
        agent.run(),
        channels.start_all()
    )
```

### 8.2 Agent Mode (`nanobot agent`)

Direct agent interaction (no channels).

### 8.3 CLI Mode (`nanobot`)

Interactive CLI chat.

---

## 9. Configuration Flow

```
config.yaml
    ↓
Config Loader (channels, providers, skills)
    ↓
┌──────────────────────────────────────┐
│     AgentLoop + ToolRegistry        │
│     + ChannelManager                │
└──────────────────────────────────────┘
```

---

## Appendix: Data Flow Diagram (ASCII)

```
┌─────────────────────────────────────────────────────────────────────┐
│                         CHAT PLATFORMS                              │
│   Telegram  Discord  Slack  Feishu  WhatsApp  QQ  Matrix  DingTalk │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      CHANNEL ADAPTERS                               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                  │
│  │   _on_msg   │  │   _on_msg   │  │   _on_msg   │  ...           │
│  │ is_allowed  │  │ is_allowed  │  │ is_allowed  │                  │
│  │ download_    │  │ download_   │  │ download_   │                  │
│  │   media      │  │   media     │  │   media     │                  │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘                  │
└─────────┼────────────────┼────────────────┼─────────────────────────┘
          │                │                │
          │ bus.publish_inbound(msg)        │
          ▼                ▼                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      MESSAGEBUS.INBOUND                             │
│                   asyncio.Queue[InboundMessage]                     │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                    AgentLoop.run() consumes
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      AGENTLOOP._process_message()                   │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │ 1. SessionManager.get_or_create(key)                           │ │
│  │    → Load/create session                                        │ │
│  ├─────────────────────────────────────────────────────────────────┤ │
│  │ 2. Handle Commands (/new, /stop, /restart, /help)              │ │
│  ├─────────────────────────────────────────────────────────────────┤ │
│  │ 3. ContextBuilder.build_messages()                              │ │
│  │    → System prompt + history + current message                  │ │
│  ├─────────────────────────────────────────────────────────────────┤ │
│  │ 4. _run_agent_loop()                                            │ │
│  │    ┌───────────────────────────────────────────────────────────┐│ │
│  │    │ for i in range(max_iterations):                            ││ │
│  │    │   → provider.chat(messages, tools)                         ││ │
│  │    │   → if text: return content                                ││ │
│  │    │   → if tool_calls:                                         ││ │
│  │    │       for tc in tool_calls:                                ││ │
│  │    │           → tools.execute(tc.name, tc.args)                ││ │
│  │    │           → add result to messages                          ││ │
│  │    └───────────────────────────────────────────────────────────┘│ │
│  ├─────────────────────────────────────────────────────────────────┤ │
│  │ 5. sessions.save(session)                                       │ │
│  ├─────────────────────────────────────────────────────────────────┤ │
│  │ 6. MemoryConsolidator.check_and_consolidate()                   │ │
│  │    → Summarize to MEMORY.md / HISTORY.md                       │ │
│  └─────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                    bus.publish_outbound(msg)
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      MESSAGEBUS.OUTBOUND                            │
│                  asyncio.Queue[OutboundMessage]                     │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                  ChannelManager._dispatch_outbound()
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      CHANNELMANAGER                                 │
│         channels.get(msg.channel).send(msg)                        │
└──────────────┬──────────────────────────────────────────────────────┘
               │
     ┌─────────┼─────────┬─────────┬─────────┐
     ▼         ▼         ▼         ▼         ▼
┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐
│ Telegram│ │ Discord │ │ Slack  │ │ Feishu  │ │  ...    │
│   API   │ │   API   │ │  API   │ │  API    │ │         │
└─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘
```
