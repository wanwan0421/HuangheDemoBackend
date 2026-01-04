# 模型运行器 - 安装和使用指南

## 前提条件

- Node.js 16+
- Python 3.8+
- MongoDB 5.0+
- NestJS 应用已搭建

## 安装步骤

### 1. 模块已包含在项目中

模块文件已经创建在 `src/model-runner` 目录下，包含以下文件：

```
src/model-runner/
├── model-runner.controller.ts       # 控制器
├── model-runner.service.ts          # 服务
├── model-runner.module.ts           # 模块
├── dto/
│   └── create-model-run.dto.ts       # DTO
├── schemas/
│   └── model-run-record.schema.ts    # MongoDB Schema
├── utils/
│   └── task-id.util.ts              # 工具函数
├── README.md                         # 模块文档
└── FRONTEND_INTEGRATION.md           # 前端集成指南
```

### 2. 更新 app.module.ts

已经自动添加了 `ModelRunnerModule` 到 `app.module.ts`，确认如下内容已存在：

```typescript
import { ModelRunnerModule } from './model-runner/model-runner.module';

@Module({
  imports: [
    // ... 其他模块
    ModelRunnerModule
  ],
  // ...
})
export class AppModule { }
```

### 3. 启动应用

```bash
npm run start:dev
```

应用启动后，模型运行器 API 将在以下端点可用：
- `POST /api/model-runner/run` - 创建并运行模型
- `GET /api/model-runner/status/:taskId` - 获取任务状态
- `GET /api/model-runner/result/:taskId` - 获取任务结果
- `GET /api/model-runner/tasks` - 获取所有任务列表

## 快速开始

### 1. 使用 cURL 测试 API

```bash
# 创建并运行模型任务
curl -X POST http://localhost:3000/api/model-runner/run \
  -H "Content-Type: application/json" \
  -d '{
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
        }
      }
    }
  }'

# 响应示例
{
  "success": true,
  "message": "模型任务已启动",
  "data": {
    "taskId": "xyz123abc456",
    "scriptPath": "/path/to/model-scripts/python-scripts/xyz123abc456_model.py",
    "message": "模型任务已创建，正在后台执行"
  }
}

# 获取任务状态
curl http://localhost:3000/api/model-runner/status/xyz123abc456

# 获取任务结果（任务完成后）
curl http://localhost:3000/api/model-runner/result/xyz123abc456

# 获取所有任务
curl http://localhost:3000/api/model-runner/tasks
```

### 2. 使用 Postman 测试

1. 导入 API 端点
2. 创建新请求，选择 `POST`
3. URL: `http://localhost:3000/api/model-runner/run`
4. Headers: `Content-Type: application/json`
5. Body (raw JSON):
```json
{
  "modelName": "UrbanM2M计算模型（用于测试请勿调用）",
  "stateEvents": {
    "run": {
      "Years_zip": {
        "name": "sz.zip",
        "url": "http://geomodeling.njnu.edu.cn/dataTransferServer/data/da686d2b-d0d6-4a8e-9667-f391be9a550c"
      }
    }
  }
}
```
6. 点击 Send 按钮

## 配置说明

### MongoDB 连接

确保在 `.env` 文件中配置了 MongoDB URL：

```env
MONGODB_URI=mongodb://localhost:27017/huanghe-demo
```

### Python 环境配置

确保 Python 在系统 PATH 中可用，或在 `model-runner.service.ts` 中指定 Python 路径：

```typescript
// 修改第 191 行
const python = spawn('python3', [scriptPath], {  // 使用 python3
  cwd: path.dirname(scriptPath),
});
```

### ogmsServer 配置

确保在项目根目录有 `config.ini` 文件，内容示例：

```ini
[DEFAULT]
username = your_username
portalServer = 172.21.252.204
portalPort = 8061
managerServer = 172.21.252.204
managerPort = 8061
dataServer = 172.21.252.204
dataPort = 8061
mappingServer = 172.21.252.204
mappingPort = 8061
```

## 目录结构

生成的 Python 脚本和数据将存储在以下位置：

```
项目根目录/
└── model-scripts/
    ├── python-scripts/
    │   ├── taskid1_model.py
    │   ├── taskid2_model.py
    │   └── ...
    └── data/
        ├── 模型名称_uuid/
        │   ├── output1.tif
        │   └── ...
        └── ...
```

## 数据流程

```
前端表单输入
    ↓
POST /api/model-runner/run
    ↓
验证请求数据
    ↓
生成 Python 脚本
    ↓
创建 MongoDB 记录
    ↓
异步执行 Python 脚本
    ↓
更新任务状态为 'running'
    ↓
执行 openModel
    ↓
下载结果文件
    ↓
更新任务状态为 'completed'
    ↓
前端轮询获取状态和结果
```

## 常见问题

### Q: 如何查看模型执行的详细日志？

A: 检查 NestJS 应用的控制台输出。可以在 `model-runner.service.ts` 中增加日志级别：

```typescript
// 在 logger 调用前修改
this.logger.log(`执行 Python 脚本: ${scriptPath}`);
this.logger.debug(`Python stdout: ${data}`);
```

### Q: 任务超时时间是多少？

A: 默认为 7200 秒（2小时）。可以在 `model-runner.service.ts` 的 `wait4Status` 方法中修改 timeout 参数。

### Q: Python 脚本执行失败怎么办？

A: 检查以下几点：
1. Python 环境是否正确安装
2. `ogmsServer` 模块是否可用
3. `config.ini` 文件是否存在且配置正确
4. 模型名称是否正确
5. 网络连接是否正常

### Q: 如何清理旧的任务记录？

A: 可以通过 MongoDB 删除过期的记录：

```javascript
// 在 MongoDB 中执行
db.modelrunrecords.deleteMany({
  completedAt: {
    $lt: new Date(Date.now() - 30 * 24 * 60 * 60 * 1000)  // 删除30天前的记录
  }
})
```

## 扩展功能

### 1. 添加 WebSocket 实时进度推送

```typescript
// 在 model-runner.gateway.ts
import { WebSocketGateway, WebSocketServer, SubscribeMessage } from '@nestjs/websockets';

@WebSocketGateway()
export class ModelRunnerGateway {
  @WebSocketServer() server;

  @SubscribeMessage('subscribe-task')
  handleSubscribe(client: any, taskId: string) {
    client.join(`task-${taskId}`);
  }
}
```

### 2. 添加文件上传支持

```typescript
// 在 model-runner.controller.ts
@Post('upload')
@UseInterceptors(FileInterceptor('file'))
uploadFile(@UploadedFile() file: Express.Multer.File) {
  // 处理文件上传
}
```

### 3. 添加数据验证模型

```typescript
// 创建 validate-model.service.ts
@Injectable()
export class ValidateModelService {
  validateEventData(eventData: any): boolean {
    // 验证事件数据完整性
  }
}
```

## 性能优化建议

1. **异步处理**：使用消息队列（如 RabbitMQ）处理长时间运行的任务
2. **缓存结果**：使用 Redis 缓存最近的任务结果
3. **并发限制**：限制同时运行的模型数量
4. **数据清理**：定期清理旧的任务记录

## 安全建议

1. **认证授权**：添加 JWT 认证，仅允许授权用户提交任务
2. **输入验证**：使用 `class-validator` 验证所有输入
3. **错误处理**：避免在错误消息中泄露系统信息
4. **速率限制**：限制单个用户的请求频率
5. **文件访问**：限制对生成的 Python 脚本的访问

## 故障排除

### 模块导入错误

如果出现找不到模块的错误，确保：
1. `model-runner` 文件夹在 `src` 目录下
2. `app.module.ts` 中正确导入了 `ModelRunnerModule`
3. 运行 `npm install` 安装所有依赖

### MongoDB 连接失败

确保：
1. MongoDB 服务正在运行
2. `.env` 文件中的 MongoDB URI 正确
3. MongoDB 用户名和密码正确（如果需要）

### Python 脚本执行失败

检查：
1. Python 版本是否满足要求（3.8+）
2. 是否正确配置了 `config.ini`
3. ogmsServer 模块是否正确安装在 Python 环境中

## 联系支持

如有任何问题，请检查以下资源：
- [README.md](./README.md) - 模块详细文档
- [FRONTEND_INTEGRATION.md](./FRONTEND_INTEGRATION.md) - 前端集成指南
- NestJS 官方文档：https://docs.nestjs.com
