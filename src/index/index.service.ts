import { Injectable } from '@nestjs/common';
import { indexSystem } from './schemas/index.schema';
import { ModelEmbedding } from './schemas/modelEmbedding.schema';
import { indicators } from './interfaces/returnIndex.interface';
import { InjectModel } from '@nestjs/mongoose';
import { Model } from 'mongoose';
import { GenAIService } from 'src/genai/genai.service';

@Injectable()
export class IndexService {
    constructor(
        @InjectModel(indexSystem.name) private indexModel: Model<indexSystem & Document>,
        @InjectModel(ModelEmbedding.name) private ModelEmbeddingModel: Model<ModelEmbedding & Document>,
        private genAIService: GenAIService,
    ) { }

    // async onModuleInit() {
    //     console.log('🚀 正在初始化指标向量数据...');
    //     try {
    //         await this.initVectorData();
    //         await this.initModelVectorData();
    //         console.log('✅ 指标向量初始化完成');
    //     } catch (error) {
    //         console.error('❌ 指标向量初始化失败:', error);
    //     }
    // }

    // 获取数据库中的指标体系，即二级指标
    // 获取二级指标中英文名+连接的模型
    public async getIndexSystem(): Promise<indicators[]> {
        const data = await this.indexModel.find({}, { categories: 1, _id: 0 }).exec();
        const indicators = data.flatMap(sphere =>
            sphere.categories.flatMap(category =>
                category.indicators
            )
        );

        const returnIndicators = indicators.map(indicator => ({
            name_en: indicator.name_en,
            name_cn: indicator.name_cn,
            models: indicator.models.map(model => model.model_name)
        }));

        return returnIndicators;
    }

    /**
     * 遍历数据库将“指标英文名称+指标中文名称+模型名称”拼接为一段话生成embedding并存入到indexSystem
     */
    public async initVectorData() {
        const data = await this.indexModel.find();
        console.log(`查找到 ${data.length} 条领域数据`);
        for (const sphere of data) {
            // 收集待处理的指标
            const tasks: { indicator: any, textToEmbed: string }[] = [];

            for (const category of sphere.categories) {
                for (const indicator of category.indicators) {
                    // 只有当向量为空时才生成，避免重复消耗 Token
                    if (!indicator.embedding || indicator.embedding.length === 0) {
                        const textToEmbed = `index_en: ${indicator.name_en}. index_cn: ${indicator.name_cn}. model: ${indicator.models.map(m => m.model_name).join(', ')}`;
                        tasks.push({ indicator, textToEmbed })
                    }
                }
            }

            if (tasks.length === 0) continue;

            // 每10个指标分一组发送
            const CHUNK_SIZE = 10;
            for (let i = 0; i < tasks.length; i += CHUNK_SIZE) {
                const chunk = tasks.slice(i, i + CHUNK_SIZE);
                const texts = chunk.map(t => t.textToEmbed)
                console.log(`正在批量同步处理${chunk.length}条数据...`);

                let success = false;
                let retryCount = 0;

                while (!success && retryCount < 3) {
                    console.log(`🚀 [${sphere.sphere_name}] 正在处理批次 ${i / CHUNK_SIZE + 1}...`);
                    const vectors = await this.genAIService.generateEmbeddings(texts);

                    if (vectors.length > 0) {
                        vectors.forEach((vec, idx) => {
                            chunk[idx].indicator.embedding = vec;
                        });
                        console.log(`成功获取${vectors.length}条向量`);
                        success = true;
                        await new Promise(r => setTimeout(r, 30000));
                    } else {
                        retryCount++;
                        console.warn(`  ⚠️ 触发频率限制，进入 65 秒深度冷却 (重试第 ${retryCount} 次)...`);
                        // 🚩 遇到 429 后，必须休息超过 60 秒
                        await new Promise(r => setTimeout(r, 65000));
                    }
                }
            }

            sphere.markModified('categories');
            await sphere.save();
        }
    }

    /**
     * 遍历数据库将“模型名称+模型描述”拼接为一段话为每个模型生成embedding并存入到indexSystem
     */
    public async initModelVectorData() {
        const data = await this.indexModel.find();
        console.log(`查找到 ${data.length} 条领域数据`);

        // 先判断原有的model是否已经获取了embedding
        const existingModel = await this.ModelEmbeddingModel
            .find(
                { 
                    modelMd5: { $exists: true, $ne: "" }, 
                    embedding: { $exists: true, $not: { $size: 0 } } 
                },
                { modelMd5: 1 })
            .lean();
        const existingModelSet = new Set(existingModel.map(e => e.modelMd5));
        const currentTaskModelSet = new Set();
        const modelTasks: any[] = [];

        for (const sphere of data) {
            for (const category of sphere.categories) {
                for (const indicator of category.indicators) {
                    for (const model of indicator.models) {

                        if (existingModelSet.has(model.model_id) || currentTaskModelSet.has(model.model_id)) continue;

                        modelTasks.push({
                            modelMd5: model.model_id,
                            modelName: model.model_name,
                            modelDescription: model.description,
                            indicatorEnName: indicator.name_en,
                            indicatorCnName: indicator.name_cn,
                            categoryEnName: category.category_id,
                            categoryCnName: category.category_name,
                            sphereEnName: sphere.sphere_id,
                            sphereCnName: sphere.sphere_name,
                            textToEmbed: `model_name: ${model.model_name}. model_description: ${model.description}.`
                        });

                        currentTaskModelSet.add(model.model_id);
                    }
                }
            }

            
        }

        if (modelTasks.length === 0) {
            console.log("没有检测到新模型，无需更新向量数据。");
            return;
        }

        // 分批生成 embedding
        const CHUNK_SIZE = 50;
        for (let i = 0; i < modelTasks.length; i += CHUNK_SIZE) {
            try {
                const chunk = modelTasks.slice(i, i + CHUNK_SIZE);
                const texts = chunk.map(t => t.textToEmbed);

                const vectors = await this.genAIService.generateEmbeddings(texts);

                if (!vectors || !Array.isArray(vectors) || vectors.length !== chunk.length) {
                    console.error(`⚠️ 批次索引 ${i} 失败：API 返回数据无效或受限。跳过此批次。`);
                    await new Promise(r => setTimeout(r, 60000)); 
                    continue;
                }

                const modelVectors = chunk.map((t, i) => ({
                    modelMd5: t.modelMd5,
                    modelName: t.modelName,
                    modelDescription: t.modelDescription,
                    indicatorEnName: t.indicatorEnName,
                    indicatorCnName: t.indicatorCnName,
                    categoryEnName: t.categoryEnName,
                    categoryCnName: t.categoryCnName,
                    sphereEnName: t.sphereEnName,
                    sphereCnName: t.sphereCnName,
                    embedding: vectors[i]
                }));

                await this.ModelEmbeddingModel.insertMany(modelVectors);
                await new Promise(r => setTimeout(r, 30000));
            } catch (error) {
                console.log(`处理批次起始索引为 ${i} 的数据时出错:`, error);
            }
            
        }
        
        console.log(`✅ 成功写入 ${modelTasks.length} 条模型 embedding`);
    }

    /**
     * 从指标库找与用户输入相关的10个指标信息
     * @param userQueryVector 用户输入转换为的向量
     * @returns 返回10个相关指标信息
     */
    public async findRelevantIndex(userQueryVector: number[]) {
        const data = await this.indexModel.find({}, { categories: 1, _id: 0 }).exec();
        const indicators = data.flatMap(sphere =>
            sphere.categories.flatMap(category =>
                category.indicators
            )
        );

        // 计算余弦相似度
        const consineSimilarity = (a: number[], b: number[]) => {
            let dot = 0, na = 0, nb = 0;
            for (let i = 0; i < a.length; i++) {
                dot += a[i] * b[i];
                na += a[i] * a[i];
                nb += b[i] * b[i];
            }
            return dot / (Math.sqrt(na) * Math.sqrt(nb));
        };

        const results = indicators.filter(ind => ind.embedding && ind.embedding.length > 0)
            .map(indicator => ({
                name_en: indicator.name_en,
                name_cn: indicator.name_cn,
                score: consineSimilarity(userQueryVector, indicator.embedding)
            }))
            .sort((a, b) => b.score - a.score)
            .slice(0, 10);

        return results
    }

    /**
     * 从modelEmbedding模型向量库找与用户输入相关的5个模型详细信息
     * 
     * @param userQueryVector 用户输入转换为的向量
     * @param modelIds 模型的MD5值
     * @returns 返回5个相关模型信息
     */
    public async findRelevantModel(userQueryVector: number[], modelIds: string[]) {
        const data = await this.ModelEmbeddingModel.find({ modelMd5: { $in: modelIds} }).lean();

        // 计算余弦相似度
        const consineSimilarity = (a: number[], b: number[]) => {
            let dot = 0, na = 0, nb = 0;
            for (let i = 0; i < a.length; i++) {
                dot += a[i] * b[i];
                na += a[i] * a[i];
                nb += b[i] * b[i];
            }
            return dot / (Math.sqrt(na) * Math.sqrt(nb));
        };

        const rankedModels = data.filter(model => model.embedding && model.embedding.length > 0 )
            .map(m => ({
                modelMd5: m.modelMd5,
                modelName: m.modelName,
                modelDescription: m.modelDescription,
                score: consineSimilarity(userQueryVector, m.embedding)
            }))
            .sort((a, b) => b.score - a.score)
            .slice(0, 5);

        return rankedModels
    }

    /**
     * 根据indicator名称从指标库找详细信息
     * @param indicatorNames 指标名称
     * @returns 返回相关指标信息
     */
    public async getIndicatorByNames(indicatorNames: string[]) {
        const data = await this.indexModel.find({}, { categories: 1, _id: 0 }).lean();

        const indicators = data.flatMap(sphere => sphere.categories.flatMap(category => category.indicators));

        return indicators.filter(indicator =>
            indicatorNames.includes(indicator.name_en) || indicatorNames.includes(indicator.name_cn)
        );
    }
}
