# 三角匹配系统（Triangle Matching System）- 批量处理模式

## 📋 概述

三角匹配系统实现了 **模型+任务+数据** 的智能对齐机制，通过四个专业Agent协作，确保地理模型的输入数据与任务需求完美匹配。

### 工作模式：批量提交统一对齐

用户上传所有数据文件后，点击按钮触发对齐检查，一次性完成 **Task→Model→Data→Alignment** 的完整流程。

## 🏗️ 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│              用户界面（前端）                                    │
│   1. 输入需求描述                                               │
│   2. 上传所有数据文件                                           │
│   3. 点击"开始对齐"按钮                                         │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
        ┌────────────────────────┐
        │  三角匹配协调器          │
        │ (Batch Processing)     │
        └────────┬───────────────┘
                 │
    ┌────────────┼────────────┬────────────┐
    │            │            │            │
┌───▼───┐   ┌───▼────┐   ┌──▼─────┐  ┌──▼────────┐
│ Task  │   │ Model  │   │  Data  │  │ Alignment │
│ Agent │   │ Agent  │   │ Agent  │  │  Agent    │
└───┬───┘   └───┬────┘   └──┬─────┘  └──┬────────┘
    │           │           │           │
    └───────────┴───────────┴───────────┘
                 │
                 ▼
         ┌───────────────┐
         │  对齐结果       │
         │  - 得分         │
         │  - 建议         │
         │  - 问题列表     │
         └───────────────┘
```

## 🔄 工作流程

### 前端交互流程（Human-in-the-Loop）

```
步骤1: 用户输入需求
  ↓
步骤2: 用户上传所有数据文件（可多个）
  ↓
步骤3: 用户点击"开始对齐"按钮
  ↓
步骤4: 前端调用 POST /api/triangle-matching/execute
  {
    "user_request": "...",
    "file_paths": ["file1.nc", "file2.tif", ...]
  }
  ↓
步骤5: 后端执行（顺序）：
  - Task Agent 解析需求 → Task_spec
  - Model Agent 推荐模型 → Model_contract  
  - Data Agent 批量扫描 → Data_profiles
  - Alignment Agent 对齐 → Alignment_result
  - 生成Go/No-Go决策包
  ↓
步骤6: 返回完整结果给前端，包含：
  - can_run_now: 是否可直接执行
  - go_no_go: "go" / "no-go"
  - blocking_issues: 阻塞问题（必须修）
  - warnings: 警告问题（可继续）
  - minimal_runnable_inputs: 最小可运行输入集
  - mapping_plan_draft: 映射方案草案
  - execution_estimate: 执行耗时预估
  ↓
步骤7: 前端展示对齐结果：
  ┌─────────────────────────────────┐
  │ 如果 can_run_now == true:       │
  │   - 启用"直接执行模型"按钮       │
  │   - 或 "先做映射"按钮（可选）    │
  │                                 │
  │ 如果 can_run_now == false:      │
  │   - 禁用"执行"按钮               │
  │   - 显示阻塞问题列表             │
  │   - 提供"开始映射"按钮           │
  └─────────────────────────────────┘
  ↓
步骤8: 用户选择：
  ┌─ 选择1: 直接执行模型（若无阻塞问题）
  │
  └─ 选择2: 先做数据映射/修复
       ↓
       映射完成后，调用 POST /api/triangle-matching/rescan-data
       {
         "file_paths": ["file1_mapped.nc", "file2_resampled.tif"]
       }
       ↓
       返回前后差异：
       {
         "added_files": [...],
         "changed_files": [{"file_path": "...", "diff": {...}}],
         "unchanged_files": [...]
       }
       ↓
       若差异符合预期，可选择：
       - 再次调用 /execute 做完整对齐确认
       - 直接进入模型执行
```

## 📡 主要API端点

### ⭐ 核心接口

#### 阶段1：解析需求并推荐模型

```http
POST /api/triangle-matching/parse-requirement
Content-Type: application/json

{
  "user_request": "我需要模拟黄河流域2020-2023年的水文过程"
}
```

**响应：**
```json
{
  "status": "success",
  "session_id": "uuid-xxx",
  "task_spec": {
    "Domain": "水文模拟",
    "Spatial_scope": { ... },
    "Temporal_scope": { ... }
  },
  "model_contract": {
    "model_name": "SWAT水文模型",
    "Required_slots": [
      {
        "input_name": "降水",
        "semantic": "日降水量",
        "form": "Raster",
        "spatial": {"crs": "EPSG:4326"},
        "temporal": {"frequency": "daily"}
      },
      ...
    ]
  },
  "required_inputs": [ ... ],
  "message": "任务解析完成，请上传模型所需数据后调用扫描接口"
}
```

**前端处理：**
- 保存 `session_id` 用于阶段2
- 展示 `model_contract` 的 `Required_slots`，告知用户需要上传哪些数据
- 启用文件上传组件

---

#### 阶段2：扫描数据并对齐检查

```http
POST /api/triangle-matching/scan-and-align
Content-Type: application/json

{
  "session_id": "uuid-xxx",
  "file_paths": [
    "uploads/precipitation_2020_2023.nc",
    "uploads/dem_huanghe.tif",
    "uploads/evaporation_2020_2023.csv"
  ]
}
```

**响应：**
```json
{
  "status": "success",
  "session_id": "uuid-xxx",
  "task_spec": {
    "Domain": "水文模拟",
    "Spatial_scope": { ... },
    "Temporal_scope": { ... }
  },
  "model_contract": {
    "model_name": "SWAT水文模型",
    "Required_slots": [ ... ]
  },
  "data_profiles": [
    {
      "file_id": "file_abc123",
      "file_path": "uploads/precipitation.nc",
      "profile": { ... }
    }
  ],
  "alignment_result": {
    "overall_score": 0.85,
    "summary": "数据基本满足模型需求",
    "per_slot": [ ... ],
    "blocking_issues": [ ... ],
    "warnings": [ ... ],
    "recommended_actions": [ ... ],
    "minimal_runnable_inputs": [ ... ],
    "mapping_plan_draft": [ ... ],
    "execution_estimate": {
      "estimated_minutes": 8,
      "required_slot_count": 4,
      "available_input_count": 3
    }
  },
  "alignment_status": "partial",
  "can_run_now": true,
  "go_no_go": "go",
  "recommended_actions": [ ... ],
  "minimal_runnable_inputs": [ ... ],
  "execution_estimate": { ... },
  "completed_at": "2026-03-09T10:30:00"
}
```

### 辅助接口

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/triangle-matching/parse-requirement` | POST | 🔴 阶段1：解析需求并推荐模型 |
| `/api/triangle-matching/scan-and-align` | POST | 🔴 阶段2：扫描数据并对齐检查 |
| `/api/triangle-matching/execute` | POST | 一次性完整流程（向下兼容） |
| `/api/triangle-matching/status/{id}` | GET | 查询对齐状态（含Go/No-Go） |
| `/api/triangle-matching/session/{id}` | GET | 获取完整会话 |
| `/api/triangle-matching/scan-data` | POST | 批量扫描数据（预览） |
| `/api/triangle-matching/rescan-data` | POST | 增量重扫并返回差异 |
| `/api/triangle-matching/run-workflow` | POST | 完整工作流（备用） |
| `/api/triangle-matching/data-profiles` | GET | 获取缓存画像 |

## 🎯 前端集成指南

### 1. 调用时机

**两阶段流程（推荐）：**
- ✅ 阶段1：用户输入需求后立即调用 `/api/triangle-matching/parse-requirement`
- ✅ 阶段2：用户上传完数据后调用 `/api/triangle-matching/scan-and-align`

**一次性流程（向下兼容）：**
- ✅ 用户输入需求+上传数据后调用 `/api/triangle-matching/execute`

### 2. 前端示例代码

```javascript
// 阶段1：用户输入需求后，解析任务并推荐模型
async function handleParseRequirement() {
  setLoading(true);
  
  try {
    const response = await fetch('http://localhost:8000/api/triangle-matching/parse-requirement', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_request: userInput
      })
    });
    
    const result = await response.json();
    
    // 保存session_id用于阶段2
    setSessionId(result.session_id);
    
    // 展示模型需求
    setModelName(result.model_contract.model_name);
    setRequiredInputs(result.model_contract.Required_slots);
    
    // 启用上传组件
    setShowUploadPanel(true);
    showMessage('请上传以下数据文件...');
    
  } catch (error) {
    showError('需求解析失败，请重试');
  } finally {
    setLoading(false);
  }
}

// 阶段2：用户上传完数据后，执行扫描和对齐
async function handleScanAndAlign() {
  setLoading(true);
  
  try {
    const response = await fetch('http://localhost:8000/api/triangle-matching/scan-and-align', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: sessionId,  // 阶段1返回的session_id
        file_paths: uploadedFiles.map(f => f.path)
      })
    });
    
    const result = await response.json();
    
    // 展示对齐结果
    setAlignmentScore(result.alignment_result.overall_score);
    setAlignmentStatus(result.alignment_status);
    setCanRunNow(result.can_run_now);
    setGoNoGo(result.go_no_go);
    setRecommendedActions(result.recommended_actions || []);
    setMinimalInputs(result.minimal_runnable_inputs || []);
    setDataMatching(result.alignment_result.per_slot || []);
    
  } catch (error) {
    showError('对齐检查失败，请重试');
  } finally {
    setLoading(false);
  }
}
```

### 3. UI呈现建议（支持Go/No-Go决策）

```
┌─────────────────────────────────────────┐
│  三角匹配 - 数据对齐检查                  │
├─────────────────────────────────────────┤
│                                         │
│  1. 输入需求描述                         │
│  ┌───────────────────────────────────┐ │
│  │ 我需要模拟黄河流域2020-2023年...   │ │
│  └───────────────────────────────────┘ │
│                                         │
│  2. 上传数据文件                         │
│  ┌───────────────────────────────────┐ │
│  │ [+] 添加文件                       │ │
│  │  ✓ precipitation.nc               │ │
│  │  ✓ dem.tif                        │ │
│  │  ✓ evaporation.csv                │ │
│  └───────────────────────────────────┘ │
│                                         │
│  ┌───────────────┐                     │
│  │ 开始对齐检查   │  ← 点击触发API调用   │
│  └───────────────┘                     │
│                                         │
│  3. 对齐结果                             │
│  ┌───────────────────────────────────┐ │
│  │ Go/No-Go: 🟢 GO (可运行)          │ │
│  │ 对齐得分: ★★★★☆ 0.82             │ │
│  │ 风险等级: 🟡 中等                 │ │
│  │                                   │ │
│  │ ✓ 降水数据：完全匹配               │ │
│  │ ⚠ DEM数据：分辨率不一致            │ │
│  │   建议：重采样到1km (可选修复)     │ │
│  │                                   │ │
│  │ 最小可运行输入集:                  │ │
│  │  • 降水 • DEM • 蒸发              │ │
│  │                                   │ │
│  │ 下一步建议动作:                    │ │
│  │  1. 可先用最小输入集试跑，再迭代   │ │
│  │  2. 修复后调用增量重扫验证变化     │ │
│  └───────────────────────────────────┘ │
│                                         │
│  ┌───────────────┐  ┌───────────────┐ │
│  │ 直接执行模型   │  │ 先做数据映射   │ │
│  └───────────────┘  └───────────────┘ │
└─────────────────────────────────────────┘

♦ 若 Go/No-Go == "no-go" (阻塞问题):
  - "直接执行"按钮灰显禁用
  - 只保留"开始修复"按钮
  - 显示红色阻塞问题列表
```

### 4. 结果字段说明

| 字段 | 类型 | 说明 | 前端展示建议 |
|------|------|------|-------------|
| `overall_score` | 0-1 | 总体得分 | ⭐评级展示 |
| `alignment_status` | string | matched/partial/mismatch | 颜色标记 |
| `summary` | string | 文字总结 | 顶部提示 |
| `per_slot` | array | 每个输入的匹配情况 | 列表展示 |
| `blocking_issues` | array | 阻塞问题（必须先修） | 错误提示 |
| `warnings` | array | 警告问题（可先跑后修） | 告警提示 |
| `can_run_now` | boolean | 当前是否可执行模型 | 主按钮可用态 |
| `go_no_go` | string | go/no-go 决策 | 决策标签 |
| `minimal_runnable_inputs` | array | 最小可运行输入集 | 快速试跑清单 |
| `mapping_plan_draft` | array | 映射方案草案 | 映射配置面板 |
| `recommended_actions` | array | 下一步建议动作 | 操作指引 |
| `execution_estimate` | object | 执行成本预估 | 耗时提示 |

### 5. 状态展示建议

```javascript
// 根据Go/No-Go决策显示不同UI状态
const decisionConfig = {
  'go': { 
    color: 'green', 
    icon: '🟢', 
    text: 'GO (可运行)', 
    enableExecuteButton: true 
  },
  'no-go': { 
    color: 'red', 
    icon: '🔴', 
    text: 'NO-GO (存在阻塞)', 
    enableExecuteButton: false 
  }
};

// 根据对齐状态显示不同颜色和图标
const statusConfig = {
  matched: { color: 'green', icon: '✓', text: '完全匹配' },
  partial: { color: 'yellow', icon: '⚠', text: '部分匹配' },
  mismatch: { color: 'red', icon: '✗', text: '不匹配' },
  pending: { color: 'gray', icon: '○', text: '等待处理' }
};

// 风险等级色彩
const riskLevelConfig = {
  low: { color: 'green', text: '低风险' },
  medium: { color: 'orange', text: '中等风险' },
  high: { color: 'red', text: '高风险' }
};
```

### 6. 修复后增量验证流程

```javascript
// 用户完成映射/修复后，调用增量重扫
async function handleRescanAfterMapping(mappedFilePaths) {
  const response = await fetch('/api/triangle-matching/rescan-data', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ file_paths: mappedFilePaths })
  });
  
  const result = await response.json();
  const rescanResult = result.rescan_result;
  
  // 展示前后差异
  console.log('新增文件:', rescanResult.added_files);
  console.log('变更文件:', rescanResult.changed_files);
  console.log('不变文件:', rescanResult.unchanged_files);
  
  // 若关键字段已修复，可再次执行完整对齐或直接运行
  if (rescanResult.changed_files.length > 0) {
    showDiffPanel(rescanResult.changed_files);
  } else {
    showMessage('数据未变化，建议检查映射配置');
  }
}
```

## 🧪 测试

### 运行测试脚本

```bash
cd intelligent-server
python test_triangle_matching.py
```

### 手动测试（curl）

```bash
# 阶段1：解析需求并推荐模型
curl -X POST http://localhost:8000/api/triangle-matching/parse-requirement \
  -H "Content-Type: application/json" \
  -d '{
    "user_request": "我需要模拟黄河流域2020-2023年的水文过程"
  }'

# 阶段2：扫描数据并对齐（使用阶段1返回的session_id）
curl -X POST http://localhost:8000/api/triangle-matching/scan-and-align \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "YOUR_SESSION_ID",
    "file_paths": [
      "uploads/precipitation.nc",
      "uploads/dem.tif"
    ]
  }'

# 或使用一次性接口（向下兼容）
curl -X POST http://localhost:8000/api/triangle-matching/execute \
  -H "Content-Type: application/json" \
  -d '{
    "user_request": "我需要模拟黄河流域2020-2023年的水文过程",
    "file_paths": [
      "uploads/precipitation.nc",
      "uploads/dem.tif"
    ]
  }'

# 查询状态
curl http://localhost:8000/api/triangle-matching/status/YOUR_SESSION_ID

# 增量重扫（修复映射后，仅重扫变更文件）
curl -X POST http://localhost:8000/api/triangle-matching/rescan-data \
  -H "Content-Type: application/json" \
  -d '{
    "file_paths": [
      "uploads/precipitation_mapped.nc",
      "uploads/dem_resampled.tif"
    ]
  }'
```

## 🚀 快速开始

### 1. 启动服务器

```bash
cd intelligent-server
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 2. 前端集成清单

**V2版核心改动（2026-03-09）**：
- [x] 解析并展示 `can_run_now` 字段，控制执行按钮可用性
- [x] 展示 `go_no_go` 决策状态（🟢 GO / 🔴 NO-GO）
- [x] 分级展示问题：`blocking_issues`（红色）vs `warnings`（黄色）
- [x] 显示 `minimal_runnable_inputs`（最小可运行输入集），支持快速试跑
- [x] 渲染 `mapping_plan_draft`，提供一键开始映射入口
- [x] 显示 `execution_estimate`（预估耗时），辅助用户决策
- [x] 修复后调用 `/api/triangle-matching/rescan-data` 做增量复检
- [x] 可视化前后差异（changed_files 的 before/after 字段）

**基础集成清单（V1）**：
- [ ] 收集用户输入的需求描述
- [ ] 收集所有上传的文件路径
- [ ] 点击按钮触发 `/api/triangle-matching/execute`
- [ ] 展示对齐结果（得分、匹配情况、建议）
- [ ] 处理错误情况

## 📦 依赖

```bash
pip install -r requirements.txt
```

主要依赖：
- FastAPI
- LangGraph
- LangChain  
- Rasterio（地理数据处理）
- GeoPandas
- XArray

**注意**：已移除 `watchdog` 依赖（不再需文件监控）

## 📝 架构优势

### 批量处理模式的优点

✅ **简单直观**：用户一次性提交，一次性获得结果  
✅ **性能更好**：批量处理，减少网络往返  
✅ **易于实现**：前端无需复杂的状态管理  
✅ **容易调试**：清晰的请求-响应模型  
✅ **资源友好**：无需后台监控进程

### Human-in-the-Loop改进（V2新增）

✅ **Go/No-Go决策门控**  
   - 阻塞问题（必须修）vs 警告问题（可继续）自动分级  
   - 前端根据 `can_run_now` 字段控制执行按钮可用性  
   - 避免用户盲目执行导致失败

✅ **最小可运行输入集推荐**  
   - 系统自动计算哪些输入可先试跑验证流程  
   - 支持快速迭代，先通后优化

✅ **映射方案草案自动生成**  
   - 基于对齐结果，输出字段级映射建议（含优先级）  
   - 用户只需确认/微调，无需从零手工配置

✅ **增量重扫+前后差异对比**  
   - 修复后只重扫变更文件，秒级返回结果  
   - 差异可视化（before/after），快速验证修复效果

✅ **执行成本预估**  
   - 预估运行耗时（基于输入槽位数和文件数）  
   - 辅助用户判断是否先做映射优化再执行

### 适用场景

- ✅ 用户在前端界面一次性上传所有数据
- ✅ 数据文件数量适中（通常< 50个）
- ✅ 对齐检查是一次性操作，不需要持续监控
- ✅ 用户希望立即看到完整的对齐结果

## 🔮 未来扩展

- [x] **Go/No-Go决策门控**（已完成）
- [x] **增量重扫+差异对比**（已完成）
- [x] **映射方案草案生成**（已完成）
- [x] **最小可运行输入集推荐**（已完成）
- [ ] 支持数据自动转换（坐标系、格式、分辨率）
- [ ] 增加数据质量评分
- [ ] 支持大文件的进度回调
- [ ] 支持WebSocket实时反馈对齐进度
- [ ] 集成可视化对齐报告

## 📚 相关文档

- [Agent开发指南](README_llm_agent.md)
- [数据扫描Agent文档](agents/data_scan/)
- [API完整参考](../API_REFERENCE.md)

---

## 附录：四大Agent详细说明

### Agent 1: Task Agent

**文件位置**: [agents/task/graph.py](agents/task/graph.py)

**输出示例**:
```json
{
  "Domain": "水文模拟",
  "Target_object": "河流径流量",
  "Spatial_scope": {
    "description": "黄河流域",
    "crs_requirement": "EPSG:4326",
    "spatial_resolution": "1km"
  },
  "Temporal_scope": {
    "start_time": "2020-01-01",
    "end_time": "2023-12-31",
    "temporal_resolution": "日"
  },
  "Resolution_requirements": {
    "spatial": "1km级别",
    "temporal": "日尺度"
  }
}
```

### Agent 2: Model Agent

**文件位置**: [agents/model_recommend/graph.py](agents/model_recommend/graph.py)

**输出示例**:
```json
{
  "model_name": "SWAT水文模型",
  "Required_slots": [
    {
      "input_name": "降水",
      "semantic": "日降水量",
      "form": "Raster",
      "spatial": {"crs": "EPSG:4326"},
      "temporal": {"frequency": "daily"}
    }
  ]
}
```

### Agent 3: Data Agent

**文件位置**: [agents/data_scan/graph.py](agents/data_scan/graph.py)

**输出示例**:
```json
[
  {
    "file_id": "file_abc123",
    "file_path": "uploads/precipitation.nc",
    "profile": {
      "Form": "Raster",
      "Spatial": {
        "crs": "EPSG:4326",
        "extent": [100.5, 32.0, 118.5, 42.0]
      },
      "Temporal": {
        "has_time": true,
        "time_range": ["2020-01-01", "2023-12-31"]
      }
    }
  }
]
```

### Agent 4: Alignment Agent

**文件位置**: [agents/alignment/graph.py](agents/alignment/graph.py)

**输出示例**:
```json
{
  "overall_score": 0.85,
  "summary": "数据基本满足模型需求",
  "dimensions": {
    "semantic": {"score": 0.9, "status": "match"},
    "spatiotemporal": {"score": 0.8, "status": "partial"},
    "spec": {"score": 0.85, "status": "match"}
  },
  "per_slot": [
    {
      "input_name": "降水",
      "overall_status": "match",
      "gaps": []
    }
  ],
  "recommendations": ["建议将DEM重采样到1km"],
  "blocking_issues": []
}
```

## 📄 许可

MIT License
