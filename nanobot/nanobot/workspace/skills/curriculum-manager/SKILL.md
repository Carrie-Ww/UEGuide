---
name: curriculum-manager
description: 教案管理和智能问答系统。管理虚拟现实UE课程教案，支持教案导入、查询、更新和基于教案内容的智能问答。
always: true
---

# 教案管理系统

## 功能概述

本技能提供完整的教案管理功能，包括：
- 教案导入和存储
- 教案查询和列表
- 教案更新和删除
- 基于教案内容的智能问答

## 零基础用户接待与解释规范

**主要用户是不懂虚幻引擎的人，通过问答学习。**

- **术语解释**：首次出现专业词（如蓝图、Lumen、PIE、SIE、内容浏览器、关卡、材质、碰撞等）时，用一句话通俗解释再继续。
- **回答结构**：可先给「一句话结论」，再给步骤或细节；若问题较复杂，可分点或分步骤说明。
- **回答优先级（必须遵守）**：① 先基于教案（`curriculum/index.json` + `curriculum/lessons/*.md`）回答；② 教案不足时再结合 [Epic 官方学习页](https://dev.epicgames.com/community/unreal-engine/learning)（`web_fetch` 该 URL）；③ 实在没有时再自己回答，并说明「未在教案/官方页中找到，仅供参考」。
- **鼓励追问**：若用户说「不懂」「再简单点」「下一步呢」，耐心重复或换一种说法，并可主动问「你想先搞懂哪一步？」。

## 教案存储结构

教案存储在 `workspace/curriculum/` 目录下：
```
workspace/
└── curriculum/
    ├── index.json          # 教案索引文件（包含所有教案的元数据）
    └── lessons/
        ├── lesson-001.md   # 具体教案文件
        ├── lesson-002.md
        └── ...
```

## 核心功能

### 1. 导入教案

当用户提供教案文件或内容时：

1. **读取教案内容**：使用 `read_file` 读取教案文件
2. **解析教案信息**：提取课程名称、课时、教学目标、教学内容等
3. **生成教案ID**：基于课程名称和时间戳生成唯一ID
4. **保存教案文件**：保存到 `workspace/curriculum/lessons/lesson-{id}.md`
5. **更新索引**：在 `workspace/curriculum/index.json` 中添加教案元数据

**示例流程**：
```python
# 1. 读取教案文件
content = read_file("虚拟现实UE课程某职业技术学院教案表.md")

# 2. 解析并保存
# 生成ID：基于课程名称
lesson_id = "ue-course-001"
lesson_path = f"workspace/curriculum/lessons/lesson-{lesson_id}.md"

# 3. 保存教案内容
write_file(lesson_path, content)

# 4. 更新索引
index_path = "workspace/curriculum/index.json"
# 读取现有索引
index = read_file(index_path) if file_exists else "{}"
# 解析JSON，添加新教案，写回
```

### 2. 查询教案

**列出所有教案**：
```python
# 读取索引文件
index = read_file("workspace/curriculum/index.json")
# 解析并返回教案列表
```

**查询特定教案**：
```python
# 根据课程名称、ID或关键词搜索
# 读取索引，匹配关键词，返回匹配的教案
```

**读取教案内容**：
```python
# 根据ID读取具体教案文件
lesson_content = read_file(f"workspace/curriculum/lessons/lesson-{id}.md")
```

### 3. 更新教案

```python
# 1. 读取现有教案
# 2. 使用 edit_file 或 write_file 更新内容
# 3. 更新索引中的元数据（如更新时间）
```

### 4. 联网官方学习资源（第二优先级知识源）

仅在**教案不足或未覆盖**时使用 **web_fetch** 获取 Epic 官方学习页，与教案结合回答（不得在未先查教案的情况下仅用此页回答）：

- **URL**：`https://dev.epicgames.com/community/unreal-engine/learning`
- **调用**：`web_fetch(url="https://dev.epicgames.com/community/unreal-engine/learning", extractMode="markdown")`
- 返回的页面正文包含官方教程、课程、学习路径等，与教案内容一起组织答案并引用链接。

### 5. 智能问答（严格按优先级）

回答 UE 相关问题时，**必须按以下顺序**使用知识源：

1. **优先基于教案**：
   - 提取问题关键词（如"教学目标"、"UE"、"课时"、"创建项目"等）
   - 读取 `curriculum/index.json`，根据 `keywords`、`title`、`course` 匹配教案
   - 用 `read_file` 读取匹配的 `curriculum/lessons/lesson-*.md`，将教案内容作为回答的主要依据
   - 若教案已能完整回答问题，则主要基于教案生成回答
2. **教案不足时再结合官方学习页**：
   - 若教案未覆盖或需补充（如最新教程、官方学习路径），调用 `web_fetch(url="https://dev.epicgames.com/community/unreal-engine/learning", extractMode="markdown")`
   - 将拉取到的内容与教案、知识库 `knowledge/ue-course-knowledge.md` 结合后生成回答
3. **实在没有时再自己回答**：
   - 仅当教案与上述网页均无相关内容时，才基于模型自身知识回答
   - 回答中注明「此部分未在教案/官方页中找到，仅供参考」

**问答流程**：
```
用户问题 
  → 提取关键词 → 读取 index.json，匹配教案
  → 读取匹配的教案文件内容（第一优先级）
  → 若需补充：web_fetch( Epic 学习页 )（第二优先级）
  → 将教案（+ 可选官方页 + 知识库）作为上下文生成回答
  → 若仍无内容：再自己回答并说明「未在教案/官方页中找到」
```

**实现示例**：
```python
# 1. 用户问题："UE课程的教学目标是什么？"
# 2. 提取关键词：["UE", "教学目标"]
# 3. 读取索引
index_content = read_file("curriculum/index.json")
# 解析JSON，找到包含"UE"和"教学目标"的教案
# 假设找到 lesson-ue-course-001

# 4. 读取教案内容
lesson_content = read_file("curriculum/lessons/lesson-ue-course-001.md")

# 5. 构建回答（LLM会自动处理）
# 上下文："以下是UE课程的教案内容：[lesson_content]"
# 问题："UE课程的教学目标是什么？"
# LLM会从教案内容中提取教学目标部分并回答
```

**关键词匹配策略**：
- 课程名称匹配（如"UE"、"虚拟现实"）
- 内容关键词匹配（如"教学目标"、"教学内容"、"课时"）
- 章节标题匹配（如"第一章"、"创建项目"）

## 索引文件格式

`workspace/curriculum/index.json` 格式：
```json
{
  "lessons": [
    {
      "id": "ue-course-001",
      "title": "虚拟现实UE课程",
      "course": "虚拟现实UE",
      "hours": 64,
      "created_at": "2026-02-09T10:00:00",
      "updated_at": "2026-02-09T10:00:00",
      "file_path": "lessons/lesson-ue-course-001.md",
      "keywords": ["UE", "虚拟现实", "Unreal Engine"]
    }
  ]
}
```

## 使用示例

### 导入教案
```
用户：导入这个教案文件
助手：
1. 读取教案文件
2. 解析教案信息
3. 保存到 curriculum/lessons/
4. 更新索引
5. 确认导入成功
```

### 查询教案
```
用户：列出所有教案
助手：读取 index.json，展示教案列表

用户：查询UE相关教案
助手：搜索索引中的关键词，返回匹配教案
```

### 智能问答
```
用户：UE课程的教学目标是什么？
助手：
1. 搜索包含"教学目标"的教案
2. 读取教案内容
3. 提取教学目标部分
4. 返回给用户

用户：如何创建UE项目？
助手：
1. 搜索"创建项目"相关内容
2. 读取相关教案章节
3. 基于教案内容回答
```

## 注意事项

1. **教案格式**：支持Markdown格式，保持结构清晰
2. **索引维护**：每次添加/更新/删除教案都要更新索引
3. **关键词提取**：从教案标题和内容中提取关键词，便于搜索
4. **问答准确性**：确保回答基于教案内容，不要编造信息
5. **文件路径**：使用相对路径 `workspace/curriculum/`，不要使用绝对路径

## 工具使用

- `read_file`: 读取教案文件和索引
- `write_file`: 保存教案和更新索引
- `edit_file`: 更新教案内容
- `list_dir`: 列出教案目录
- 记忆系统：可以将常用教案信息存储到 `MEMORY.md` 中
