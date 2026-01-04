# 模型运行器 API 参考文档

## 基础信息

**基础 URL**: `http://localhost:3000`

**API 前缀**: `/api/model-runner`

**内容类型**: `application/json`

---

## 接口列表

### 1. 创建并运行模型

#### 请求

```http
POST /api/model-runner/run
Content-Type: application/json
```

#### 请求体

```json
{
  "modelName": "string",
  "stateEvents": {
    "[stateName]": {
      "[eventName]": {
        "name": "string",
        "url": "string (可选)",
        "filePath": "string (可选)",
        "value": "any (可选)"
      }
    }
  }
}
```

#### 参数说明

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| modelName | string | ✅ | 模型名称，必须在 OGMS 系统中存在 |
| stateEvents | object | ✅ | 状态事件数据对象，至少包含一个状态 |
| stateEvents.[stateName] | object | ✅ | 状态名称，如 "run", "preprocessing" 等 |
| stateEvents.[stateName].[eventName] | object | ✅ | 事件名称，如 "Years_zip", "st_year" 等 |
| stateEvents.[stateName].[eventName].name | string | ✅ | 事件的描述性名称（通常是文件名或参数名） |
| stateEvents.[stateName].[eventName].url | string | ❌ | 数据的网络地址 URL |
| stateEvents.[stateName].[eventName].filePath | string | ❌ | 本地文件路径 |
| stateEvents.[stateName].[eventName].value | any | ❌ | 参数值（数字、字符串等） |

**注**: 在 `url`、`filePath` 和 `value` 中至少需要提供一个。

#### 响应

**成功响应** (HTTP 200)

```json
{
  "success": true,
  "message": "模型任务已启动",
  "data": {
    "taskId": "1g8h9i0j1k2l3m4n",
    "scriptPath": "/path/to/model-scripts/python-scripts/1g8h9i0j1k2l3m4n_model.py",
    "message": "模型任务已创建，正在后台执行"
  }
}
```

**失败响应** (HTTP 400)

```json
{
  "success": false,
  "message": "模型名称不能为空"
}
```

#### 错误代码

| 错误信息 | 原因 | 解决方案 |
|---------|------|---------|
| 模型名称不能为空 | modelName 为空 | 提供有效的模型名称 |
| 状态事件数据不能为空 | stateEvents 为空 | 至少添加一个状态和事件 |
| 状态 "xxx" 的事件数据格式不正确 | 事件结构不符合格式 | 检查事件对象结构 |
| 状态 "xxx" 的事件 "yyy" 必须包含 name、url 或 value | 事件缺少必要字段 | 添加至少一个必需字段 |

#### 示例

**cURL**
```bash
curl -X POST http://localhost:3000/api/model-runner/run \
  -H "Content-Type: application/json" \
  -d '{
    "modelName": "UrbanM2M计算模型",
    "stateEvents": {
      "run": {
        "data": {
          "name": "input.zip",
          "url": "http://example.com/input.zip"
        }
      }
    }
  }'
```

**JavaScript Fetch**
```javascript
const response = await fetch('http://localhost:3000/api/model-runner/run', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    modelName: 'UrbanM2M计算模型',
    stateEvents: {
      run: {
        data: {
          name: 'input.zip',
          url: 'http://example.com/input.zip'
        }
      }
    }
  })
});
const result = await response.json();
```

---

### 2. 获取任务状态

#### 请求

```http
GET /api/model-runner/status/:taskId
```

#### 路径参数

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| taskId | string | ✅ | 任务 ID（由创建任务接口返回） |

#### 响应

**成功响应** (HTTP 200)

```json
{
  "success": true,
  "data": {
    "taskId": "1g8h9i0j1k2l3m4n",
    "modelName": "UrbanM2M计算模型",
    "status": "running",
    "createdAt": "2024-01-04T10:30:00.000Z",
    "startedAt": "2024-01-04T10:31:00.000Z",
    "completedAt": null
  }
}
```

**失败响应** (HTTP 400)

```json
{
  "success": false,
  "message": "任务不存在: invalid-task-id"
}
```

#### 状态值说明

| 状态 | 说明 | 可下一步 |
|------|------|---------|
| pending | 待执行，任务已创建但尚未开始 | 继续轮询 |
| running | 运行中，模型正在执行 | 继续轮询 |
| completed | 已完成，模型执行成功 | 获取结果 |
| failed | 已失败，模型执行出错 | 检查错误信息 |

#### 示例

**cURL**
```bash
curl http://localhost:3000/api/model-runner/status/1g8h9i0j1k2l3m4n
```

**JavaScript**
```javascript
const response = await fetch(
  'http://localhost:3000/api/model-runner/status/1g8h9i0j1k2l3m4n'
);
const result = await response.json();
console.log(result.data.status);
```

---

### 3. 获取任务结果

#### 请求

```http
GET /api/model-runner/result/:taskId
```

#### 路径参数

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| taskId | string | ✅ | 任务 ID |

#### 响应

**成功响应** (HTTP 200)

```json
{
  "success": true,
  "data": {
    "taskId": "1g8h9i0j1k2l3m4n",
    "modelName": "UrbanM2M计算模型",
    "status": "completed",
    "result": {
      "output_layer": "/path/to/data/model_uuid/output-layer.tif",
      "statistics": "/path/to/data/model_uuid/statistics.json"
    },
    "completedAt": "2024-01-04T10:45:00.000Z"
  }
}
```

**失败响应 - 任务不存在** (HTTP 400)

```json
{
  "success": false,
  "message": "任务不存在: invalid-task-id"
}
```

**失败响应 - 任务仍在运行** (HTTP 400)

```json
{
  "success": false,
  "message": "任务仍在运行中，状态: running"
}
```

**失败响应 - 任务执行失败** (HTTP 400)

```json
{
  "success": false,
  "message": "任务执行失败: 模型找不到"
}
```

#### 说明

- 仅当任务状态为 `completed` 时可获取结果
- `result` 对象的键值对对应模型的输出事件名称和文件路径
- 文件路径可用于下载或进一步处理输出结果

#### 示例

**cURL**
```bash
curl http://localhost:3000/api/model-runner/result/1g8h9i0j1k2l3m4n
```

**JavaScript**
```javascript
const response = await fetch(
  'http://localhost:3000/api/model-runner/result/1g8h9i0j1k2l3m4n'
);
const { data } = await response.json();
console.log('输出文件:', data.result);
```

---

### 4. 获取任务列表

#### 请求

```http
GET /api/model-runner/tasks
```

#### 查询参数

| 参数名 | 类型 | 必填 | 默认值 | 说明 |
|--------|------|------|--------|------|
| limit | number | ❌ | 50 | 返回的最大任务数 |

#### 响应

**成功响应** (HTTP 200)

```json
{
  "success": true,
  "data": [
    {
      "_id": "mongodb-object-id-1",
      "taskId": "1g8h9i0j1k2l3m4n",
      "modelName": "UrbanM2M计算模型",
      "status": "completed",
      "createdAt": "2024-01-04T10:30:00.000Z",
      "startedAt": "2024-01-04T10:31:00.000Z",
      "completedAt": "2024-01-04T10:45:00.000Z"
    },
    {
      "_id": "mongodb-object-id-2",
      "taskId": "2h8i9j0k1l2m3n4o",
      "modelName": "CustomModel",
      "status": "running",
      "createdAt": "2024-01-04T11:00:00.000Z",
      "startedAt": "2024-01-04T11:01:00.000Z"
    }
  ]
}
```

**失败响应** (HTTP 400)

```json
{
  "success": false,
  "message": "获取任务列表失败"
}
```

#### 说明

- 返回的任务列表按 `createdAt` 降序排列（最新的在前）
- `limit` 参数限制返回的任务数量
- 列表中不包含 `result` 字段，若需结果请使用 `/result/:taskId` 接口

#### 示例

**cURL**
```bash
# 获取最近 20 个任务
curl 'http://localhost:3000/api/model-runner/tasks?limit=20'
```

**JavaScript**
```javascript
const response = await fetch(
  'http://localhost:3000/api/model-runner/tasks?limit=20'
);
const { data } = await response.json();
console.log(`总任务数: ${data.length}`);
data.forEach(task => {
  console.log(`${task.taskId}: ${task.status}`);
});
```

---

## 数据类型定义

### CreateModelRunRequest

```typescript
interface CreateModelRunRequest {
  modelName: string;
  stateEvents: Record<string, Record<string, EventDataDto>>;
}
```

### EventDataDto

```typescript
interface EventDataDto {
  name: string;          // 必填：事件名称
  url?: string;          // 可选：网络地址
  filePath?: string;     // 可选：本地路径
  value?: any;           // 可选：参数值
}
```

### ModelRunRecord

```typescript
interface ModelRunRecord {
  _id: string;                    // MongoDB ID
  taskId: string;                 // 唯一任务标识
  modelName: string;              // 模型名称
  scriptPath: string;             // Python 脚本路径
  stateEvents: object;            // 输入的状态事件数据
  status: 'pending' | 'running' | 'completed' | 'failed';
  result?: Record<string, string>;  // 输出结果
  error?: string;                 // 错误信息
  createdAt: Date;                // 创建时间
  startedAt?: Date;               // 开始时间
  completedAt?: Date;             // 完成时间
}
```

---

## 响应格式标准

所有 API 响应遵循统一格式：

### 成功响应

```json
{
  "success": true,
  "message": "操作消息（可选）",
  "data": {}
}
```

### 失败响应

```json
{
  "success": false,
  "message": "错误描述"
}
```

---

## HTTP 状态码

| 状态码 | 说明 |
|--------|------|
| 200 | 请求成功 |
| 400 | 请求参数错误或业务逻辑错误 |
| 404 | 资源不存在 |
| 500 | 服务器内部错误 |

---

## 速率限制

当前版本暂无速率限制。建议在生产环境中添加：

```
- 单个用户：100 请求/分钟
- 全局：1000 请求/分钟
```

---

## 认证

当前版本不需要认证。生产环境建议添加 JWT 认证。

---

## 完整工作流示例

### JavaScript 完整示例

```javascript
class ModelRunnerClient {
  constructor(baseUrl = 'http://localhost:3000') {
    this.baseUrl = baseUrl;
  }

  async submitModel(modelData) {
    const response = await fetch(`${this.baseUrl}/api/model-runner/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(modelData)
    });
    return response.json();
  }

  async getStatus(taskId) {
    const response = await fetch(
      `${this.baseUrl}/api/model-runner/status/${taskId}`
    );
    return response.json();
  }

  async getResult(taskId) {
    const response = await fetch(
      `${this.baseUrl}/api/model-runner/result/${taskId}`
    );
    return response.json();
  }

  async getTasks(limit = 50) {
    const response = await fetch(
      `${this.baseUrl}/api/model-runner/tasks?limit=${limit}`
    );
    return response.json();
  }

  async waitForCompletion(taskId, maxWaitTime = 7200000) {
    const startTime = Date.now();
    const pollInterval = 2000;

    return new Promise((resolve, reject) => {
      const interval = setInterval(async () => {
        const statusResult = await this.getStatus(taskId);

        if (!statusResult.success) {
          clearInterval(interval);
          reject(new Error(statusResult.message));
          return;
        }

        const { status } = statusResult.data;

        if (status === 'completed') {
          clearInterval(interval);
          const resultResult = await this.getResult(taskId);
          resolve(resultResult.data);
        } else if (status === 'failed') {
          clearInterval(interval);
          reject(new Error('任务执行失败'));
        } else if (Date.now() - startTime > maxWaitTime) {
          clearInterval(interval);
          reject(new Error('任务超时'));
        }
      }, pollInterval);
    });
  }
}

// 使用示例
const client = new ModelRunnerClient();

const modelData = {
  modelName: 'UrbanM2M计算模型',
  stateEvents: {
    run: {
      Years_zip: {
        name: 'sz.zip',
        url: 'http://example.com/sz.zip'
      }
    }
  }
};

client.submitModel(modelData)
  .then(result => {
    console.log('任务ID:', result.data.taskId);
    return client.waitForCompletion(result.data.taskId);
  })
  .then(result => {
    console.log('结果:', result);
  })
  .catch(error => {
    console.error('错误:', error.message);
  });
```

---

## 注意事项

1. **URL 格式**: 确保提供的 URL 格式正确且可访问
2. **模型名称**: 模型名称必须在 OGMS 系统中存在
3. **并发限制**: 建议单个用户同时运行的任务不超过 5 个
4. **超时处理**: 默认超时为 7200 秒（2 小时），可根据需要调整
5. **错误重试**: 建议在网络错误时实现指数退避重试

---

**API 版本**: 1.0.0  
**最后更新**: 2024-01-04
