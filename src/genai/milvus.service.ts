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
    modelMdl?: string;
    modelMdlJson?: Record<string, any>;
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

    private normalizeText(value: unknown, maxLength = 0): string {
        if (typeof value !== 'string') {
            return '';
        }

        const normalized = value.replace(/\s+/g, ' ').trim();
        if (!normalized) {
            return '';
        }

        return maxLength > 0 ? normalized.slice(0, maxLength) : normalized;
    }

    private normalizeTextList(value: unknown): string[] {
        const candidates = Array.isArray(value)
            ? value.flatMap((item) => this.normalizeTextList(item))
            : this.normalizeText(value)
                .replace(/[;，]/g, ',')
                .split(',')
                .map((item) => item.trim())
                .filter((item) => item.length > 0);

        return Array.from(new Set(candidates));
    }

    private extractMdlSummary(document: Partial<MilvusEmbeddingDocument>): string {
        const rawMdl = document.modelMdl || (document.modelMdlJson as any)?.mdl?.raw || '';
        const normalized = this.normalizeText(rawMdl, 2400);
        if (!normalized) {
            return '';
        }

        return normalized
            .replace(/<[^>]+>/g, ' ')
            .replace(/&[a-zA-Z]+;/g, ' ')
            .replace(/\s+/g, ' ')
            .trim()
            .slice(0, 1200);
    }

    private buildModelText(document: Partial<MilvusEmbeddingDocument>): string {
        const mdlJson = document.modelMdlJson ?? {};
        const mdl = (mdlJson as any).mdl ?? {};

        const parts: string[] = [];
        const push = (label: string, value: unknown, maxLength = 0): void => {
            const text = this.normalizeText(value, maxLength);
            if (text) {
                parts.push(`${label}: ${text}`);
            }
        };

        push('model_name', document.modelName);
        push('model_description', document.modelDescription, 1200);
        push('mdl_summary', this.extractMdlSummary(document), 1200);

        return parts.join('. ');
    }

    private escapeMilvusString(value: string): string {
        return value.replace(/\\/g, '\\\\').replace(/"/g, '\\"');
    }

    private inferHybridWeights(queryText: string): { profile: string; weights: [number, number] } {
        const text = this.normalizeText(queryText);
        const lower = text.toLowerCase();
        const asciiTokens = text.match(/[A-Za-z][A-Za-z0-9_./-]*/g) || [];
        const hasIdentifier = asciiTokens.some((token) =>
            token.includes('_') ||
            token.includes('/') ||
            token.includes('.') ||
            /\d/.test(token),
        );
        const hasAcronym = asciiTokens.some((token) =>
            token.length >= 2 && (token.match(/[A-Z]/g) || []).length >= 2,
        );
        const parameterTerms = [
            '参数', '输入', '输出', '文件', '格式', '支持', '导入', '设置',
            'input', 'output', 'parameter', 'param', 'data', 'file',
        ];
        const intentTerms = ['我想', '有没有', '推荐', '哪个', '哪一个', '比较好', '适合', '怎么选', '用什么'];

        let keywordSignal = 0;
        keywordSignal += hasIdentifier ? 2 : 0;
        keywordSignal += hasAcronym ? 2 : 0;
        keywordSignal += parameterTerms.filter((term) => lower.includes(term) || text.includes(term)).length;

        const isColloquial = intentTerms.some((term) => text.includes(term));
        if (isColloquial && keywordSignal <= 1) {
            return { profile: 'dense_heavy', weights: [0.9, 0.1] };
        }

        if (keywordSignal >= 3) {
            return { profile: 'keyword_aware', weights: [0.65, 0.35] };
        }

        return { profile: 'balanced', weights: [0.8, 0.2] };
    }

    private extractQueryRows(queryResult: any): any[] {
        if (Array.isArray(queryResult)) {
            return queryResult;
        }

        const rows = queryResult?.data ?? queryResult?.results ?? [];
        return Array.isArray(rows) ? rows : [];
    }

    private async queryAllRowsByExpr(expr: string, outputFields: string[]): Promise<any[]> {
        const batchSize = 1000;
        const maxPages = 50;
        let offset = 0;
        const allRows: any[] = [];

        for (let page = 0; page < maxPages; page += 1) {
            const queryResult = await this.client.query({
                collection_name: this.config.collectionName,
                filter: expr,
                expr,
                output_fields: outputFields,
                limit: batchSize,
                offset,
            } as any);

            const rows = this.extractQueryRows(queryResult);
            if (rows.length === 0) {
                break;
            }

            allRows.push(...rows);

            if (rows.length < batchSize) {
                break;
            }

            offset += rows.length;
        }

        return allRows;
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

    private async deleteStaleByMd5(activeModelMd5s: string[]): Promise<void> {
        const activeSet = new Set(activeModelMd5s.filter((item) => !!item));
        if (activeSet.size === 0) {
            return;
        }

        const rows = await this.queryAllRowsByExpr('', ['modelMd5']);
        const staleModelMd5s = (Array.isArray(rows) ? rows : [])
            .map((item: any) => item?.modelMd5)
            .filter((item: any) => typeof item === 'string' && !activeSet.has(item));

        if (staleModelMd5s.length > 0) {
            this.logger.log(`Deleting ${staleModelMd5s.length} stale model embeddings`);
            await this.deleteByModelMd5s(staleModelMd5s);
        }
    }

    async upsertDocuments(
        documents: MilvusEmbeddingDocument[],
        activeModelMd5s: string[]
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
                await this.deleteStaleByMd5(activeModelMd5s);
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

            await this.deleteStaleByMd5(activeModelMd5s);
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
        return this.upsertDocuments(documents, []);
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

    async getExistingDocumentMap(): Promise<Map<string, MilvusEmbeddingDocument>> {
        const existing = new Map<string, MilvusEmbeddingDocument>();

        try {
            await this.createCollection();

            const rows = await this.queryAllRowsByExpr(
                '',
                ['modelMd5', 'modelId', 'modelName', 'modelDescription', 'modelText', 'embeddingSource'],
            );

            this.logger.log(`Milvus existing model embeddings fetched (by modelMd5): ${rows.length}`);
            for (const row of Array.isArray(rows) ? rows : []) {
                const modelMd5 = String(row?.modelMd5 || '');
                if (!modelMd5) {
                    continue;
                }

                existing.set(modelMd5, {
                    modelId: String(row?.modelId || ''),
                    modelMd5: modelMd5,
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

            const searchLimit = Math.max(limit * 5, 50);
            const hybridProfile = this.inferHybridWeights(queryText);
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
                    params: { weights: hybridProfile.weights },
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
