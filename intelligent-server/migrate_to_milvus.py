#!/usr/bin/env python3
"""
MongoDB embedding 迁移到 Milvus 的脚本
使用修改后的 taskType: 'RETRIEVAL_DOCUMENT' 重新生成向量

使用方法:
    # 完整迁移（重新生成所有向量）
    python migrate_to_milvus.py --mode full
    
    # 只迁移数据（保用原有向量）
    python migrate_to_milvus.py --mode migrate-only
    
    # 验证数据
    python migrate_to_milvus.py --mode verify
"""

import json
import time
import argparse
import asyncio
import re
from typing import List, Dict, Any
from tqdm import tqdm
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# MongoDB
from pymongo import MongoClient, UpdateOne
from pymongo.errors import ConnectionFailure

# Milvus
from pymilvus import connections, Collection, FieldSchema, CollectionSchema, DataType, utility

try:
    from pymilvus import Function, FunctionType
    MILVUS_AVAILABLE = True
except:
    MILVUS_AVAILABLE = False

# GenAI - 通过HTTP调用NestJS服务
import httpx


def extract_mdl_summary(doc: Dict[str, Any], max_length: int = 1200) -> str:
    """从 mdl 字段中提取纯文本摘要，去除HTML标签和多余空白，并限制长度。"""
    raw_mdl = doc.get("mdl") or ""

    if not isinstance(raw_mdl, str) or not raw_mdl.strip():
        return ""

    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw_mdl)).strip()[:max_length]


def build_model_text(doc: Dict[str, Any]) -> str:
    """构建用于 embedding 和 BM25 的文本：名称 + 描述 + mdl 摘要。"""
    modelName = doc.get("name", "") or doc.get("modelName", "") or ""
    modelDescription = doc.get("description", "") or doc.get("modelDescription", "") or ""
    modelMdl = extract_mdl_summary(doc)

    parts = [
        part for part in [
            f"modelName: {modelName}" if modelName else "",
            f"modelDescription: {modelDescription}" if modelDescription else "",
            f"modelMdl: {modelMdl}" if modelMdl else "",
        ] if part
    ]

    return ". ".join(parts)


class MongoDBConnector:
    """MongoDB连接器"""
    
    def __init__(self, uri: str = "mongodb://localhost:27017/", db_name: str = "huanghe-demo"):
        self.uri = uri
        self.db_name = db_name
        self.client = None
        self.db = None
        
    def connect(self):
        """连接MongoDB"""
        try:
            self.client = MongoClient(self.uri, serverSelectionTimeoutMS=5000)
            self.client.admin.command('ping')
            self.db = self.client[self.db_name]
            logger.info(f"✅ MongoDB 连接成功: {self.uri}")
            return True
        except ConnectionFailure as e:
            logger.error(f"❌ MongoDB 连接失败: {e}")
            return False
    
    def get_resource_collection(self):
        """获取modelResource集合（包含keywords）"""
        if self.db is None:
            return None
        return self.db['modelResource']

    def get_embeddings_collection(self):
        """获取modelembeddings集合"""
        if self.db is None:
            return None
        return self.db['modelembeddings']
    
    def read_all_embeddings(self) -> List[Dict[str, Any]]:
        """读取 modelResource 作为唯一来源，生成待重建的文档列表"""
        resources_col = self.get_resource_collection()

        if resources_col is None:
            return []

        try:
            resource_docs = list(resources_col.find({}, {
                'id': 1,
                'md5': 1,
                'name': 1,
                'description': 1,
                'mdl': 1,
                'mdlJson': 1,
            }))
            logger.info(f"✅ 读取资源数据: {len(resource_docs)} 条")

            docs: List[Dict[str, Any]] = []
            for res_doc in resource_docs:
                model_md5 = res_doc.get('md5') or ''
                model_id = res_doc.get('id') or ''
                model_name = res_doc.get('name') or ''
                model_description = res_doc.get('description') or ''

                if not model_md5:
                    continue

                docs.append({
                    'modelId': str(model_id),
                    'modelMd5': str(model_md5),
                    'modelName': str(model_name),
                    'modelDescription': str(model_description),
                    'mdl': res_doc.get('mdl') or '',
                    'mdlJson': res_doc.get('mdlJson') or {},
                })

            return docs
        except Exception as e:
            logger.error(f"❌ 读取资源数据失败: {e}")
            return []

    def read_embeddings_from_mongo(self) -> List[Dict[str, Any]]:
        """读取 MongoDB embedding 集合，用于迁移到 Milvus"""
        embeddings_col = self.get_embeddings_collection()

        if embeddings_col is None:
            return []

        try:
            docs = list(embeddings_col.find({}, {
                'modelId': 1,
                'modelMd5': 1,
                'modelName': 1,
                'modelDescription': 1,
                'embeddingSource': 1,
                'embedding': 1,
                'modelText': 1,
                'mdl': 1,
                'mdlJson': 1,
            }))
            logger.info(f"✅ 读取 MongoDB embeddings: {len(docs)} 条")
            return docs
        except Exception as e:
            logger.error(f"❌ 读取 MongoDB embeddings 失败: {e}")
            return []

    def upsert_embeddings(self, docs: List[Dict[str, Any]], batch_size: int = 1000) -> int:
        """写入 embedding 到 MongoDB（upsert by modelMd5）"""
        embeddings_col = self.get_embeddings_collection()

        if embeddings_col is None:
            return 0

        ops: List[UpdateOne] = []
        written = 0

        for doc in docs:
            model_md5 = str(doc.get("modelMd5", "") or "")
            embedding = doc.get("embedding", [])
            if not model_md5:
                continue
            if not (isinstance(embedding, list) and len(embedding) == 3072):
                continue

            payload = {
                "modelId": str(doc.get("modelId", "") or ""),
                "modelMd5": model_md5,
                "modelName": str(doc.get("modelName", "") or ""),
                "modelDescription": str(doc.get("modelDescription", "") or ""),
                "embeddingSource": str(doc.get("embeddingSource", "") or ""),
                "embedding": embedding,
                "modelText": str(doc.get("modelText", "") or build_model_text(doc)),
                "mdl": str(doc.get("mdl", "") or ""),
                "mdlJson": doc.get("mdlJson") or {},
                "updatedAt": time.time(),
            }

            ops.append(UpdateOne({"modelMd5": model_md5}, {"$set": payload}, upsert=True))

            if len(ops) >= batch_size:
                result = embeddings_col.bulk_write(ops, ordered=False)
                written += result.upserted_count + result.modified_count
                ops = []

        if ops:
            result = embeddings_col.bulk_write(ops, ordered=False)
            written += result.upserted_count + result.modified_count

        logger.info(f"✅ 写入 MongoDB embeddings: {written} 条")
        return written
    
    def close(self):
        """关闭连接"""
        if self.client:
            self.client.close()
            logger.info("✅ MongoDB连接已关闭")


class EmbeddingGenerator:
    """调用GenAI服务生成embedding"""
    
    def __init__(self, 
                 genai_url: str = "http://localhost:3000",
                 batch_size: int = 5,
                 delay_per_batch: float = 0.5):
        self.genai_url = genai_url
        self.batch_size = batch_size
        self.delay_per_batch = delay_per_batch
        self.client = httpx.AsyncClient(timeout=60.0)
        
    async def generate_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """批量生成embedding"""
        try:
            # 调用NestJS服务的embedding端点
            response = await self.client.post(
                f"{self.genai_url}/genai/embeddings",
                json={"texts": texts},
                timeout=60.0
            )
            
            if response.status_code == 200:
                result = response.json()
                embeddings = result.get("embeddings", [])
                if not embeddings:
                    logger.warning(f"⚠️  GenAI返回空embeddings，原始响应: {result}")
                return embeddings
            else:
                logger.error(f"❌ GenAI服务返回错误: {response.status_code} - {response.text}")
                return []
        except Exception as e:
            logger.error(f"❌ 生成embedding失败: {e}")
            return []

    async def regenerate_all_embeddings(self, docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """重新生成所有embedding"""
        
        logger.info("🔄 开始重新生成 embedding")
        
        # 准备文本：组合模型名称和关键词
        texts_to_embed = []
        doc_indices = []
        
        for idx, doc in enumerate(docs):
            combined_text = build_model_text(doc)
            if combined_text:
                texts_to_embed.append(combined_text)
                doc_indices.append(idx)
        
        logger.info(f"📝 待生成向量: {len(texts_to_embed)}")
        
        # 批量生成embedding
        new_docs = [doc.copy() for doc in docs]  # 复制一份，保留原有元数据
        regenerated_count = 0
        kept_original_count = 0

        for batch_start in tqdm(range(0, len(texts_to_embed), self.batch_size),
                                desc="生成embedding"):
            batch_end = min(batch_start + self.batch_size, len(texts_to_embed))
            batch_texts = texts_to_embed[batch_start:batch_end]
            batch_doc_indices = doc_indices[batch_start:batch_end]
            
            embeddings = await self.generate_embeddings_batch(batch_texts)

            if not embeddings or len(embeddings) != len(batch_texts):
                logger.warning(
                    f"⚠️  批次 {batch_start}-{batch_end} 生成失败，保留MongoDB原向量"
                )
                kept_original_count += len(batch_texts)
            else:
                for i, doc_idx in enumerate(batch_doc_indices):
                    vec = embeddings[i]
                    if isinstance(vec, list) and len(vec) == 3072:
                        new_docs[doc_idx]['embedding'] = vec
                        new_docs[doc_idx]['modelText'] = batch_texts[i]
                        new_docs[doc_idx]['embeddingSource'] = 'RETRIEVAL_DOCUMENT'
                        new_docs[doc_idx]['regeneratedAt'] = time.time()
                        regenerated_count += 1
                    else:
                        kept_original_count += 1
                        logger.warning(
                            f"⚠️  文档索引 {doc_idx} 新向量维度异常，保留MongoDB原向量"
                        )
            
            # 延迟，避免API限制
            if batch_end < len(texts_to_embed):
                await asyncio.sleep(self.delay_per_batch)

        logger.info(
            f"✅ 向量生成完成: 新生成 {regenerated_count} 条, 保留 {kept_original_count} 条"
        )
        
        return new_docs
    
    async def close(self):
        """关闭HTTP客户端"""
        await self.client.aclose()


class MilvusConnector:
    """Milvus连接器"""
    
    def __init__(self, 
                 host: str = "localhost",
                 port: int = 19530,
                 collection_name: str = "modelembeddings"):
        self.host = host
        self.port = port
        self.collection_name = collection_name
        self.collection = None
        
    def connect(self) -> bool:
        """连接Milvus"""
        if not MILVUS_AVAILABLE:
            logger.error("❌ Milvus SDK未安装，请先运行: pip install pymilvus")
            return False
        
        try:
            connections.connect(
                alias="default",
                host=self.host,
                port=self.port
            )
            logger.info(f"✅ Milvus连接成功: {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"❌ Milvus连接失败: {e}")
            return False
    
    def create_collection(self) -> bool:
        """创建Milvus集合（如果不存在）"""
        try:
            # 检查集合是否存在
            if utility.has_collection(self.collection_name):
                self.collection = Collection(name=self.collection_name)
                logger.info(f"✅ 集合 {self.collection_name} 已存在，将使用该集合")
                return True
            
            # 定义字段
            fields = [
                FieldSchema(
                    name="id",
                    dtype=DataType.INT64
                ),
                FieldSchema(
                    name="modelId",
                    dtype=DataType.VARCHAR,
                    max_length=255
                ),
                FieldSchema(
                    name="modelMd5",
                    dtype=DataType.VARCHAR,
                    max_length=255,
                    is_primary=True,
                    auto_id=False,
                ),
                FieldSchema(
                    name="modelName",
                    dtype=DataType.VARCHAR,
                    max_length=1024
                ),
                FieldSchema(
                    name="modelDescription",
                    dtype=DataType.VARCHAR,
                    max_length=8192
                ),
                FieldSchema(
                    name="modelText",
                    dtype=DataType.VARCHAR,
                    max_length=16384,
                    enable_analyzer=True,
                    enable_match=True,
                    analyzer_params={
                        "type": "chinese",
                    },
                ),
                FieldSchema(
                    name="embeddingSource",
                    dtype=DataType.VARCHAR,
                    max_length=255
                ),
                FieldSchema(
                    name="embedding",
                    dtype=DataType.FLOAT_VECTOR,
                    dim=3072  # Google Gemini embedding维度
                ),
                FieldSchema(
                    name="sparse",
                    dtype=DataType.SPARSE_FLOAT_VECTOR,
                    is_function_output=True,
                )
            ]

            functions = [
                Function(
                    name="model_text_bm25",
                    function_type=FunctionType.BM25,
                    input_field_names=["modelText"],
                    output_field_names=["sparse"],
                    params={},
                )
            ]
            
            # 创建集合
            schema = CollectionSchema(
                fields=fields,
                description="Model embeddings for RAG retrieval",
                functions=functions,
            )
            
            self.collection = Collection(
                name=self.collection_name,
                schema=schema
            )
            
            logger.info(f"✅ 创建集合: {self.collection_name}")
            return True
            
        except Exception as e:
            logger.error(f"❌ 创建集合失败: {e}")
            return False
    
    def insert_documents(self, docs: List[Dict[str, Any]]) -> bool:
        """向Milvus插入文档"""
        if self.collection is None:
            logger.error("❌ 集合未初始化")
            return False
        
        try:
            existing_md5_set = set()

            existing_indexes = list(getattr(self.collection, "indexes", []) or [])

            has_embedding_index = any(
                getattr(index, "field_name", "") == "embedding"
                for index in existing_indexes
            )

            if has_embedding_index:
                try:
                    self.collection.load()

                    batch_size = 16000
                    offset = 0

                    while True:
                        existing_rows = self.collection.query(
                            expr='modelMd5 != ""',
                            output_fields=["modelMd5"],
                            offset=offset,
                            limit=batch_size
                        )

                        if not existing_rows:
                            break

                        existing_md5_set.update(
                            str(row.get("modelMd5", ""))
                            for row in existing_rows
                            if row.get("modelMd5")
                        )

                        offset += batch_size

                    logger.info(
                        f"ℹ️  已存在 {len(existing_md5_set)} 条 modelMd5，将执行增量迁移"
                    )

                except Exception as query_err:
                    logger.warning(
                        f"⚠️  增量检查失败，继续执行: {type(query_err).__name__}"
                    )
            else:
                logger.info("ℹ️  新集合无索引，跳过增量检查")

            seen_in_batch = set()

            # 准备插入数据（行式写法）
            rows = []

            for doc in docs:
                model_md5 = str(doc.get("modelMd5", "") or "")
                if model_md5:
                    if model_md5 in existing_md5_set:
                        continue
                    if model_md5 in seen_in_batch:
                        continue
                    seen_in_batch.add(model_md5)

                embedding = doc.get("embedding", [])
                if isinstance(embedding, list) and len(embedding) == 3072:
                    vector = embedding
                else:
                    # 如果embedding维度不对，使用零向量
                    logger.warning(f"⚠️  跳过非法向量: {model_md5}")
                    continue

                model_name = doc.get("modelName", "") or ""
                model_description = doc.get("modelDescription", "") or ""
                model_text = str(doc.get("modelText", "") or build_model_text(doc))

                rows.append({
                    "modelId": str(doc.get("modelId", "")),
                    "modelMd5": model_md5,
                    "modelName": model_name,
                    "modelDescription": model_description,
                    "modelText": model_text,
                    "embeddingSource": doc.get("embeddingSource", "") or "",
                    "embedding": vector,
                })

            if not rows:
                logger.info("✅ 无新增数据写入")
                return True
            
            # 批量插入
            mr = self.collection.insert(rows)
            self.collection.flush()
            
            logger.info(f"✅ 写入 Milvus: {mr.insert_count} 条")
            return True
            
        except Exception as e:
            logger.error(f"❌ 插入数据失败: {e}")
            return False
    
    def create_index(self) -> bool:
        """创建索引"""
        if self.collection is None:
            logger.error("❌ 集合未初始化")
            return False
        
        try:
            # 兼容已有多索引场景（如 embedding + sparse）
            existing_indexes = list(getattr(self.collection, "indexes", []) or [])
            existing_fields = {getattr(index, "field_name", "") for index in existing_indexes}

            if {"embedding", "sparse"}.issubset(existing_fields):
                logger.info("✅ embedding索引和sparse索引都已存在")
                return True

            if "embedding" not in existing_fields:
                embedding_index_params = {
                    "index_type": "HNSW",
                    "metric_type": "COSINE",
                    "params": {"M": 8, "efConstruction": 200},
                }
                self.collection.create_index(
                    field_name="embedding",
                    index_params=embedding_index_params
                )
                logger.info("✅ 创建 embedding 索引")

            if "sparse" not in existing_fields:
                sparse_index_params = {
                    "index_type": "SPARSE_INVERTED_INDEX",
                    "metric_type": "BM25",
                    "params": {},
                }
                self.collection.create_index(
                    field_name="sparse",
                    index_params=sparse_index_params
                )
                logger.info("✅ 创建 sparse 索引")

            try:
                self.collection.load()
            except Exception:
                pass

            return True
            
        except Exception as e:
            logger.error(f"❌ 创建索引失败: {e}")
            return False
    
    def load_collection(self):
        """加载集合到内存"""
        if self.collection is None:
            return False

        try:
            self.collection.load()
            logger.info("✅ 集合已加载")
            return True
        except Exception as e:
            logger.error(f"❌ 加载集合失败: {e}")
            return False

    def verify_data(self) -> Dict[str, Any]:
        """验证数据"""
        if self.collection is None:
            try:
                if not utility.has_collection(self.collection_name):
                    logger.warning(f"⚠️  集合不存在: {self.collection_name}")
                    return {
                        "total_count": 0,
                        "sample_data": []
                    }

                self.collection = Collection(name=self.collection_name)
            except Exception as e:
                logger.error(f"❌ 初始化集合失败: {e}")
                return {}
        
        try:
            self.collection.load()
            count = self.collection.num_entities
            logger.info(f"✅ Milvus 数据量: {count}")
            
            return {
                "total_count": count,
            }
            
        except Exception as e:
            logger.error(f"❌ 数据验证失败: {e}")
            return {}
    
    def close(self):
        """关闭连接"""
        try:
            connections.disconnect(alias="default")
            logger.info("✅ Milvus连接已关闭")
        except Exception as e:
            logger.error(f"❌ 关闭连接失败: {e}")


def reset_milvus(milvus_host: str, milvus_port: int, collection_name: str = "modelembeddings"):
    """重置Milvus集合（删除后重建）"""
    logger.info("🔄 重置 Milvus 集合")
    
    milvus = MilvusConnector(host=milvus_host, port=milvus_port)
    if not milvus.connect():
        return
    
    try:
        # 释放集合
        if utility.has_collection(collection_name):
            try:
                connections.get_connection(alias="default").release_collection(
                    collection_name=collection_name
                )
                logger.info(f"✅ 已释放集合: {collection_name}")
            except:
                pass
            
            # 删除集合
            utility.drop_collection(collection_name)
            logger.info(f"✅ 已删除集合: {collection_name}")
        
        logger.info("✅ Milvus 集合重置完成")
    except Exception as e:
        logger.error(f"❌ 重置集合失败: {e}")
    finally:
        milvus.close()

async def migrate_full(mongodb_uri: str, mongodb_db: str, genai_url: str, milvus_host: str, milvus_port: int):
    """完整迁移：生成向量写入MongoDB，再迁移到Milvus"""
    logger.info("🚀 开始全量重建")
    
    # 1. 从MongoDB读取数据
    mongo = MongoDBConnector(uri=mongodb_uri, db_name=mongodb_db)
    if not mongo.connect():
        return
    
    docs = mongo.read_all_embeddings()
    if not docs:
        logger.error("❌ 未读取到任何数据，中止迁移")
        mongo.close()
        return
    
    mongo.close()
    
    # 2. 重新生成embedding
    generator = EmbeddingGenerator(genai_url=genai_url)
    try:
        docs = await generator.regenerate_all_embeddings(docs)
    finally:
        await generator.close()
    
    # 3. 写入 Milvus，不再经过 MongoDB embeddings 中转
    milvus = MilvusConnector(host=milvus_host, port=milvus_port)
    if not milvus.connect():
        return
    
    if not milvus.create_collection():
        milvus.close()
        return
    
    if not milvus.create_index():
        logger.warning("⚠️  索引创建失败，但数据已插入")
    
    if not milvus.insert_documents(docs):
        milvus.close()
        return
    
    milvus.load_collection()
    
    # 验证
    verification = milvus.verify_data()
    logger.info(f"✅ 迁移完成！共 {verification.get('total_count', 0)} 条数据")
    
    milvus.close()


def migrate_only(mongodb_uri: str, mongodb_db: str, milvus_host: str, milvus_port: int):
    """只迁移数据，不重新生成向量"""
    logger.info("🚀 开始迁移 MongoDB embeddings")

    mongo = MongoDBConnector(uri=mongodb_uri, db_name=mongodb_db)
    if not mongo.connect():
        return

    docs = mongo.read_embeddings_from_mongo()
    mongo.close()

    if not docs:
        logger.error("❌ 未读取到 MongoDB embeddings，中止迁移")
        return

    milvus = MilvusConnector(host=milvus_host, port=milvus_port)
    if not milvus.connect():
        return

    if not milvus.create_collection():
        milvus.close()
        return

    if not milvus.create_index():
        logger.warning("⚠️  索引创建失败，但数据已插入")

    if not milvus.insert_documents(docs):
        milvus.close()
        return

    milvus.load_collection()

    verification = milvus.verify_data()
    logger.info(f"✅ 迁移完成！共 {verification.get('total_count', 0)} 条数据")

    milvus.close()


def verify_milvus(milvus_host: str, milvus_port: int):
    """验证Milvus中的数据"""
    logger.info("🔍 验证 Milvus 数据")
    
    milvus = MilvusConnector(host=milvus_host, port=milvus_port)
    if not milvus.connect():
        return
    
    milvus.verify_data()
    
    milvus.close()


def main():
    parser = argparse.ArgumentParser(description="MongoDB Embedding迁移到Milvus")
    parser.add_argument(
        "--mode",
        choices=["full", "migrate-only", "verify", "reset"],
        default="migrate-only",
        help="迁移模式"
    )
    parser.add_argument(
        "--mongodb-uri",
        default="mongodb://localhost:27017/",
        help="MongoDB连接URI"
    )
    parser.add_argument(
        "--mongodb-db",
        default="huanghe-demo",
        help="MongoDB数据库名"
    )
    parser.add_argument(
        "--genai-url",
        default="http://localhost:3000",
        help="GenAI服务URL（仅--mode=full需要）"
    )
    parser.add_argument(
        "--milvus-host",
        default="localhost",
        help="Milvus服务器地址"
    )
    parser.add_argument(
        "--milvus-port",
        type=int,
        default=19530,
        help="Milvus服务器端口"
    )
    parser.add_argument(
        "--reset-collection",
        action="store_true",
        help="在迁移前重置Milvus集合（删除所有现有数据）"
    )
    
    args = parser.parse_args()
    
    logger.info("📋 配置信息")
    logger.info(f"- 模式: {args.mode}")
    logger.info(f"- Milvus: {args.milvus_host}:{args.milvus_port}")
    if args.mode == "full":
        logger.info(f"  - GenAI服务: {args.genai_url}")
    if args.reset_collection:
        logger.info(f"  - 将重置Milvus集合")
    
    if args.reset_collection:
        reset_milvus(
            milvus_host=args.milvus_host,
            milvus_port=args.milvus_port
        )
    
    if args.mode == "full":
        asyncio.run(migrate_full(
            mongodb_uri=args.mongodb_uri,
            mongodb_db=args.mongodb_db,
            genai_url=args.genai_url,
            milvus_host=args.milvus_host,
            milvus_port=args.milvus_port
        ))
    elif args.mode == "migrate-only":
        migrate_only(
            mongodb_uri=args.mongodb_uri,
            mongodb_db=args.mongodb_db,
            milvus_host=args.milvus_host,
            milvus_port=args.milvus_port
        )
    elif args.mode == "verify":
        verify_milvus(
            milvus_host=args.milvus_host,
            milvus_port=args.milvus_port
        )
    elif args.mode == "reset":
        reset_milvus(
            milvus_host=args.milvus_host,
            milvus_port=args.milvus_port
        )


if __name__ == "__main__":
    main()
