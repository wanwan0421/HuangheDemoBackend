# 共享文件上传配置说明

## 概述

项目中多个模块都需要处理文件上传功能，为避免重复代码和维护成本，将文件上传的 multer 配置提取到共享的工具函数中。

## 文件位置

```
src/
├── common/
│   └── upload-config.ts    ← 共享的上传配置工具
├── data/
│   ├── data.controller.ts  ← 使用共享配置
│   └── ...
└── model/
    ├── model.controller.ts ← 使用共享配置
    └── ...
```

## 核心函数

### 1. `createDiskStorageConfig(options)`

创建 diskStorage 配置对象。

**参数：**
```typescript
interface UploadConfigOptions {
  destination: string;        // 上传目录
  maxFileSize?: number;       // 最大文件大小，默认 500MB
  allowedMimeTypes?: string[]; // 允许的 MIME 类型，undefined 表示允许所有
}
```

**特性：**
- 自动创建上传目录
- 自动按 sessionId 组织子目录
- 自动处理中文文件名编码
- 生成唯一文件名避免冲突

### 2. `createFileInterceptorConfig(options)`

创建单文件上传的完整拦截器配置（用于 `@FileInterceptor`）。

**使用示例：**
```typescript
@Post('upload')
@UseInterceptors(
  FileInterceptor('file', createFileInterceptorConfig({
    destination: './uploads/temp',
    maxFileSize: 500 * 1024 * 1024,
  }))
)
async uploadFile(@UploadedFile() file: Express.Multer.File) {
  // ...
}
```

### 3. `createAnyFilesInterceptorConfig(options)`

创建多文件上传的完整拦截器配置（用于 `@AnyFilesInterceptor`）。

**使用示例：**
```typescript
@Post('run')
@UseInterceptors(
  AnyFilesInterceptor(
    createAnyFilesInterceptorConfig({
      destination: './model-scripts/uploads',
    })
  )
)
async runModel(@UploadedFiles() files: Express.Multer.File[]) {
  // ...
}
```

## 实现原理

### 自动 SessionId 组织

```typescript
// 上传目录结构
destination/
├── session-123/
│   ├── file1.csv
│   └── file2.json
├── session-456/
│   └── file3.xlsx
└── default/
    └── file4.txt
```

SessionId 的获取顺序：
1. `req.body?.sessionId` (Form 数据)
2. `req.query?.sessionId` (URL 查询参数)
3. 默认值 `'default'`

### 中文文件名处理

```typescript
// 解决 multer 默认的 latin1 编码问题
const originalName = Buffer.from(file.originalname, 'latin1').toString('utf8');
// "æ°æ®.csv" → "数据.csv"
```

### 唯一文件名生成

```typescript
// 格式: {原始文件名}-{时间戳}-{随机数}.{扩展名}
// 例如: data-1705239600000-123456789.csv
```

## 使用对比

### 之前（重复代码）

```typescript
// model.controller.ts
const UPLOAD_DIR = './model-scripts/uploads';
if (!fs.existsSync(UPLOAD_DIR)) {
  fs.mkdirSync(UPLOAD_DIR, { recursive: true });
}

@UseInterceptors(AnyFilesInterceptor({
  storage: diskStorage({
    destination: UPLOAD_DIR,
    filename: (req, file, cb) => {
      file.originalname = Buffer.from(file.originalname, 'latin1').toString('utf8');
      const uniqueSuffix = Date.now() + '-' + Math.round(Math.random() * 1E9);
      cb(null, uniqueSuffix + '-' + file.originalname);
    },
  })
}))

// data.controller.ts
// ... 几乎相同的代码 ...
```

### 之后（复用配置）

```typescript
// model.controller.ts
@UseInterceptors(
  AnyFilesInterceptor(
    createAnyFilesInterceptorConfig({
      destination: './model-scripts/uploads',
    })
  )
)

// data.controller.ts
@UseInterceptors(
  FileInterceptor('file', createFileInterceptorConfig({
    destination: './uploads/temp',
  }))
)
```

## 优势

✅ **代码复用** - 减少重复代码  
✅ **一致性** - 所有模块使用相同的上传逻辑  
✅ **可维护性** - 修改上传逻辑只需改一处  
✅ **易于扩展** - 新增上传功能只需创建新配置  
✅ **自动化** - 自动处理中文文件名、sessionId 组织等  

## 添加新的上传端点

```typescript
import { createFileInterceptorConfig } from '../common/upload-config';

@Controller('documents')
export class DocumentController {
  @Post('upload')
  @UseInterceptors(
    FileInterceptor('document', createFileInterceptorConfig({
      destination: './uploads/documents',
      maxFileSize: 100 * 1024 * 1024, // 100MB
      allowedMimeTypes: ['application/pdf', 'image/png', 'image/jpeg'],
    }))
  )
  async uploadDocument(@UploadedFile() file: Express.Multer.File) {
    return {
      success: true,
      filePath: file.path.replace(/\\/g, '/'),
    };
  }
}
```

## 自定义配置

### 限制文件类型

```typescript
createFileInterceptorConfig({
  destination: './uploads/images',
  allowedMimeTypes: ['image/jpeg', 'image/png', 'image/gif'],
})
```

### 限制文件大小

```typescript
createFileInterceptorConfig({
  destination: './uploads/temp',
  maxFileSize: 10 * 1024 * 1024, // 10MB
})
```

## 文件路径处理

上传后获取文件路径：

```typescript
async uploadFile(@UploadedFile() file: Express.Multer.File) {
  // Windows: C:\project\uploads\temp\session-123\file-123456.csv
  const absolutePath = file.path;
  
  // 转换为相对路径（前端使用）
  const relativePath = file.path.replace(/\\/g, '/').split('uploads/')[1];
  // uploads/temp/session-123/file-123456.csv
  
  return {
    success: true,
    filePath: `uploads/${relativePath}`,
  };
}
```

## 注意事项

1. **SessionId 来源**：确保前端在上传时提供 `sessionId`（FormData 或 URL 参数）
2. **目录权限**：确保应用有目录的读写权限
3. **磁盘空间**：定期清理过期文件，避免磁盘满
4. **大文件处理**：对于 > 100MB 的文件，考虑使用分片上传
5. **安全性**：生产环境建议添加文件类型和大小验证

## 后续改进建议

- [ ] 支持分片上传（用于大文件）
- [ ] 支持秒传（MD5 哈希）
- [ ] 支持断点续传
- [ ] 自动过期文件清理任务
- [ ] 文件扫描和病毒检测
- [ ] 细粒度权限控制

---

**版本**: 1.0  
**最后更新**: 2025年1月  
**维护者**: 后端团队
