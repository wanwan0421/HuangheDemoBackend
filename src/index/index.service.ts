import { Injectable } from '@nestjs/common';
import { index } from './schemas/index.schema';
import { thirdIndex } from './interfaces/thirdIndex.interface';
import { indicators } from './interfaces/returnIndex.interface';
import { InjectModel } from '@nestjs/mongoose';
import { Model } from 'mongoose';
import { GenAIService } from 'src/genai/genai.service';
import { delay } from 'rxjs';

@Injectable()
export class IndexService {
    constructor(
        @InjectModel(index.name) private indexModel: Model<index & Document>,
        private genAIService: GenAIService,
    ){}

    async onModuleInit() {
        console.log('🚀 正在初始化指标向量数据...');
        try {
            await this.initVectorData();
            console.log('✅ 指标向量初始化完成');
        } catch (error) {
            console.error('❌ 指标向量初始化失败:', error);
        }
    }

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
            models: indicator.models.map(model =>  model.model_name)
        }));

        return returnIndicators;
    }

    /**
     * 遍历数据库将“指标名称+模型名称+模型描述”拼接为一段话生成向量并存入数据库
     */
    public async initVectorData() {
        const data = await this.indexModel.find();
        console.log(`🔍 查找到 ${data.length} 条领域数据`);
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

            // 每50个指标分一组发送
            const CHUNK_SIZE = 10;
            for (let i = 0; i < tasks.length; i += CHUNK_SIZE) {
                const chunk = tasks.slice(i, i + CHUNK_SIZE);
                const texts = chunk.map(t => t.textToEmbed)
                console.log(`正在批量同步处理${chunk.length}条数据...`);

                let success = false;
                let retryCount = 0;

                while(!success && retryCount < 3) {
                    console.log(`🚀 [${sphere.sphere_name}] 正在处理批次 ${i/CHUNK_SIZE + 1}...`);
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
     * 从指标库找与用户输入相关的20个指标信息
     * @param prompt 用户输入转换为的向量
     * @returns 返回20个相关指标信息
     */
    public async findRelevantIndex(userQueryVector: number[]) {
        const data = await this.indexModel.find({}, { categories: 1, _id: 0 }).exec();
        const indicators = data.flatMap(sphere => 
            sphere.categories.flatMap(category => 
                category.indicators
            )
        );

        // 计算余弦相似度
        const results = indicators.filter(ind => ind.embedding && ind.embedding.length > 0)
        .map(indicator => {
            let score = 0;
            for (let i = 0; i < userQueryVector.length; i++) {
                score += userQueryVector[i] * indicator.embedding[i]
            }

            return {
                name_en: indicator.name_en,
                name_cn: indicator.name_cn,
                models: indicator.models.map(model =>  model.model_name).slice(0, 10),
                score:score
            }
        })

        return results.sort((a, b) => b.score - a.score).slice(0, 5);
    }
}
