import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import {
    DataType,
    FunctionType,
    IndexType,
    MetricType,
    MilvusClient,
} from '@zilliz/milvus2-sdk-node';

export interface MilvusEmbeddingDocument {
    modelId: string;
    modelMd5: string;
    modelName: string;
    modelDescription: string;
    modelText?: string;
    embeddingSource: string;
    embedding: number[];
}

export interface MilvusConfig {
    host: string;
    port: number;
    username?: string;
    password?: string;
    collectionName: string;
    vectorDim: number;
}

@Injectable()
export class MilvusService {
    private client!: MilvusClient;
    private config!: MilvusConfig;
    private logger = new Logger('MilvusService');

    constructor(private configService: ConfigService) {
        this.initConfig();
        this.initClient();
    }

    private initConfig(): void {
        this.config = {
            host: this.configService.get<string>('MILVUS_HOST', 'localhost'),
            port: this.configService.get<number>('MILVUS_PORT', 19530),
            username: this.configService.get<string>('MILVUS_USERNAME'),
            password: this.configService.get<string>('MILVUS_PASSWORD'),
            collectionName: this.configService.get<string>('MILVUS_COLLECTION', 'modelembeddings'),
            vectorDim: this.configService.get<number>('EMBEDDING_DIM', 3072),
        };
    }

    private initClient(): void {
        this.client = new MilvusClient({
            address: `${this.config.host}:${this.config.port}`,
            username: this.config.username,
            password: this.config.password,
            timeout: 10000,
        });
    }

    private buildModelText(document: Partial<MilvusEmbeddingDocument>): string {
        return [
            `model_name: ${document.modelName || ''}`,
            `model_description: ${document.modelDescription || ''}`,
        ].join('. ');
    }

    private escapeMilvusString(value: string): string {
        return value.replace(/\\/g, '\\\\').replace(/"/g, '\\"');
    }

    private async collectionHasHybridSchema(): Promise<boolean> {
        const description = await this.client.describeCollection({
            collection_name: this.config.collectionName,
        });

        const fields = description.schema?.fields ?? [];
        const fieldNames = new Set(fields.map((field: any) => field.name));
        const sparseField = fields.find((field: any) => field.name === 'sparse');
        const functions = (description as any).functions ?? description.schema?.functions ?? [];
        const hasBm25Function = Array.isArray(functions) && functions.some((func: any) =>
            func?.name === 'model_text_bm25' ||
            String(func?.type).toUpperCase() === 'BM25' ||
            Number(func?.type) === FunctionType.BM25,
        );

        return (
            fieldNames.has('modelText') &&
            fieldNames.has('embedding') &&
            fieldNames.has('sparse') &&
            Boolean(sparseField?.is_function_output) &&
            hasBm25Function
        );
    }

    private async dropCollectionIfExists(): Promise<void> {
        const hasCollection = await this.client.hasCollection({
            collection_name: this.config.collectionName,
        });

        if (!hasCollection.value) {
            return;
        }

        try {
            await this.client.releaseCollection({
                collection_name: this.config.collectionName,
            });
        } catch {
            // The collection may not be loaded.
        }

        await this.client.dropCollection({
            collection_name: this.config.collectionName,
        });
    }

    async connect(): Promise<boolean> {
        try {
            await this.client.connectPromise;
            await this.client.showCollections();
            this.logger.log(`Milvus connected: ${this.config.host}:${this.config.port}`);
            return true;
        } catch (error: unknown) {
            const err = error as any;
            this.logger.error(`Milvus connection failed: ${err.message || String(error)}`);
            return false;
        }
    }

    async createCollection(): Promise<boolean> {
        try {
            const hasCollection = await this.client.hasCollection({
                collection_name: this.config.collectionName,
            });

            if (hasCollection.value) {
                const hasHybridSchema = await this.collectionHasHybridSchema();
                if (hasHybridSchema) {
                    await this.client.loadCollectionSync({
                        collection_name: this.config.collectionName,
                    });
                    this.logger.log(`Collection ${this.config.collectionName} loaded`);
                    return true;
                }

                this.logger.warn(
                    `Collection ${this.config.collectionName} has an old schema; rebuilding for Milvus hybrid search`,
                );
                await this.dropCollectionIfExists();
            }

            await this.client.createCollection({
                collection_name: this.config.collectionName,
                fields: [
                    {
                        name: 'id',
                        data_type: DataType.Int64,
                        is_primary_key: true,
                        autoID: true,
                    },
                    {
                        name: 'modelId',
                        data_type: DataType.VarChar,
                        max_length: 255,
                    },
                    {
                        name: 'modelMd5',
                        data_type: DataType.VarChar,
                        max_length: 255,
                    },
                    {
                        name: 'modelName',
                        data_type: DataType.VarChar,
                        max_length: 1024,
                    },
                    {
                        name: 'modelDescription',
                        data_type: DataType.VarChar,
                        max_length: 8192,
                    },
                    {
                        name: 'modelText',
                        data_type: DataType.VarChar,
                        max_length: 16384,
                        enable_analyzer: true,
                        enable_match: true,
                        analyzer_params: {
                            type: 'chinese',
                        },
                    },
                    {
                        name: 'embeddingSource',
                        data_type: DataType.VarChar,
                        max_length: 255,
                    },
                    {
                        name: 'embedding',
                        data_type: DataType.FloatVector,
                        dim: this.config.vectorDim,
                    },
                    {
                        name: 'sparse',
                        data_type: DataType.SparseFloatVector,
                        is_function_output: true,
                    },
                ],
                functions: [
                    {
                        name: 'model_text_bm25',
                        type: FunctionType.BM25,
                        input_field_names: ['modelText'],
                        output_field_names: ['sparse'],
                        params: {},
                    },
                ],
                index_params: [
                    {
                        field_name: 'embedding',
                        index_type: IndexType.HNSW,
                        metric_type: MetricType.COSINE,
                        params: { M: 8, efConstruction: 200 },
                    },
                    {
                        field_name: 'sparse',
                        index_type: IndexType.SPARSE_INVERTED_INDEX,
                        metric_type: MetricType.BM25,
                        params: {},
                    },
                ],
                enable_dynamic_field: false,
            });

            await this.client.loadCollectionSync({
                collection_name: this.config.collectionName,
            });

            this.logger.log(`Collection ${this.config.collectionName} created for hybrid search`);
            return true;
        } catch (error: unknown) {
            const err = error as any;
            this.logger.error(`Create collection failed: ${err.message || String(error)}`);
            return false;
        }
    }

    private normalizeRows(documents: MilvusEmbeddingDocument[]): MilvusEmbeddingDocument[] {
        const deduped = new Map<string, MilvusEmbeddingDocument>();

        for (const document of documents) {
            if (!document?.modelMd5) {
                continue;
            }

            deduped.set(document.modelMd5, {
                modelId: String(document.modelId || ''),
                modelMd5: String(document.modelMd5 || ''),
                modelName: String(document.modelName || ''),
                modelDescription: String(document.modelDescription || ''),
                modelText: String(document.modelText || this.buildModelText(document)),
                embeddingSource: String(document.embeddingSource || ''),
                embedding: Array.isArray(document.embedding) ? document.embedding : [],
            });
        }

        return Array.from(deduped.values());
    }

    private async deleteByModelMd5s(modelMd5s: string[]): Promise<void> {
        const uniqueMd5s = Array.from(new Set(modelMd5s.filter((item) => !!item)));
        if (uniqueMd5s.length === 0) {
            return;
        }

        const chunkSize = 200;
        for (let i = 0; i < uniqueMd5s.length; i += chunkSize) {
            const chunk = uniqueMd5s.slice(i, i + chunkSize);
            const escaped = chunk.map((item) => `"${this.escapeMilvusString(item)}"`);
            await this.client.delete({
                collection_name: this.config.collectionName,
                filter: `modelMd5 in [${escaped.join(',')}]`,
            });
        }
    }

    private async deleteStaleBySource(activeModelMd5s: string[], embeddingSource: string): Promise<void> {
        const activeSet = new Set(activeModelMd5s.filter((item) => !!item));
        if (activeSet.size === 0) {
            return;
        }

        const queryResult = await this.client.query({
            collection_name: this.config.collectionName,
            filter: `embeddingSource == "${this.escapeMilvusString(embeddingSource)}"`,
            output_fields: ['modelMd5'],
            limit: 100000,
        });

        const rows = (queryResult as any)?.data ?? (queryResult as any)?.results ?? [];
        const staleModelMd5s = (Array.isArray(rows) ? rows : [])
            .map((item: any) => item?.modelMd5)
            .filter((item: any) => typeof item === 'string' && !activeSet.has(item));

        await this.deleteByModelMd5s(staleModelMd5s);
    }

    async upsertDocuments(
        documents: MilvusEmbeddingDocument[],
        activeModelMd5s: string[],
        embeddingSource: string,
    ): Promise<boolean> {
        try {
            await this.createCollection();

            const rows = this.normalizeRows(documents)
                .filter((doc) => {
                    const valid = doc.embedding.length === this.config.vectorDim;
                    if (!valid) {
                        this.logger.warn(`Skip invalid embedding dimension for model ${doc.modelMd5 || doc.modelId}`);
                    }
                    return valid;
                })
                .map((doc) => ({
                    modelId: doc.modelId,
                    modelMd5: doc.modelMd5,
                    modelName: doc.modelName,
                    modelDescription: doc.modelDescription,
                    modelText: doc.modelText || this.buildModelText(doc),
                    embeddingSource: doc.embeddingSource,
                    embedding: doc.embedding,
                }));

            if (rows.length === 0) {
                await this.deleteStaleBySource(activeModelMd5s, embeddingSource);
                this.logger.warn('No valid documents to insert; stale Milvus rows cleaned only');
                return true;
            }

            await this.deleteByModelMd5s(rows.map((row) => row.modelMd5));

            const chunkSize = 500;
            for (let i = 0; i < rows.length; i += chunkSize) {
                await this.client.insert({
                    collection_name: this.config.collectionName,
                    data: rows.slice(i, i + chunkSize),
                });
            }

            await this.client.flush({
                collection_names: [this.config.collectionName],
            });

            await this.deleteStaleBySource(activeModelMd5s, embeddingSource);
            await this.client.loadCollectionSync({
                collection_name: this.config.collectionName,
            });

            this.logger.log(`Inserted ${rows.length} model embeddings into Milvus`);
            return true;
        } catch (error: unknown) {
            const err = error as any;
            this.logger.error(`Insert documents failed: ${err.message || String(error)}`);
            return false;
        }
    }

    async insertDocuments(documents: MilvusEmbeddingDocument[]): Promise<boolean> {
        return this.upsertDocuments(documents, [], 'manual');
    }

    async createIndex(): Promise<boolean> {
        try {
            await this.createCollection();
            this.logger.log('Milvus indexes are ready');
            return true;
        } catch (error: unknown) {
            const err = error as any;
            this.logger.error(`Create index failed: ${err.message || String(error)}`);
            return false;
        }
    }

    async getExistingDocumentMap(embeddingSource: string): Promise<Map<string, MilvusEmbeddingDocument>> {
        const existing = new Map<string, MilvusEmbeddingDocument>();

        try {
            await this.createCollection();

            const queryResult = await this.client.query({
                collection_name: this.config.collectionName,
                filter: `embeddingSource == "${this.escapeMilvusString(embeddingSource)}"`,
                output_fields: ['modelId', 'modelMd5', 'modelName', 'modelDescription', 'modelText', 'embeddingSource'],
                limit: 100000,
            });

            const rows = (queryResult as any)?.data ?? (queryResult as any)?.results ?? [];
            for (const row of Array.isArray(rows) ? rows : []) {
                const modelId = String(row?.modelId || '');
                if (!modelId) {
                    continue;
                }

                existing.set(modelId, {
                    modelId,
                    modelMd5: String(row?.modelMd5 || ''),
                    modelName: String(row?.modelName || ''),
                    modelDescription: String(row?.modelDescription || ''),
                    modelText: String(row?.modelText || ''),
                    embeddingSource: String(row?.embeddingSource || ''),
                    embedding: [],
                });
            }
        } catch (error: unknown) {
            const err = error as any;
            this.logger.warn(`Read existing Milvus documents failed; regenerating as needed: ${err.message || String(error)}`);
        }

        return existing;
    }

    async assertEmbeddingSourceConsistent(expectedSource: string): Promise<void> {
        await this.createCollection();

        const queryResult = await this.client.query({
            collection_name: this.config.collectionName,
            filter: `embeddingSource != "${this.escapeMilvusString(expectedSource)}"`,
            output_fields: ['embeddingSource'],
            limit: 10,
        });

        const rows = (queryResult as any)?.data ?? (queryResult as any)?.results ?? [];
        const conflicts = Array.isArray(rows)
            ? Array.from(
                new Set(
                    rows
                        .map((row: any) => String(row?.embeddingSource || '').trim())
                        .filter((value: string) => value.length > 0),
                ),
            )
            : [];

        if (conflicts.length > 0) {
            throw new Error(
                `Milvus embeddingSource 与当前配置不一致。期望: "${expectedSource}"，检测到历史来源: ${conflicts.join(', ')}`,
            );
        }
    }

    async search(embedding: number[], limit: number = 10, filter?: string): Promise<any[]> {
        try {
            await this.createCollection();

            const searchResult = await this.client.search({
                collection_name: this.config.collectionName,
                data: [embedding],
                anns_field: 'embedding',
                limit,
                filter,
                output_fields: ['modelId', 'modelMd5', 'modelName', 'modelDescription', 'embeddingSource'],
                metric_type: MetricType.COSINE,
                params: { ef: 128 },
            });

            const rows = (searchResult as any)?.results ?? [];
            const firstBatch = Array.isArray(rows) ? rows[0] : [];
            return Array.isArray(firstBatch) ? firstBatch.map((item: any) => ({
                id: item.id,
                score: item.score,
                modelId: item.modelId,
                modelMd5: item.modelMd5,
                modelName: item.modelName,
                modelDescription: item.modelDescription,
                embeddingSource: item.embeddingSource,
            })) : [];
        } catch (error: unknown) {
            const err = error as any;
            this.logger.error(`Vector search failed: ${err.message || String(error)}`);
            return [];
        }
    }

    async hybridSearch(queryText: string, embedding: number[], limit: number = 10, filter?: string): Promise<any[]> {
        try {
            await this.createCollection();

            const searchLimit = Math.max(limit, 10);
            const hybridRequests: any[] = [
                {
                    data: [embedding],
                    anns_field: 'embedding',
                    limit: searchLimit,
                    filter,
                    metric_type: MetricType.COSINE,
                    params: { ef: 128 },
                },
                {
                    data: [queryText],
                    anns_field: 'sparse',
                    limit: searchLimit,
                    filter,
                    metric_type: MetricType.BM25,
                    params: {},
                },
            ];
            const searchResult = await this.client.hybridSearch({
                collection_name: this.config.collectionName,
                data: hybridRequests,
                rerank: {
                    strategy: 'weighted',
                    params: { weights: [0.65, 0.35] },
                },
                limit,
                output_fields: ['modelId', 'modelMd5', 'modelName', 'modelDescription', 'embeddingSource'],
            });

            const rows = (searchResult as any)?.results ?? [];
            return Array.isArray(rows) ? rows.map((item: any) => ({
                id: item.id,
                score: item.score,
                modelId: item.modelId,
                modelMd5: item.modelMd5,
                modelName: item.modelName,
                modelDescription: item.modelDescription,
                embeddingSource: item.embeddingSource,
            })) : [];
        } catch (error: unknown) {
            const err = error as any;
            this.logger.error(`Hybrid search failed: ${err.message || String(error)}`);
            return [];
        }
    }

    async getCollectionStats(): Promise<any> {
        try {
            await this.createCollection();
            return await this.client.getCollectionStatistics({
                collection_name: this.config.collectionName,
            });
        } catch (error: unknown) {
            const err = error as any;
            this.logger.error(`Get collection stats failed: ${err.message || String(error)}`);
            return {};
        }
    }

    async flush(): Promise<boolean> {
        try {
            await this.client.flush({
                collection_names: [this.config.collectionName],
            });
            this.logger.log('Milvus data flushed');
            return true;
        } catch (error: unknown) {
            const err = error as any;
            this.logger.error(`Flush failed: ${err.message || String(error)}`);
            return false;
        }
    }

    async deleteCollection(): Promise<boolean> {
        try {
            await this.dropCollectionIfExists();
            this.logger.log(`Collection ${this.config.collectionName} deleted`);
            return true;
        } catch (error: unknown) {
            const err = error as any;
            this.logger.error(`Delete collection failed: ${err.message || String(error)}`);
            return false;
        }
    }
}
