import { Injectable } from '@nestjs/common';
import { IndexSystem } from './schemas/index.schema';
import { thirdIndex } from './interfaces/thirdIndex.interface';
import { indicators } from './interfaces/returnIndex.interface';
import { InjectModel } from '@nestjs/mongoose';
import { Model } from 'mongoose';
import { GenAIService } from 'src/llm-agent/genai.service';

@Injectable()
export class IndexService {
    constructor(
        @InjectModel(IndexSystem.name) private indexModel: Model<IndexSystem & Document>,
        private genAIService: GenAIService,
    ){}

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
        for (const sphere of data) {
            let isModified = false;
            for (const category of sphere.categories) {
                for (const indicator of category.indicators) {
                    // 只有当向量为空时才生成，避免重复消耗 Token
                    if (!indicator.embedding || indicator.embedding.length === 0) {
                        const textToEmbed = `index_en: ${indicator.name_en}. index_cn: ${indicator.name_cn}. model: ${indicator.models.map(m => m.model_name).join(', ')}`;
                        indicator.embedding = await this.genAIService.generateEmbedding(textToEmbed);
                        isModified = true;
                    }
                }
            }
            if (isModified) {
                await sphere.save();
            }
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
                models: indicator.models.map(model =>  model.model_name),
                score:score
            }
        })

        return results.sort((a, b) => b.score - a.score).slice(0, 20);
    }
}
