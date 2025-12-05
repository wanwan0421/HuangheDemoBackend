import { Injectable } from '@nestjs/common';
import { HttpService } from '@nestjs/axios';
import { ResourceDto, ResourceType } from './dto/resource.dto';

// 假设的内存数据库存储资源元数据
const MOCK_RESOURCES: ResourceDto[] = [
    {
        id: 'model-a',
        type: ResourceType.MODEL,
        name: '气候预测模型A',
        description: '基于时间序列的降雨量预测模型',
        input_requirements: [{ name: '历史数据', type: 'array<number>' }],
        output_requirements: [{ name: '预测值', type: 'number' }],
        external_url: 'http://external-model-service.com/api/predict/a',
    },
    {
        id: 'method-normalize',
        type: ResourceType.METHOD,
        name: '数据归一化方法',
        description: '将数据缩放到 [0, 1] 区间',
        input_requirements: [{ name: '原始数据', type: 'array<number>' }],
        output_requirements: [{ name: '归一化数据', type: 'array<number>' }],
        external_url: 'http://data-process-service.com/api/normalize',
    },
];

@Injectable()
export class ResourceService {
    constructor(private readonly httpService: HttpService) {}

    // get resources list by type
    findAll(type?: ResourceType): ResourceDto[] {
        if (type) {
            return MOCK_RESOURCES.filter(resource => resource.type === type);
        }
        return MOCK_RESOURCES;
    }

    // get resource by id
    findOne(id: string): ResourceDto {
        const resource = MOCK_RESOURCES.find(resource => resource.id === id);
        if (!resource) {
            throw new Error(`Resource with id ${id} not found`);
        }
        return resource;
    }

    // invoke external resource

}
