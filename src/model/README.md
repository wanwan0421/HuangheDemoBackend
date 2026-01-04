# 模型运行器 (Model Runner) 模块

## 概述

`model-runner` 模块是一个后端服务，用于根据前端输入的数据自动生成 Python 脚本，然后调用 `openModel` 执行模型运算。

## 功能特性

- 🎯 自动生成 Python 脚本（类似 `UrbanM2M_SZ.py`）
- 🔄 支持异步后台执行模型
- 📊 任务状态跟踪和结果管理
- 💾 MongoDB 数据持久化
- 🛡️ 完整的数据验证

## 文件结构

```
src/model-runner/
├── model-runner.controller.ts      # 控制器：处理HTTP请求
├── model-runner.service.ts         # 服务：核心业务逻辑
├── model-runner.module.ts          # 模块：依赖注入配置
├── schemas/
│   └── model-run-record.schema.ts  # MongoDB Schema
└── dto/
    └── create-model-run.dto.ts     # 请求数据传输对象
```

## API 接口

### 1. 创建并运行模型

**端点**: `POST /api/model-runner/run`

**请求体**:
```json
{
  "modelName": "UrbanM2M计算模型（用于测试请勿调用）",
  "stateEvents": {
    "run": {
      "Years_zip": {
        "name": "sz.zip",
        "url": "http://geomodeling.njnu.edu.cn/dataTransferServer/data/da686d2b-d0d6-4a8e-9667-f391be9a550c"
      },
      "st_year": {
        "name": "st_year.xml",
        "url": "http://geomodeling.njnu.edu.cn/dataTransferServer/data/ced8a86f-3c9f-413a-9d3e-1e7e205d97a3"
      },
      "first_sim_year": {
        "name": "first_sim_year.xml",
        "url": "http://geomodeling.njnu.edu.cn/dataTransferServer/data/8003c4cf-1d6a-4e10-b3d2-84eee9238cc2"
      },
      "out_len": {
        "name": "out_len.xml",
        "url": "http://geomodeling.njnu.edu.cn/dataTransferServer/data/4711dc5e-769d-44a8-af30-e4cc973f4caf"
      },
      "land_demands": {
        "name": "land_demands.xml",
        "url": "http://geomodeling.njnu.edu.cn/dataTransferServer/data/d363580b-1417-402e-b3cf-1ec60a4a5bf6",
        "value": "1000"
      }
    }
  }
}
```

**响应**:
```json
{
  "success": true,
  "message": "模型任务已启动",
  "data": {
    "taskId": "uuid-1234-5678",
    "scriptPath": "/path/to/uuid-1234-5678_model.py",
    "message": "模型任务已创建，正在后台执行"
  }
}
```

### 2. 获取任务状态

**端点**: `GET /api/model-runner/status/:taskId`

**响应**:
```json
{
  "success": true,
  "data": {
    "taskId": "uuid-1234-5678",
    "modelName": "UrbanM2M计算模型（用于测试请勿调用）",
    "status": "completed",
    "createdAt": "2024-01-04T10:30:00Z",
    "startedAt": "2024-01-04T10:31:00Z",
    "completedAt": "2024-01-04T10:45:00Z"
  }
}
```

### 3. 获取任务结果

**端点**: `GET /api/model-runner/result/:taskId`

**响应**:
```json
{
  "success": true,
  "data": {
    "taskId": "uuid-1234-5678",
    "modelName": "UrbanM2M计算模型（用于测试请勿调用）",
    "status": "completed",
    "result": {
      "output-event-name": "/path/to/output-file.tif",
      "output-event-name-2": "/path/to/output-file-2.tif"
    },
    "completedAt": "2024-01-04T10:45:00Z"
  }
}
```

### 4. 获取所有任务

**端点**: `GET /api/model-runner/tasks`

**响应**:
```json
{
  "success": true,
  "data": [
    {
      "_id": "mongodb-id",
      "taskId": "uuid-1234-5678",
      "modelName": "UrbanM2M计算模型（用于测试请勿调用）",
      "status": "completed",
      "createdAt": "2024-01-04T10:30:00Z",
      "startedAt": "2024-01-04T10:31:00Z",
      "completedAt": "2024-01-04T10:45:00Z"
    }
  ]
}
```

## 数据结构说明

### stateEvents 对象

`stateEvents` 是一个嵌套的对象结构，对应于模型的状态和事件：

```typescript
{
  [stateName: string]: {
    [eventName: string]: {
      name: string;        // 事件名称（通常是文件名或参数名）
      url?: string;        // 数据的网络地址（优先使用）
      filePath?: string;   // 本地文件路径
      value?: any;         // 参数值（用于非文件参数）
    }
  }
}
```

### 使用场景

**场景1**: 数据已上传到云服务器，提供URL
```json
{
  "modelName": "MyModel",
  "stateEvents": {
    "run": {
      "data_file": {
        "name": "data.zip",
        "url": "http://example.com/data.zip"
      }
    }
  }
}
```

**场景2**: 混合使用URL和参数值
```json
{
  "modelName": "MyModel",
  "stateEvents": {
    "run": {
      "input_data": {
        "name": "input.xml",
        "url": "http://example.com/input.xml"
      },
      "parameter": {
        "name": "param",
        "value": "1000"
      }
    }
  }
}
```

## 工作流程

1. **前端提交请求**：用户在前端输入模型信息和数据
2. **验证数据**：后端验证请求数据的完整性
3. **生成脚本**：根据数据生成 Python 脚本（类似 `UrbanM2M_SZ.py`）
4. **创建记录**：在 MongoDB 中创建任务记录
5. **异步执行**：后台执行 Python 脚本
6. **跟踪状态**：记录任务状态变化（pending → running → completed/failed）
7. **保存结果**：保存模型输出结果
8. **前端轮询**：前端轮询获取任务状态和结果

## 生成的 Python 脚本示例

模块会根据请求生成类似以下的 Python 脚本：

```python
import sys
import os
import json

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

try:
    from ogmsServer import openModel

    lists = {
        "run": {
            "Years_zip": {
                "name": "sz.zip",
                "url": "http://geomodeling.njnu.edu.cn/dataTransferServer/data/..."
            },
            "st_year": {
                "name": "st_year.xml",
                "url": "http://geomodeling.njnu.edu.cn/dataTransferServer/data/..."
            }
        }
    }

    taskServer = openModel.OGMSTaskAccess(modelName="UrbanM2M计算模型（用于测试请勿调用）")
    result = taskServer.createTaskWithURL(params_with_url=lists)
    downloadResult = taskServer.downloadAllData()
    print("模型运行完成")
    print(json.dumps(downloadResult))

except ImportError as e:
    print(f"导入模块时出错：{e}")
    ...
```

## 任务状态流转

```
pending (待执行)
   ↓
running (运行中)
   ├→ completed (已完成) ✓
   └→ failed (已失败) ✗
```

## 错误处理

### 常见错误及处理

1. **模型名称不能为空**
   - 确保请求中包含有效的 `modelName`

2. **状态事件数据不能为空**
   - 确保 `stateEvents` 不为空，至少包含一个状态

3. **事件数据格式不正确**
   - 确保每个事件都包含 `name`、`url`、`filePath` 或 `value` 中的至少一个

4. **Python 脚本执行失败**
   - 检查 `ogmsServer` 模块是否正确安装
   - 检查模型名称是否正确
   - 检查数据URL是否可访问

## 扩展建议

1. **文件上传支持**：添加支持直接上传文件而不仅仅是提供URL
2. **模型库管理**：创建模型库接口，让用户选择模型
3. **数据映射**：集成数据映射功能，自动识别数据格式
4. **通知功能**：任务完成时发送邮件或WebSocket通知
5. **进度跟踪**：实时显示模型执行的进度

## 环境配置

确保在 `config.ini` 文件中配置了以下内容（用于 openModel 的调用）：

```ini
[DEFAULT]
username = your_username
portalServer = server_ip
portalPort = port
managerServer = server_ip
managerPort = port
dataServer = server_ip
dataPort = port
mappingServer = server_ip
mappingPort = port
```

## 依赖项

- NestJS
- MongoDB (via Mongoose)
- Python 3.x
- ogmsServer 模块
