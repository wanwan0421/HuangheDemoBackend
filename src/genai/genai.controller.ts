import { Controller, Post, Body, Get, Logger, HttpCode, HttpStatus } from '@nestjs/common';
import { GenAIService } from './genai.service';
import { MilvusService } from './milvus.service';

@Controller('genai')
export class GenaiController {
    private logger = new Logger('GenaiController');

    constructor(
        private genaiService: GenAIService,
        private milvusService: MilvusService,
    ) {}

    @Post('embeddings')
    @HttpCode(HttpStatus.OK)
    async generateEmbeddings(@Body() body: { texts: string[] }) {
        try {
            if (!body.texts || !Array.isArray(body.texts)) {
                return {
                    success: false,
                    error: 'Invalid input: texts must be an array',
                    embeddings: [],
                };
            }

            const embeddings = await this.genaiService.generateEmbeddings(body.texts);

            return {
                success: true,
                embeddings,
                count: embeddings.length,
            };
        } catch (error: any) {
            this.logger.error(`❌ Embedding生成失败: ${error?.message || String(error)}`);
            return {
                success: false,
                error: error?.message || String(error),
                embeddings: [],
            };
        }
    }

    @Post('embedding')
    @HttpCode(HttpStatus.OK)
    async generateEmbedding(@Body() body: { text: string }) {
        try {
            if (!body.text || typeof body.text !== 'string') {
                return {
                    success: false,
                    error: 'Invalid input: text must be a string',
                    embedding: [],
                };
            }

            const embedding = await this.genaiService.generateEmbedding(body.text);

            return {
                success: true,
                embedding,
                dimension: embedding.length,
            };
        } catch (error: any) {
            this.logger.error(`❌ Embedding生成失败: ${error?.message || String(error)}`);
            return {
                success: false,
                error: error?.message || String(error),
                embedding: [],
            };
        }
    }

    @Get('health')
    @HttpCode(HttpStatus.OK)
    async health() {
        return {
            status: 'ok',
            timestamp: new Date().toISOString(),
        };
    }

    // Milvus相关端点
    @Post('milvus/init')
    @HttpCode(HttpStatus.OK)
    async initMilvus() {
        try {
            const connected = await this.milvusService.connect();
            if (!connected) {
                return { success: false, message: 'Milvus连接失败' };
            }

            const collectionCreated = await this.milvusService.createCollection();
            if (!collectionCreated) {
                return { success: false, message: '集合创建失败' };
            }

            const indexCreated = await this.milvusService.createIndex();

            return {
                success: true,
                message: 'Milvus初始化完成',
                indexCreated,
            };
        } catch (error: any) {
            this.logger.error(`❌ Milvus初始化失败: ${error?.message || String(error)}`);
            return {
                success: false,
                error: error?.message || String(error),
            };
        }
    }

    @Post('milvus/insert')
    @HttpCode(HttpStatus.OK)
    async insertToMilvus(@Body() body: { documents: any[] }) {
        try {
            if (!body.documents || !Array.isArray(body.documents)) {
                return {
                    success: false,
                    error: 'Invalid input: documents must be an array',
                };
            }

            const inserted = await this.milvusService.insertDocuments(body.documents);

            return {
                success: inserted,
                count: body.documents.length,
            };
        } catch (error: any) {
            this.logger.error(`❌ Milvus插入失败: ${error?.message || String(error)}`);
            return {
                success: false,
                error: error?.message || String(error),
            };
        }
    }

    @Get('milvus/stats')
    @HttpCode(HttpStatus.OK)
    async getMilvusStats() {
        try {
            const stats = await this.milvusService.getCollectionStats();
            return {
                success: true,
                stats,
            };
        } catch (error: any) {
            this.logger.error(`❌ 获取统计信息失败: ${error?.message || String(error)}`);
            return {
                success: false,
                error: error?.message || String(error),
            };
        }
    }

    @Post('milvus/search')
    @HttpCode(HttpStatus.OK)
    async searchInMilvus(@Body() body: { embedding: number[]; limit?: number }) {
        try {
            if (!body.embedding || !Array.isArray(body.embedding)) {
                return {
                    success: false,
                    error: 'Invalid input: embedding must be an array',
                    results: [],
                };
            }

            const results = await this.milvusService.search(body.embedding, body.limit || 10);

            return {
                success: true,
                results,
                count: results.length,
            };
        } catch (error: any) {
            this.logger.error(`❌ Milvus搜索失败: ${error?.message || String(error)}`);
            return {
                success: false,
                error: error?.message || String(error),
                results: [],
            };
        }
    }

    @Post('milvus/flush')
    @HttpCode(HttpStatus.OK)
    async flushMilvus() {
        try {
            const flushed = await this.milvusService.flush();
            return {
                success: flushed,
                message: flushed ? '数据已flush' : 'Flush失败',
            };
        } catch (error: any) {
            this.logger.error(`❌ Milvus flush失败: ${error?.message || String(error)}`);
            return {
                success: false,
                error: error?.message || String(error),
            };
        }
    }
}
