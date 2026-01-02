# 多会话对话系统（类似 ChatGPT）

## 功能特性
- ✅ 多会话管理（创建、切换、删除、重命名）
- ✅ 消息历史持久化存储（MongoDB）
- ✅ 长短期记忆（自动将最近 10 条消息作为上下文）
- ✅ 实时流式响应（SSE）
- ✅ 工具调用记录
- ✅ 会话元数据（消息数、最后更新时间）

## 后端集成步骤

### 1. 安装依赖
```bash
npm install @nestjs/mongoose mongoose
```

### 2. 在 app.module.ts 中导入 ChatModule
```typescript
import { Module } from '@nestjs/common';
import { MongooseModule } from '@nestjs/mongoose';
import { ChatModule } from './chat/chat.module';

@Module({
  imports: [
    MongooseModule.forRoot('mongodb://localhost:27017/your-database'),
    ChatModule,
    // ... 其他模块
  ],
})
export class AppModule {}
```

### 3. 确保 LlmAgentModule 导出 LlmAgentService
在 `src/llm-agent/llm-agent.module.ts` 中：
```typescript
@Module({
  // ...
  exports: [LlmAgentService], // 添加这行
})
export class LlmAgentModule {}
```

## API 端点

### 会话管理
- `POST /api/chat/sessions` - 创建新会话
  ```json
  { "title": "新对话" }
  ```

- `GET /api/chat/sessions` - 获取所有会话列表
  ```
  Query: ?limit=50
  ```

- `GET /api/chat/sessions/:id` - 获取特定会话详情

- `POST /api/chat/sessions/:id` - 更新会话标题
  ```json
  { "title": "更新后的标题" }
  ```

- `DELETE /api/chat/sessions/:id` - 删除会话

### 消息管理
- `GET /api/chat/sessions/:id/messages` - 获取会话消息历史
  ```
  Query: ?limit=100
  ```

- `DELETE /api/chat/sessions/:id/messages` - 清空会话消息

### 对话 SSE 流
- `GET /api/chat/sessions/:id/stream?query=你的问题` - 发送消息并接收 SSE 流

## 前端集成步骤

### 1. 复制组件文件到你的前端项目
```
frontend/
  ├── ChatApp.tsx      # 主应用组件
  ├── SessionList.tsx  # 会话列表侧边栏
  └── ChatView.tsx     # 聊天视图
```

### 2. 在主应用中使用
```typescript
import { ChatApp } from './components/ChatApp';

function App() {
  return <ChatApp />;
}
```

### 3. 配置环境变量
在 `.env` 文件中：
```
VITE_BACK_URL=http://localhost:3000
```

## 数据模型

### Session（会话）
```typescript
{
  _id: string;           // MongoDB ObjectId
  title: string;         // 会话标题
  createdAt: Date;       // 创建时间
  updatedAt: Date;       // 最后更新时间
  messageCount: number;  // 消息数量
  lastMessage: string;   // 最后一条消息预览
  userId?: string;       // 用户ID（可选）
}
```

### Message（消息）
```typescript
{
  _id: string;           // MongoDB ObjectId
  sessionId: string;     // 所属会话ID
  role: 'user' | 'assistant' | 'system';
  content: string;       // 消息内容
  tools?: any[];         // 工具调用记录
  timestamp: Date;       // 时间戳
}
```

## 上下文管理策略

系统会自动：
1. 保存每条用户和 AI 消息到数据库
2. 在新请求时，获取最近 10 条消息作为上下文
3. 将历史上下文格式化后传递给 Agent：
   ```
   以下是之前的对话历史：
   用户: ...
   AI: ...
   
   当前用户问题：...
   ```

## 优化建议

### 1. 性能优化
- 使用 Redis 缓存热门会话
- 实现消息分页加载
- 添加消息搜索功能

### 2. 功能增强
- 添加用户认证系统
- 支持会话分组/标签
- 导出对话历史
- 分享会话链接
- 消息编辑/删除
- 代码块语法高亮
- Markdown 渲染

### 3. 上下文管理优化
- 根据 token 限制动态调整历史消息数量
- 实现对话摘要（summarization）减少 token 消耗
- 支持用户手动标记重要消息（pinned messages）

## 测试

### 创建会话并发送消息
```bash
# 创建新会话
curl -X POST http://localhost:3000/api/chat/sessions \
  -H "Content-Type: application/json" \
  -d '{"title": "测试会话"}'

# 发送消息（SSE）
curl -N "http://localhost:3000/api/chat/sessions/{SESSION_ID}/stream?query=你好"

# 查看消息历史
curl http://localhost:3000/api/chat/sessions/{SESSION_ID}/messages
```

## 故障排查

### 问题：无法创建会话
- 检查 MongoDB 连接是否正常
- 确认 ChatModule 已在 AppModule 中导入

### 问题：消息历史为空
- 检查 sessionId 是否正确
- 确认消息保存时没有错误

### 问题：上下文不生效
- 查看后端日志中构造的 contextQuery
- 确认 getRecentMessages 返回正确的历史消息

## 下一步
- 部署到生产环境时，配置 MongoDB Atlas
- 添加用户认证和权限管理
- 实现实时通知（WebSocket）
- 添加消息反馈机制（点赞/点踩）
