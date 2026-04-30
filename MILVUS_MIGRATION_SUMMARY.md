# 🚀 MongoDB → Milvus 迁移完整指南

## 📌 概述

本项目已完成以下功能实现，用于将MongoDB中的模型embedding迁移到Milvus向量数据库，并使用修改后的`taskType: 'RETRIEVAL_DOCUMENT'`重新生成向量。

### 关键改动

1. **修改了`genai.service.ts`**: 将`taskType`从`'RETRIEVAL_QUERY'`改为`'RETRIEVAL_DOCUMENT'`
2. **新增Milvus集成**:
   - `src/genai/milvus.service.ts` - Milvus操作服务
   - `src/genai/genai.controller.ts` - REST API端点
   - `src/genai/genai.module.ts` - 模块配置
3. **迁移脚本**:
   - `intelligent-server/migrate_to_milvus.py` - 自动化迁移脚本
   - `intelligent-server/quick_migrate.py` - 交互式启动脚本
4. **配置和文档**:
   - `docker-compose.milvus.yml` - Milvus和MongoDB容器配置
   - `intelligent-server/MIGRATION_GUIDE.md` - 详细迁移指南

## 🎯 快速开始（3步）

### 第1步：启动依赖服务

```bash
# 方式1: 使用交互式脚本（推荐）
cd intelligent-server
python quick_migrate.py
# 选择选项 4: 启动容器

# 方式2: 直接使用Docker Compose
docker-compose -f docker-compose.milvus.yml up -d

# 方式3: 确保已启动
# - Milvus: localhost:19530
# - MongoDB: localhost:27017
# - NestJS: localhost:3000
```

### 第2步：初始化Milvus

```bash
# 使用API初始化集合和索引
curl -X POST http://localhost:3000/genai/milvus/init

# 预期结果
# {
#   "success": true,
#   "message": "Milvus初始化完成",
#   "indexCreated": true
# }
```

### 第3步：执行迁移

#### 选项A：完整迁移（推荐）- 重新生成所有向量

```bash
cd intelligent-server

# 方式1: 使用交互式脚本
python quick_migrate.py
# 选择选项 1: 完整迁移

# 方式2: 直接运行脚本
python migrate_to_milvus.py --mode full

# 方式3: 自定义参数
python migrate_to_milvus.py --mode full \
  --mongodb-uri "mongodb://localhost:27017/" \
  --genai-url "http://localhost:3000" \
  --milvus-host "localhost" \
  --milvus-port 19530
```

**工作流程**：
1. 从MongoDB读取所有embedding文档
2. 使用新的`taskType: 'RETRIEVAL_DOCUMENT'`重新生成向量
3. 批量插入到Milvus
4. 创建向量索引
5. 验证数据

**预期时间**: 5-15分钟（取决于数据量）

**预期日志**:
```
🚀 开始完整迁移流程（重新生成向量）
============================================================
✅ MongoDB 连接成功
✅ 从MongoDB读取 5234 条embedding数据
🔄 开始重新生成embedding...
📝 准备生成 5234 条向量
生成embedding: 100%|████████████| 1047/1047 [12:34<00:00]
✅ 成功生成 5234 条新embedding
✅ Milvus连接成功
✅ 成功插入 5234 条数据到Milvus
✅ 成功创建向量索引
✅ 迁移完成！共 5234 条数据
```

#### 选项B：快速迁移 - 保留原有向量

```bash
# 只迁移数据，不重新生成向量
python migrate_to_milvus.py --mode migrate-only

# 预期时间: 1-2分钟
```

#### 选项C：验证数据

```bash
# 检查Milvus中的数据状态
python migrate_to_milvus.py --mode verify

# 或使用API
curl http://localhost:3000/genai/milvus/stats
```

## 📊 集合架构

### MongoDB中的格式

```javascript
{
  _id: ObjectId("..."),
  modelMd5: "abc123...",
  modelName: "流量预报模型",
  modelDescription: "用于预报流量...",
  embedding: [0.1, 0.2, ..., 0.5],  // 1536维
  embeddingSource: "RETRIEVAL_DOCUMENT",
  indicatorEnName: "Traffic",
  indicatorCnName: "流量",
  // ... 其他字段
}
```

### Milvus中的格式

```json
{
  "id": 1,  // 自动生成
  "modelMd5": "abc123...",
  "modelName": "流量预报模型",
  "modelDescription": "用于预报流量...",
  "embedding": [0.1, 0.2, ..., 0.5],  // 1536维，向量字段
  "indicatorEnName": "Traffic",
  "indicatorCnName": "流量",
  // ... 其他字段
}
```

## 🔧 新增API端点

### 1. Embedding生成端点

```bash
# 生成单条embedding
POST /genai/embedding
Content-Type: application/json
{
  "text": "模型名称。模型描述"
}

# 响应
{
  "success": true,
  "embedding": [0.1, 0.2, ..., 0.5],
  "dimension": 1536
}
```

```bash
# 生成多条embedding
POST /genai/embeddings
Content-Type: application/json
{
  "texts": ["文本1", "文本2", "文本3"]
}

# 响应
{
  "success": true,
  "embeddings": [[...], [...], [...]],
  "count": 3
}
```

### 2. Milvus操作端点

```bash
# 初始化Milvus（创建集合+索引）
POST /genai/milvus/init

# 插入数据到Milvus
POST /genai/milvus/insert
{
  "documents": [
    { "modelMd5": "...", "embedding": [...], ... },
    { "modelMd5": "...", "embedding": [...], ... }
  ]
}

# 搜索向量
POST /genai/milvus/search
{
  "embedding": [0.1, 0.2, ..., 0.5],
  "limit": 10
}

# 获取集合统计
GET /genai/milvus/stats

# Flush数据
POST /genai/milvus/flush

# 服务健康检查
GET /genai/health
```

## 📈 性能对比

### MongoDB向量查询
```typescript
// 原有方式：应用层计算余弦相似度
const allDocs = await collection.find({...}).lean();
const similarities = allDocs.map(doc => ({
  score: cosineSimilarity(vector, doc.embedding),
  ...doc
}));
const topK = similarities.sort((a,b) => b.score - a.score).slice(0, 10);
```
- 查询速度：O(n)，需要遍历所有文档
- 内存使用：O(n)
- 适合数据量 < 10,000

### Milvus向量查询
```typescript
// 新方式：向量数据库优化查询
const results = await milvusService.search(vector, limit: 10);
```
- 查询速度：O(log n)，使用HNSW索引
- 内存使用：优化管理
- 适合数据量 > 100,000

**基准测试结果**（预计）:
- 5,000 向量：Milvus ~50ms vs MongoDB ~500ms （10倍快）
- 50,000 向量：Milvus ~100ms vs MongoDB ~5000ms （50倍快）

## 🔄 后续集成步骤

### 步骤1：更新搜索逻辑

在`src/index/index.service.ts`中：

```typescript
// 原有方式（MongoDB）
public async findRelevantModel(userQueryVector: number[], modelIds: string[]) {
    const data = await this.ModelEmbeddingModel.find({ modelMd5: { $in: modelIds} });
    // ... 应用层计算相似度
}

// 新方式（Milvus）
public async findRelevantModel(userQueryVector: number[], modelIds: string[]) {
    const results = await this.milvusService.search(userQueryVector, limit: 10);
    return results.filter(r => modelIds.includes(r.modelMd5));
}
```

### 步骤2：批量查询优化

```typescript
// 支持批量搜索
@Post('milvus/batch-search')
async batchSearch(@Body() body: { embeddings: number[][]; limit: number }) {
    return Promise.all(
        body.embeddings.map(emb => this.milvusService.search(emb, body.limit))
    );
}
```

### 步骤3：缓存策略

```typescript
// 使用Redis缓存热点查询
@Cacheable('model_search')
public async findRelevantModel(queryHash: string) {
    return this.milvusService.search(...);
}
```

## 🛡️ 故障恢复

### 数据备份

```bash
# 备份MongoDB数据
mongodump --uri "mongodb://localhost:27017/huanghe-demo" --out ./backup

# 恢复MongoDB数据
mongorestore --uri "mongodb://localhost:27017/" ./backup
```

### 回滚迁移

```bash
# 如果迁移失败，可以：
# 1. 保留MongoDB数据（未修改）
# 2. 删除Milvus集合重新开始
# 3. 修复问题后重新运行迁移

# 删除集合
python -c "
from pymilvus import connections, utility
connections.connect(host='localhost', port=19530)
utility.drop_collection('model_embeddings')
"
```

## 📋 检查清单

在投入生产前，请检查以下事项：

- [ ] MongoDB已正常运行，包含完整的embedding数据
- [ ] Milvus容器已启动并健康检查通过
- [ ] NestJS服务已启动，端点可访问
- [ ] 完成了完整迁移（或快速迁移+验证）
- [ ] Milvus中的数据行数与MongoDB匹配
- [ ] 向量维度正确（1536维）
- [ ] 搜索功能正常（通过API测试）
- [ ] 性能指标满足要求（搜索延迟 < 100ms）
- [ ] 已配置备份策略
- [ ] 已更新查询逻辑以使用Milvus

## 💬 常见问题

**Q: 迁移过程中MongoDB数据会被修改吗？**
A: 不会。迁移脚本只读取数据，不进行任何写操作。

**Q: 可以部分迁移吗？**
A: 可以。修改`migrate_to_milvus.py`中的过滤条件。

**Q: 如何处理embedding维度不一致的情况？**
A: 脚本会自动将缺失的维度填充为0。

**Q: 是否需要同时运行MongoDB和Milvus？**
A: 迁移完成后，可以只保留Milvus。MongoDB作为主数据源继续保存。

**Q: 支持在线迁移吗？**
A: 支持。底层使用增量批处理，不会锁定数据库。

## 📚 相关文档

- [详细迁移指南](./MIGRATION_GUIDE.md)
- [Milvus官方文档](https://milvus.io)
- [MongoDB文档](https://docs.mongodb.com)
- [GenAI服务文档](../src/genai/README.md)

## 🤝 支持

遇到问题？请检查：

1. 日志输出：`migrate_to_milvus.py`会输出详细的错误信息
2. API端点健康检查：`curl http://localhost:3000/genai/health`
3. Milvus健康检查：`curl http://localhost:19530/healthz`
4. MongoDB连接测试：`mongosh localhost:27017`

---

**更新时间**: 2026-04-30
**作者**: System Assistant
**版本**: 1.0
