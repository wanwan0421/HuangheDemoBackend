# MongoDB Embedding 迁移到 Milvus 指南

本指南说明如何将存储在MongoDB中的模型embedding迁移到Milvus向量数据库，并使用修改后的`taskType: 'RETRIEVAL_DOCUMENT'`重新生成向量。

## 📋 前置条件

### 1. 环境要求
- Python 3.8+
- MongoDB运行中（默认: `mongodb://localhost:27017/`）
- Milvus运行中（默认: `localhost:19530`）
- NestJS后端服务运行中（默认: `http://localhost:3000`）

### 2. 安装依赖

在`intelligent-server`目录中：

```bash
# 安装Python依赖
pip install pymongo pymilvus httpx tqdm

# 可选：如果要使用完整的embedding重新生成功能
pip install google-cloud-aiplatform  # 如果使用Google AI
```

### 3. 安装NestJS依赖

在项目根目录中：

```bash
npm install @zilliz/milvus2-sdk-node
```

## 🚀 迁移步骤

### 第一步：确保Milvus服务运行

```bash
# 使用Docker启动Milvus（如果还未启动）
docker-compose up -d milvus

# 检查Milvus健康状态
curl http://localhost:19530/healthz
```

### 第二步：初始化Milvus集合

通过NestJS API初始化Milvus集合：

```bash
# 使用curl
curl -X POST http://localhost:3000/genai/milvus/init \
  -H "Content-Type: application/json"

# 或使用PowerShell（Windows）
$response = Invoke-WebRequest -Uri "http://localhost:3000/genai/milvus/init" `
  -Method POST `
  -Headers @{"Content-Type"="application/json"}
Write-Host $response.Content
```

**预期输出**：
```json
{
  "success": true,
  "message": "Milvus初始化完成",
  "indexCreated": true
}
```

### 第三步：执行迁移

根据需要选择迁移模式：

#### 模式A：**完整迁移**（推荐 - 重新生成所有向量）

此模式会使用新的`taskType: 'RETRIEVAL_DOCUMENT'`重新生成所有向量：

```bash
cd intelligent-server
python migrate_to_milvus.py --mode full \
  --mongodb-uri "mongodb://localhost:27017/" \
  --genai-url "http://localhost:3000" \
  --milvus-host "localhost" \
  --milvus-port 19530
```

**工作流程**：
1. ✅ 从MongoDB读取所有embedding文档（~5000+条）
2. ✅ 使用修改后的GenAI服务重新生成embedding
   - 新的`taskType: 'RETRIEVAL_DOCUMENT'`用于文档嵌入
   - 旧的`taskType: 'RETRIEVAL_QUERY'`用于查询嵌入
3. ✅ 批量插入到Milvus（批大小：5条/批，延迟：0.5秒）
4. ✅ 创建向量索引
5. ✅ 验证数据

**预期时间**：~5-15分钟（取决于数据量和网络）

#### 模式B：**数据迁移**（快速 - 保留原有向量）

此模式直接迁移现有embedding，不重新生成：

```bash
cd intelligent-server
python migrate_to_milvus.py --mode migrate-only \
  --mongodb-uri "mongodb://localhost:27017/" \
  --milvus-host "localhost" \
  --milvus-port 19530
```

**适用场景**：
- 快速验证Milvus的向量检索效果
- 不需要重新生成向量的情况

#### 模式C：**只验证**（诊断）

验证Milvus中的数据状态：

```bash
cd intelligent-server
python migrate_to_milvus.py --mode verify \
  --milvus-host "localhost" \
  --milvus-port 19530
```

**预期输出**：
```json
{
  "total_count": 5234,
  "sample_data": [...]
}
```

## 📊 监控迁移进度

### 实时日志输出

迁移脚本提供详细的进度信息：

```
🚀 开始完整迁移流程（重新生成向量）
============================================================
✅ MongoDB 连接成功: mongodb://localhost:27017/
✅ 从MongoDB读取 5234 条embedding数据
🔄 开始重新生成embedding（使用 RETRIEVAL_DOCUMENT 任务类型）...
📝 准备生成 5234 条向量
生成embedding: 100%|████████████| 1047/1047 [12:34<00:00,  1.39 batches/s]
✅ 成功生成 5234 条新embedding
✅ Milvus连接成功: localhost:19530
✅ 集合 model_embeddings 已存在，将使用该集合
✅ 成功插入 5234 条数据到Milvus
✅ 成功创建向量索引
✅ 迁移完成！共 5234 条数据
```

### 通过API查询统计

```bash
# 获取集合统计信息
curl http://localhost:3000/genai/milvus/stats

# 搜索功能测试
curl -X POST http://localhost:3000/genai/milvus/search \
  -H "Content-Type: application/json" \
  -d '{"embedding": [0.1, 0.2, ..., 0.5], "limit": 5}'
```

## 🔧 高级配置

### 环境变量

在`.env`文件或系统环境变量中配置：

```env
# Milvus配置
MILVUS_HOST=localhost
MILVUS_PORT=19530
MILVUS_USERNAME=       # 如需认证
MILVUS_PASSWORD=       # 如需认证
MILVUS_COLLECTION=model_embeddings

# GenAI配置
GOOGLE_API_KEY=your_api_key_here
EMBEDDING_DIM=1536     # Google Gemini embedding维度

# MongoDB配置
MONGO_URI=mongodb://localhost:27017/
MONGO_DB=huanghe-demo
```

### 自定义迁移参数

修改迁移脚本中的参数：

```python
# 在migrate_to_milvus.py中修改
batch_size = 10         # 批大小（更大->更快但更多API调用）
delay_per_batch = 1.0   # 批次间延迟（秒，避免API限速）
```

## ✅ 验证迁移成功

### 1. 检查Milvus中的数据

```bash
# 查看集合统计
python -c "
from pymilvus import connections, Collection
connections.connect(host='localhost', port=19530)
collection = Collection('model_embeddings')
print(f'数据量: {collection.num_entities}')
"
```

### 2. 测试向量搜索

```bash
# 使用Python脚本测试搜索
python -c "
import httpx
import json

# 生成测试embedding
test_embedding = [0.1] * 1536

# 搜索
response = httpx.post(
    'http://localhost:3000/genai/milvus/search',
    json={'embedding': test_embedding, 'limit': 5}
)

print(json.dumps(response.json(), indent=2, ensure_ascii=False))
"
```

### 3. 比较新旧embedding

```bash
# 对比MongoDB和Milvus中的数据
# 验证embedding维度和值是否正确迁移
```

## ⚠️ 故障排除

### 问题1：Milvus连接失败

```
❌ Milvus连接失败: Connection refused
```

**解决方案**：
```bash
# 检查Milvus是否运行
docker ps | grep milvus

# 如果未运行，启动Milvus
docker-compose up -d milvus

# 检查端口
netstat -an | findstr 19530  # Windows
netstat -an | grep 19530      # Linux
```

### 问题2：MongoDB连接失败

```
❌ MongoDB 连接失败: Connection refused
```

**解决方案**：
```bash
# 检查MongoDB连接
python -c "from pymongo import MongoClient; MongoClient('mongodb://localhost:27017/').admin.command('ping')"

# 使用不同的URI
python migrate_to_milvus.py --mode verify --mongodb-uri "mongodb://127.0.0.1:27017/"
```

### 问题3：GenAI API超时

```
❌ 生成embedding失败: Connection timeout
```

**解决方案**：
```bash
# 1. 检查NestJS服务是否运行
curl http://localhost:3000/genai/health

# 2. 增加超时时间
# 编辑migrate_to_milvus.py，修改: self.client = httpx.AsyncClient(timeout=120.0)

# 3. 减少批大小
python migrate_to_milvus.py --mode full --batch-size 2
```

### 问题4：向量维度不匹配

```
❌ 插入数据失败: Embedding dimension mismatch
```

**解决方案**：
```bash
# 检查embedding维度
python -c "
from pymongo import MongoClient
client = MongoClient('mongodb://localhost:27017/')
db = client['huanghe-demo']
doc = db.modelembeddings.find_one()
print(f'Embedding维度: {len(doc[\"embedding\"])}')
"

# 如果维度为1536，修改genai.service.ts中的dim参数
```

## 🔄 回滚方案

如果迁移出现问题，可以回滚：

```bash
# 1. 删除Milvus集合（保留MongoDB数据）
python migrate_to_milvus.py --mode migrate-only --delete-collection

# 2. 重新生成MongoDB中的embedding
# - 恢复备份的MongoDB
# - 或重新运行embedding生成流程

# 3. 再次执行迁移
python migrate_to_milvus.py --mode full
```

## 📈 性能优化

### 1. 批量生成优化

```python
# 在migrate_to_milvus.py中调整
batch_size = 20         # 增加批大小
delay_per_batch = 0.2   # 减少延迟
```

### 2. Milvus索引优化

对于更快的搜索，调整索引参数：

```python
# 在milvus.service.ts中修改
index_params = {
    "index_type": "HNSW",  # 或 "IVF_FLAT", "ANNOY"
    "metric_type": "COSINE",
    "params": {"M": 16, "efConstruction": 500}  # 更大的M和ef->更准确但更慢
}
```

### 3. 向量池化查询

```bash
# 批量搜索多个向量
curl -X POST http://localhost:3000/genai/milvus/batch-search \
  -H "Content-Type: application/json" \
  -d '{
    "embeddings": [[...], [...], ...],
    "limit": 10
  }'
```

## 🎯 下一步

迁移完成后，建议：

1. ✅ **集成Milvus搜索**：更新[index.service.ts](../index/index.service.ts)使用Milvus而非MongoDB
2. ✅ **性能测试**：对比MongoDB和Milvus的搜索性能
3. ✅ **灾备**：定期备份Milvus数据
4. ✅ **监控**：添加Milvus健康检查和性能监控

## 📚 相关文件

- [中文迁移脚本](./migrate_to_milvus.py)
- [Milvus服务](./milvus.service.ts)
- [GenAI控制器](./genai.controller.ts)
- [GenAI服务](./genai.service.ts)

## 💡 常见问题

**Q: 如何更新已有的Milvus集合？**
A: 直接运行迁移脚本，它会自动更新现有集合。

**Q: 能否部分迁移（例如只迁移特定类别的模型）？**
A: 可以修改`migrate_to_milvus.py`中的过滤条件。

**Q: MongoDB中的数据会被删除吗？**
A: 不会。迁移过程只读取MongoDB数据，不会修改。

**Q: 能否同时保留MongoDB和Milvus索引？**
A: 可以。Milvus和MongoDB可以并行使用。

---

更新时间: 2026-04-30
