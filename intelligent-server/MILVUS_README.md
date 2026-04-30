# Milvus迁移工具集

> 将MongoDB中的模型embedding迁移到Milvus向量数据库的自动化工具

## ⚡ 快速开始

### 1. 最快方式（交互式菜单）

```bash
# 使用交互式启动脚本
python quick_migrate.py

# 然后选择：
# 4 - 启动容器
# 1 - 完整迁移
# 3 - 验证数据
```

### 2. 标准方式（命令行）

```bash
# 启动Milvus和MongoDB
docker-compose -f ../docker-compose.milvus.yml up -d

# 初始化Milvus集合
curl -X POST http://localhost:3000/genai/milvus/init

# 执行迁移
python migrate_to_milvus.py --mode full
```

### 3. 验证迁移结果

```bash
# 检查Milvus中的数据
python migrate_to_milvus.py --mode verify

# 或使用API
curl http://localhost:3000/genai/milvus/stats
```

## 📁 文件说明

| 文件 | 用途 |
|------|------|
| `migrate_to_milvus.py` | 自动化迁移脚本（支持3种模式） |
| `quick_migrate.py` | 交互式菜单启动脚本 |
| `MIGRATION_GUIDE.md` | 详细迁移文档和故障排除 |
| `../docker-compose.milvus.yml` | Docker容器配置 |
| `../MILVUS_MIGRATION_SUMMARY.md` | 项目整体迁移总结 |

## 🎯 迁移模式

```bash
# 完整迁移 - 重新生成所有向量（推荐）
python migrate_to_milvus.py --mode full

# 快速迁移 - 只迁移数据，保留原有向量
python migrate_to_milvus.py --mode migrate-only

# 验证数据 - 检查Milvus中的数据状态
python migrate_to_milvus.py --mode verify
```

## ⚙️ 自定义参数

```bash
python migrate_to_milvus.py --mode full \
  --mongodb-uri "mongodb://user:pass@host:27017/" \
  --mongodb-db "huanghe-demo" \
  --genai-url "http://localhost:3000" \
  --milvus-host "127.0.0.1" \
  --milvus-port 19530
```

## 📊 预期结果

**完整迁移**：
- 从MongoDB读取 ~5,000-10,000 条embedding
- 用新的`taskType: 'RETRIEVAL_DOCUMENT'`重新生成向量
- 插入Milvus并创建HNSW索引
- 总耗时：5-15分钟

**迁移日志示例**：
```
✅ MongoDB 连接成功
✅ 从MongoDB读取 5234 条embedding数据
✅ 成功生成 5234 条新embedding
✅ Milvus连接成功
✅ 成功插入 5234 条数据
✅ 成功创建向量索引
✅ 迁移完成！共 5234 条数据
```

## 🔍 常见命令

```bash
# 获取帮助
python migrate_to_milvus.py --help

# 检查服务状态
curl http://localhost:3000/genai/health
curl http://localhost:19530/healthz

# 测试向量搜索
curl -X POST http://localhost:3000/genai/milvus/search \
  -H "Content-Type: application/json" \
  -d '{"embedding": [0.1, 0.2, ...], "limit": 5}'

# 查看容器日志
docker logs milvus-standalone
docker logs mongodb-embedding
```

## 🛠️ 故障排除

### Milvus连接失败
```bash
# 检查容器是否运行
docker ps | grep milvus

# 启动容器
docker-compose -f ../docker-compose.milvus.yml up -d
```

### MongoDB连接失败
```bash
# 检查连接字符串
python -c "from pymongo import MongoClient; MongoClient('mongodb://localhost:27017/').admin.command('ping')"
```

### GenAI API超时
```bash
# 检查NestJS服务
curl http://localhost:3000/genai/health

# 或查看服务日志
npm run start:dev
```

更多详情请见 [MIGRATION_GUIDE.md](./MIGRATION_GUIDE.md)

---

**最后修改**: 2026-04-30
