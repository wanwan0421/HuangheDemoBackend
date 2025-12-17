import { Injectable } from '@nestjs/common';
import { IndexSystem } from './schemas/index.schema';
import { thirdIndex } from './interfaces/thirdIndex.interface';
import { indicators } from './interfaces/returnIndex.interface';
import { InjectModel } from '@nestjs/mongoose';
import { Model } from 'mongoose';

@Injectable()
export class IndexService {
    constructor(
        @InjectModel(IndexSystem.name) private indexModel: Model<IndexSystem & Document>,
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
}
