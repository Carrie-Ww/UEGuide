# Available Tools

This document describes the tools available to nanobot.

## File Operations

### read_file
Read the contents of a file.
```
read_file(path: str) -> str
```

### write_file
Write content to a file (creates parent directories if needed).
```
write_file(path: str, content: str) -> str
```

### edit_file
Edit a file by replacing specific text.
```
edit_file(path: str, old_text: str, new_text: str) -> str
```

### list_dir
List contents of a directory.
```
list_dir(path: str) -> str
```

## Shell Execution

### exec
Execute a shell command and return output.
```
exec(command: str, working_dir: str = None) -> str
```

**Safety Notes:**
- Commands have a configurable timeout (default 60s)
- Dangerous commands are blocked (rm -rf, format, dd, shutdown, etc.)
- Output is truncated at 10,000 characters
- Optional `restrictToWorkspace` config to limit paths

## Web Access

### web_search
Search the web using Brave Search API.
```
web_search(query: str, count: int = 5) -> str
```

Returns search results with titles, URLs, and snippets. Requires `tools.web.search.apiKey` in config.

### web_fetch
Fetch and extract main content from a URL.
```
web_fetch(url: str, extractMode: str = "markdown", maxChars: int = 50000) -> str
```

**Notes:**
- Content is extracted using readability
- Supports markdown or plain text extraction
- Output is truncated at 50,000 characters by default

**UE 智能问答回答优先级**：① 先基于教案（curriculum/）回答；② 教案不足时再结合下方官方学习页；③ 实在没有时再自己回答。  
**UE 官方学习页（第二优先级）**：需补充时用 web_fetch 获取 [Epic 官方 Unreal Engine 学习门户](https://dev.epicgames.com/community/unreal-engine/learning) 最新内容，与教案结合回答。
- URL: `https://dev.epicgames.com/community/unreal-engine/learning`
- Example: `web_fetch(url="https://dev.epicgames.com/community/unreal-engine/learning", extractMode="markdown")`

## Communication

### message
Send a message to the user (used internally).
```
message(content: str, channel: str = None, chat_id: str = None) -> str
```

## Background Tasks

### spawn
Spawn a subagent to handle a task in the background.
```
spawn(task: str, label: str = None) -> str
```

Use for complex or time-consuming tasks that can run independently. The subagent will complete the task and report back when done.

## Scheduled Reminders (Cron)

Use the `exec` tool to create scheduled reminders with `nanobot cron add`:

### Set a recurring reminder
```bash
# Every day at 9am
nanobot cron add --name "morning" --message "Good morning! ☀️" --cron "0 9 * * *"

# Every 2 hours
nanobot cron add --name "water" --message "Drink water! 💧" --every 7200
```

### Set a one-time reminder
```bash
# At a specific time (ISO format)
nanobot cron add --name "meeting" --message "Meeting starts now!" --at "2025-01-31T15:00:00"
```

### Manage reminders
```bash
nanobot cron list              # List all jobs
nanobot cron remove <job_id>   # Remove a job
```

## Heartbeat Task Management

The `HEARTBEAT.md` file in the workspace is checked every 30 minutes.
Use file operations to manage periodic tasks:

### Add a heartbeat task
```python
# Append a new task
edit_file(
    path="HEARTBEAT.md",
    old_text="## Example Tasks",
    new_text="- [ ] New periodic task here\n\n## Example Tasks"
)
```

### Remove a heartbeat task
```python
# Remove a specific task
edit_file(
    path="HEARTBEAT.md",
    old_text="- [ ] Task to remove\n",
    new_text=""
)
```

### Rewrite all tasks
```python
# Replace the entire file
write_file(
    path="HEARTBEAT.md",
    content="# Heartbeat Tasks\n\n- [ ] Task 1\n- [ ] Task 2\n"
)
```

## Curriculum Management (教案管理)

The curriculum management system allows you to manage teaching plans and answer questions based on curriculum content.

### Import Curriculum (导入教案)

Import a curriculum file into the system:
```python
# 1. Read the curriculum file
content = read_file("虚拟现实UE课程某职业技术学院教案表.md")

# 2. Parse and save to curriculum/lessons/
# The system will automatically:
# - Generate a unique lesson ID
# - Save to curriculum/lessons/lesson-{id}.md
# - Update curriculum/index.json with metadata
```

### Query Curriculum (查询教案)

List all curricula:
```python
# Read the index file
index = read_file("curriculum/index.json")
# Parse JSON and display lesson list
```

Search for specific curriculum:
```python
# Search by keywords in index.json
# Match keywords and return relevant lessons
```

### Smart Q&A (智能问答)

Answer questions based on curriculum content:
```python
# 1. Extract keywords from user question
# 2. Match relevant lessons in index.json
# 3. Load lesson content using read_file
# 4. Use lesson content as context for LLM to generate answer
```

**Example workflow:**
- User asks: "UE课程的教学目标是什么？"
- System: Searches index.json → Finds relevant lesson → Reads lesson file → Extracts teaching objectives → Returns answer

### Curriculum Storage Structure

```
workspace/
└── curriculum/
    ├── index.json          # Curriculum index (metadata)
    └── lessons/
        └── lesson-*.md     # Individual lesson files
```

---

## Adding Custom Tools

To add custom tools:
1. Create a class that extends `Tool` in `nanobot/agent/tools/`
2. Implement `name`, `description`, `parameters`, and `execute`
3. Register it in `AgentLoop._register_default_tools()`
