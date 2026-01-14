# 文件上传完整解决方案

## 📋 项目结构

```
src/
├── common/
│   ├── upload-config.ts          ← 共享上传配置（model 和 data 都用）
│   └── UPLOAD_CONFIG_GUIDE.md    ← 配置说明文档
│
├── data/
│   ├── data.controller.ts        ← 通用数据上传端点
│   ├── data.service.ts           ← 文件管理服务
│   ├── data.module.ts            ← 模块定义
│   ├── types.ts                  ← TypeScript 类型定义
│   ├── FileUploadManager.ts      ← 前端客户端库
│   ├── DATA_UPLOAD_GUIDE.md      ← API 和使用文档
│   └── INTEGRATION_GUIDE.md      ← 集成示例
│
└── model/
    ├── model.controller.ts       ← 模型运行（现已使用共享配置）
    └── ...
```

## 🎯 核心功能

### 1. 通用文件上传 (`/data/upload`)

**用途**：前端上传任意文件，获取临时路径供后续使用

**流程**：
```
前端上传文件 
  ↓
后端接收并保存到 uploads/temp/{sessionId}/
  ↓
返回临时路径给前端
  ↓
前端使用路径进行后续操作（扫描、分析等）
  ↓
完成后手动或自动清理文件
```

**关键特性**：
- ✅ 自动按 sessionId 组织文件
- ✅ 自动处理中文文件名
- ✅ 支持大文件（最大 500MB）
- ✅ 返回相对路径供前端使用
- ✅ 支持批量删除和会话清理

### 2. 模型文件上传 (`/api/model/run`)

**用途**：专用于模型运行任务的文件上传

**改进**：
- 现已使用共享的 `upload-config.ts`
- 代码更简洁，逻辑更统一
- 便于维护和扩展

### 3. 共享上传配置 (`common/upload-config.ts`)

**优势**：
- 消除代码重复
- 统一上传逻辑
- 便于后续新增模块

**使用方式**：
```typescript
// 单文件
FileInterceptor('file', createFileInterceptorConfig({ destination: '...' }))

// 多文件
AnyFilesInterceptor(createAnyFilesInterceptorConfig({ destination: '...' }))
```

## 🔄 前后端交互流程

### 场景：数据扫描流程

```
┌─ 前端 ─────────────────────────────────────────────┐
│                                                     │
│  1. 用户选择文件                                    │
│     ↓                                              │
│  2. 调用 uploadFile(file, sessionId)               │
│     │                                              │
│     │ FormData {file, sessionId}                   │
│     │                                              │
│     ↓                                              │
└──────────────────────────────────────────────────────┘
                    POST /data/upload
                          ↓
┌─ 后端 ─────────────────────────────────────────────┐
│                                                     │
│  DataController.uploadFile()                       │
│     ↓                                              │
│  使用 createFileInterceptorConfig() 保存文件       │
│     ↓                                              │
│  uploads/temp/session-123/data-123456.csv          │
│     ↓                                              │
│  返回: {                                           │
│    success: true,                                  │
│    filePath: "uploads/temp/session-123/..."       │
│  }                                                 │
│                                                     │
└──────────────────────────────────────────────────────┘
                          ↓
                    返回临时路径
                          ↓
┌─ 前端 ─────────────────────────────────────────────┐
│                                                     │
│  3. 获得 filePath 后，启动数据扫描                 │
│     ↓                                              │
│  EventSource("/data-mapping/data-scan?             │
│    filePath=...&sessionId=...")                    │
│     ↓                                              │
│  接收 SSE 流，展示扫描进度                         │
│     ↓                                              │
│  4. 扫描完成，清理文件                            │
│     ↓                                              │
│  DELETE /data/temp/{encodedPath}                   │
│                                                     │
└──────────────────────────────────────────────────────┘
```

## 💻 前端使用示例

### 最简单的方式

```typescript
import { uploadFile } from '@/data/FileUploadManager';

// 上传文件
const filePath = await uploadFile(file, sessionId);

// 使用路径...
// 清理文件...
```

### 完整的方式

```typescript
import { FileUploadManager } from '@/data/FileUploadManager';

const manager = new FileUploadManager('http://localhost:3000', sessionId);

// 上传 + 进度回调
const filePath = await manager.upload(file, {
  onStart: (file) => console.log('开始上传:', file.name),
  onProgress: (percent) => console.log('进度:', percent + '%'),
  onSuccess: (path) => console.log('成功:', path),
  onError: (error) => console.error('失败:', error),
  onComplete: () => console.log('完成'),
});

// 使用文件...

// 清理
await manager.deleteFile(filePath);
// 或清理整个会话
await manager.cleanSession();
```

### 与聊天系统集成

```typescript
class ChatService {
  private uploadManager: FileUploadManager;

  handleUserUploadFile(file: File) {
    // 上传
    const filePath = await this.uploadManager.upload(file);
    
    // 添加消息
    this.addMessage({
      role: 'user',
      type: 'file',
      content: `上传文件: ${file.name}`,
      metadata: { filePath }
    });

    // 启动数据扫描
    this.startDataScan(filePath);
  }

  async cleanup() {
    // 清理所有临时文件
    await this.uploadManager.cleanSession();
  }
}
```

## 📁 文件组织结构

```
项目根目录/
├── src/
│   ├── common/
│   │   └── upload-config.ts
│   ├── data/
│   │   └── *.ts
│   └── model/
│       └── model.controller.ts
│
└── uploads/
    └── temp/                    # 临时文件存储
        ├── session-123/
        │   ├── data-1705239600000-123456789.csv
        │   └── model-1705239610000-987654321.json
        ├── session-456/
        │   └── report-1705239620000-555555555.xlsx
        └── default/
            └── ...

└── model-scripts/
    └── uploads/                # 模型脚本文件
        └── (存储模型运行的文件)
```

## 🔐 安全特性

- ✅ 路径验证：防止目录遍历攻击
- ✅ 文件大小限制：防止磁盘被填满
- ✅ 文件类型验证：可选的 MIME 类型检查
- ✅ 唯一文件名：避免覆盖冲突
- ✅ SessionId 隔离：用户文件互不影响

## 🧹 文件清理策略

### 手动清理
```typescript
// 删除单个文件
await DELETE /data/temp/{encodedFilePath}

// 清理整个会话
await DELETE /data/temp-session/{sessionId}
```

### 自动清理（推荐部署）
```typescript
// 在 app.module.ts 中添加定时任务
@Cron('0 0 * * *') // 每天午夜
async cleanExpiredFiles() {
  await this.dataService.cleanExpiredTempFiles(24 * 60 * 60 * 1000);
}
```

## 📊 API 完整参考

| 方法 | 端点 | 功能 | 响应 |
|------|------|------|------|
| POST | `/data/upload` | 上传文件 | `{success, filePath, fileSize, ...}` |
| DELETE | `/data/temp/{path}` | 删除单个文件 | `{success, message}` |
| DELETE | `/data/temp-session/{sessionId}` | 清理会话文件 | `{success, message}` |

## 🚀 快速开始清单

### 后端
- [x] 创建 `src/data/` 模块（controller, service, module）
- [x] 创建 `src/common/upload-config.ts` 共享配置
- [x] 更新 `app.module.ts` 导入 DataModule
- [x] 更新 `model.controller.ts` 使用共享配置
- [ ] 创建 `uploads/temp` 目录（首次运行自动创建）
- [ ] 配置防火墙和 CORS（如需）
- [ ] 部署定时清理任务（可选）

### 前端
- [ ] 复制 `FileUploadManager.ts` 到前端项目
- [ ] 导入 `FileUploadManager` 或使用 `uploadFile()` 函数
- [ ] 配置后端 API 基础 URL
- [ ] 测试文件上传功能
- [ ] 集成到业务流程（聊天、数据扫描等）

## 📚 相关文档

| 文件 | 说明 |
|------|------|
| `src/data/DATA_UPLOAD_GUIDE.md` | API 详细文档和前端示例 |
| `src/data/INTEGRATION_GUIDE.md` | 与其他模块的集成方案 |
| `src/common/UPLOAD_CONFIG_GUIDE.md` | 共享配置使用说明 |

## 🎓 学习路径

1. **快速上手** → `DATA_UPLOAD_GUIDE.md` 的"快速开始"部分
2. **理解架构** → 本文档的"前后端交互流程"部分
3. **深入集成** → `INTEGRATION_GUIDE.md` 的场景说明
4. **配置定制** → `UPLOAD_CONFIG_GUIDE.md` 的"自定义配置"部分

## ❓ 常见问题

**Q: 为什么要复用上传配置？**  
A: 多个模块都需要上传文件功能，共享配置避免重复代码，便于维护和统一逻辑。

**Q: sessionId 是必需的吗？**  
A: 建议提供，用于组织文件和清理。不提供时默认使用 `'default'`。

**Q: 文件会永久保存吗？**  
A: 不会。临时文件会被自动清理（24小时）或手动删除。

**Q: 支持哪些文件类型？**  
A: 支持所有类型，可在配置中添加 MIME 类型白名单。

**Q: 如何处理大文件（> 1GB）？**  
A: 当前版本支持最大 500MB，大文件建议使用分片上传（未来版本实现）。

## 📞 支持和反馈

- 问题反馈：提交 issue
- 功能建议：提交 PR 或讨论
- 文档更新：维护相应的 .md 文件

---

**版本**: 1.0  
**创建日期**: 2025年1月  
**维护者**: 后端团队  
**最后更新**: 2025年1月14日
