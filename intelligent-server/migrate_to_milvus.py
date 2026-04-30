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

import os
import sys
import json
import time
import argparse
import asyncio
from typing import List, Dict, Any, Optional
from tqdm import tqdm
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# MongoDB
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure

# Milvus
try:
    from pymilvus import (
        connections,
        Collection,
        FieldSchema,
        CollectionSchema,
        DataType,
        utility
    )
    MILVUS_AVAILABLE = True
except ImportError:
    MILVUS_AVAILABLE = False
    logger.warning("⚠️  Milvus SDK not installed. Install with: pip install pymilvus")

# GenAI - 通过HTTP调用NestJS服务
import httpx


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
    
    def get_embeddings_collection(self):
        """获取embeddings集合"""
        if not self.db:
            return None
        return self.db['modelembeddings']
    
    def read_all_embeddings(self) -> List[Dict[str, Any]]:
        """读取所有embedding文档"""
        collection = self.get_embeddings_collection()
        if not collection:
            return []
        
        try:
            docs = list(collection.find({}))
            logger.info(f"✅ 从MongoDB读取 {len(docs)} 条embedding数据")
            return docs
        except Exception as e:
            logger.error(f"❌ 读取MongoDB数据失败: {e}")
            return []
    
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
                return result.get("embeddings", [])
            else:
                logger.error(f"❌ GenAI服务返回错误: {response.status_code} - {response.text}")
                return []
        except Exception as e:
            logger.error(f"❌ 生成embedding失败: {e}")
            return []
    
    async def regenerate_all_embeddings(self, docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """重新生成所有embedding"""
        
        logger.info("🔄 开始重新生成embedding（使用 RETRIEVAL_DOCUMENT 任务类型）...")
        
        # 准备文本：组合模型名称和描述
        texts_to_embed = []
        doc_indices = []
        
        for idx, doc in enumerate(docs):
            model_name = doc.get('modelName', '')
            model_desc = doc.get('modelDescription', '')
            # 组合文本
            combined_text = f"{model_name}。{model_desc}" if model_desc else model_name
            if combined_text:
                texts_to_embed.append(combined_text)
                doc_indices.append(idx)
        
        logger.info(f"📝 准备生成 {len(texts_to_embed)} 条向量")
        
        # 批量生成embedding
        new_docs = [doc.copy() for doc in docs]  # 复制一份，保留原有元数据
        
        embeddings_batch_list = []
        for batch_start in tqdm(range(0, len(texts_to_embed), self.batch_size), 
                                desc="生成embedding"):
            batch_end = min(batch_start + self.batch_size, len(texts_to_embed))
            batch_texts = texts_to_embed[batch_start:batch_end]
            
            embeddings = await self.generate_embeddings_batch(batch_texts)
            
            if not embeddings:
                logger.warning(f"⚠️  批次 {batch_start}-{batch_end} 生成失败，跳过")
                embeddings = [[0.0] * 1536 for _ in batch_texts]  # 默认维度
            
            embeddings_batch_list.extend(embeddings)
            
            # 延迟，避免API限制
            if batch_end < len(texts_to_embed):
                await asyncio.sleep(self.delay_per_batch)
        
        # 将新embedding更新到文档
        for i, doc_idx in enumerate(doc_indices):
            if i < len(embeddings_batch_list):
                new_docs[doc_idx]['embedding'] = embeddings_batch_list[i]
                new_docs[doc_idx]['embeddingSource'] = 'RETRIEVAL_DOCUMENT'
                new_docs[doc_idx]['regeneratedAt'] = time.time()
        
        logger.info(f"✅ 成功生成 {len(embeddings_batch_list)} 条新embedding")
        
        return new_docs
    
    async def close(self):
        """关闭HTTP客户端"""
        await self.client.aclose()


class MilvusConnector:
    """Milvus连接器"""
    
    def __init__(self, 
                 host: str = "localhost",
                 port: int = 19530,
                 collection_name: str = "model_embeddings"):
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
                    dtype=DataType.INT64,
                    is_primary=True,
                    auto_id=True
                ),
                FieldSchema(
                    name="modelMd5",
                    dtype=DataType.VARCHAR,
                    max_length=255
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
                    name="indicatorEnName",
                    dtype=DataType.VARCHAR,
                    max_length=1024,
                    nullable=True
                ),
                FieldSchema(
                    name="indicatorCnName",
                    dtype=DataType.VARCHAR,
                    max_length=1024,
                    nullable=True
                ),
                FieldSchema(
                    name="categoryEnName",
                    dtype=DataType.VARCHAR,
                    max_length=1024,
                    nullable=True
                ),
                FieldSchema(
                    name="categoryCnName",
                    dtype=DataType.VARCHAR,
                    max_length=1024,
                    nullable=True
                ),
                FieldSchema(
                    name="sphereEnName",
                    dtype=DataType.VARCHAR,
                    max_length=1024,
                    nullable=True
                ),
                FieldSchema(
                    name="sphereCnName",
                    dtype=DataType.VARCHAR,
                    max_length=1024,
                    nullable=True
                ),
                FieldSchema(
                    name="embedding",
                    dtype=DataType.FLOAT_VECTOR,
                    dim=1536  # Google Gemini embedding维度
                )
            ]
            
            # 创建集合
            schema = CollectionSchema(
                fields=fields,
                description="Model embeddings for RAG retrieval"
            )
            
            self.collection = Collection(
                name=self.collection_name,
                schema=schema
            )
            
            logger.info(f"✅ 成功创建Milvus集合: {self.collection_name}")
            return True
            
        except Exception as e:
            logger.error(f"❌ 创建集合失败: {e}")
            return False
    
    def insert_documents(self, docs: List[Dict[str, Any]]) -> bool:
        """向Milvus插入文档"""
        if not self.collection:
            logger.error("❌ 集合未初始化")
            return False
        
        try:
            # 准备插入数据
            data = {
                "modelMd5": [],
                "modelName": [],
                "modelDescription": [],
                "indicatorEnName": [],
                "indicatorCnName": [],
                "categoryEnName": [],
                "categoryCnName": [],
                "sphereEnName": [],
                "sphereCnName": [],
                "embedding": []
            }
            
            for doc in docs:
                data["modelMd5"].append(doc.get("modelMd5", ""))
                data["modelName"].append(doc.get("modelName", ""))
                data["modelDescription"].append(doc.get("modelDescription", ""))
                data["indicatorEnName"].append(doc.get("indicatorEnName", "") or "")
                data["indicatorCnName"].append(doc.get("indicatorCnName", "") or "")
                data["categoryEnName"].append(doc.get("categoryEnName", "") or "")
                data["categoryCnName"].append(doc.get("categoryCnName", "") or "")
                data["sphereEnName"].append(doc.get("sphereEnName", "") or "")
                data["sphereCnName"].append(doc.get("sphereCnName", "") or "")
                
                embedding = doc.get("embedding", [])
                if isinstance(embedding, list) and len(embedding) == 1536:
                    data["embedding"].append(embedding)
                else:
                    # 如果embedding维度不对，使用零向量
                    data["embedding"].append([0.0] * 1536)
            
            # 批量插入
            mr = self.collection.insert(data)
            self.collection.flush()
            
            logger.info(f"✅ 成功插入 {mr.insert_count} 条数据到Milvus")
            return True
            
        except Exception as e:
            logger.error(f"❌ 插入数据失败: {e}")
            return False
    
    def create_index(self) -> bool:
        """创建索引"""
        if not self.collection:
            logger.error("❌ 集合未初始化")
            return False
        
        try:
            # 检查是否已有索引
            if self.collection.has_index():
                logger.info("✅ 索引已存在")
                return True
            
            # 创建HNSW索引
            index_params = {
                "index_type": "HNSW",
                "metric_type": "COSINE",
                "params": {"M": 8, "efConstruction": 200}
            }
            
            self.collection.create_index(
                field_name="embedding",
                index_params=index_params
            )
            
            logger.info("✅ 成功创建向量索引")
            return True
            
        except Exception as e:
            logger.error(f"❌ 创建索引失败: {e}")
            return False
    
    def verify_data(self) -> Dict[str, Any]:
        """验证数据"""
        if not self.collection:
            logger.error("❌ 集合未初始化")
            return {}
        
        try:
            self.collection.load()
            count = self.collection.num_entities
            logger.info(f"✅ Milvus中的数据量: {count}")
            
            # 获取样本数据
            result = self.collection.query(
                expr="",
                output_fields=["modelMd5", "modelName", "embedding"],
                limit=3
            )
            
            return {
                "total_count": count,
                "sample_data": result
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


async def migrate_full(mongodb_uri: str, genai_url: str, milvus_host: str, milvus_port: int):
    """完整迁移：重新生成向量并迁移到Milvus"""
    logger.info("=" * 60)
    logger.info("🚀 开始完整迁移流程（重新生成向量）")
    logger.info("=" * 60)
    
    # 1. 从MongoDB读取数据
    mongo = MongoDBConnector(uri=mongodb_uri)
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
    
    # 3. 迁移到Milvus
    milvus = MilvusConnector(host=milvus_host, port=milvus_port)
    if not milvus.connect():
        return
    
    if not milvus.create_collection():
        milvus.close()
        return
    
    if not milvus.insert_documents(docs):
        milvus.close()
        return
    
    if not milvus.create_index():
        logger.warning("⚠️  索引创建失败，但数据已插入")
    
    # 验证
    verification = milvus.verify_data()
    logger.info(f"✅ 迁移完成！共 {verification.get('total_count', 0)} 条数据")
    
    milvus.close()


def migrate_only(mongodb_uri: str, milvus_host: str, milvus_port: int):
    """只迁移数据，不重新生成向量"""
    logger.info("=" * 60)
    logger.info("🚀 开始数据迁移流程（保留原有向量）")
    logger.info("=" * 60)
    
    # 1. 从MongoDB读取数据
    mongo = MongoDBConnector(uri=mongodb_uri)
    if not mongo.connect():
        return
    
    docs = mongo.read_all_embeddings()
    if not docs:
        logger.error("❌ 未读取到任何数据，中止迁移")
        mongo.close()
        return
    
    logger.info(f"✅ 从MongoDB读取 {len(docs)} 条数据")
    mongo.close()
    
    # 2. 迁移到Milvus
    milvus = MilvusConnector(host=milvus_host, port=milvus_port)
    if not milvus.connect():
        return
    
    if not milvus.create_collection():
        milvus.close()
        return
    
    if not milvus.insert_documents(docs):
        milvus.close()
        return
    
    if not milvus.create_index():
        logger.warning("⚠️  索引创建失败，但数据已插入")
    
    # 验证
    verification = milvus.verify_data()
    logger.info(f"✅ 迁移完成！共 {verification.get('total_count', 0)} 条数据")
    
    milvus.close()


def verify_milvus(milvus_host: str, milvus_port: int):
    """验证Milvus中的数据"""
    logger.info("=" * 60)
    logger.info("🔍 开始验证Milvus数据")
    logger.info("=" * 60)
    
    milvus = MilvusConnector(host=milvus_host, port=milvus_port)
    if not milvus.connect():
        return
    
    verification = milvus.verify_data()
    if verification:
        logger.info(json.dumps(verification, indent=2, ensure_ascii=False))
    
    milvus.close()


def main():
    parser = argparse.ArgumentParser(description="MongoDB Embedding迁移到Milvus")
    parser.add_argument(
        "--mode",
        choices=["full", "migrate-only", "verify"],
        default="full",
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
    
    args = parser.parse_args()
    
    logger.info(f"📋 配置信息:")
    logger.info(f"  - 模式: {args.mode}")
    logger.info(f"  - MongoDB: {args.mongodb_uri}")
    logger.info(f"  - Milvus: {args.milvus_host}:{args.milvus_port}")
    if args.mode == "full":
        logger.info(f"  - GenAI服务: {args.genai_url}")
    
    if args.mode == "full":
        asyncio.run(migrate_full(
            mongodb_uri=args.mongodb_uri,
            genai_url=args.genai_url,
            milvus_host=args.milvus_host,
            milvus_port=args.milvus_port
        ))
    elif args.mode == "migrate-only":
        migrate_only(
            mongodb_uri=args.mongodb_uri,
            milvus_host=args.milvus_host,
            milvus_port=args.milvus_port
        )
    elif args.mode == "verify":
        verify_milvus(
            milvus_host=args.milvus_host,
            milvus_port=args.milvus_port
        )


if __name__ == "__main__":
    main()
