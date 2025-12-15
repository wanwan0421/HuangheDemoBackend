import { Injectable } from '@nestjs/common';
import { IndexSystem } from './schemas/index.schema';
import { secondIndex } from './interfaces/secondIndex.interface'
import { InjectModel } from '@nestjs/mongoose';
import { Model } from 'mongoose';

@Injectable()
export class IndexService {
    constructor(
        @InjectModel(IndexSystem.name) private indexModel: Model<IndexSystem & Document>,
    ){}

    // 获取数据库中的指标体系，即二级指标
    // 获取二级指标中英文名+连接的模型
    public async getIndexSystem(): Promise<secondIndex[]> {
        const data = await this.indexModel.find({}, { categories: 1, _id: 0 }).exec();
        const indicators = data.flatMap(sphere => 
            sphere.categories.flatMap(category => 
                category.indicators
            )
        );


        return indicators.map(indicator => ({
            secondIndex_En: indicator.name_en,
            secondIndex_Cn: indicator.name_cn,

        })) as secondIndex[];

    }
}
