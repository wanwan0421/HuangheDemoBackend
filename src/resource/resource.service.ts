import { Injectable, Logger } from '@nestjs/common';
import { HttpService } from '@nestjs/axios';
import { ConfigService } from '@nestjs/config';
import { ResourceDto, ResourceType } from './dto/modelResourceIO.dto';
import { ModelResource } from './entities/modelResource.entity';
import { Md5Item, OnePageMd5Result, PortalMd5Data } from './interfaces/portalSync.interface';
import { firstValueFrom } from 'rxjs';

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
    private readonly logger = new Logger(ResourceService.name); // 日志记录器
    private readonly portalLocation: string;
    private readonly portalToken: string;
    private readonly pageSize = 20;
    private localModels: ModelResource[] = []; // 本地存储的模型资源列表

    constructor(private readonly httpService: HttpService,
                private readonly configService: ConfigService,
    ) {
        this.portalLocation = this.configService.get<string>('portalLocation')!;
        this.portalToken = this.configService.get<string>('portalToken')!;
    }

    // 获取单页健康模型的md5列表
    // @param page 页码
    // @param pageSize 每页数量
    private async getHealthyModelMd5List(page: number, pageSize: number): Promise<OnePageMd5Result> {
        const url = `http://${this.portalLocation}/managementSystem/deyployedModel?${this.portalToken}`;

        const body = {
            asc: false,
            page: page,
            pageSize: pageSize,
            searchText: '',
            sortField: 'viewCount'
        }

        // 发送GET请求并接收ResonseEntity
        try {
            // 取Observable第一次输出的值作为Promise结果
            // Observable = 可持续产生数据的“数据流”
            const response = await firstValueFrom(
                this.httpService.post<any>(url, body)
            )

            if (response.status !== 200 || !response.data) {
                this.logger.error(`Failed to fetch data from portal, status: ${response.status}`);
                throw new Error(`Failed to fetch data from portal, status: ${response.status}`);
            }

            const dataNode: PortalMd5Data = response.data.data;
            const md5List = dataNode.content.map((item: Md5Item) => item.md5);

            return {
                totalNumber: dataNode.total,
                md5List: md5List
            };
        } catch (error) {
            this.logger.error(`Error fetching data from portal: ${error}`);
            throw new Error(`Error fetching data from portal: ${error}`);
        }
    }

    // 循环获取门户所有模型的MD5列表
    private async getPortalModelMd5(): Promise<string[]> {
        const pageSize = this.pageSize;
        let onePageMd5 = await this.getHealthyModelMd5List(1, pageSize);
        const modelsMd5List: string[] = [...onePageMd5.md5List];

        const totalModels = onePageMd5.totalNumber;
        const totalPages = Math.ceil(totalModels / pageSize);

        for (let page = 2; page <= totalPages; page++) {
            try {
                onePageMd5 = await this.getHealthyModelMd5List(page, pageSize);
                modelsMd5List.push(...onePageMd5.md5List);
            } catch (error) {
                this.logger.error(`Error fetching data from portal on page ${page}: ${error}`);
                continue;
            }
        }
        return modelsMd5List;
    }

    public async synchronizePortalModels(): Promise<void> {
        const modelsMd5List = await this.getPortalModelMd5();
        const baseUrl = `http://${this.portalLocation}/computableModel/ModelInfoAndClassifications_pid/`;


        // 遍历MD5列表，逐个获取模型详情并保存
        for (const md5 of modelsMd5List) {
            try {
                const detailResponse = await firstValueFrom(
                    this.httpService.get<any>(baseUrl + md5)
                )

                if (detailResponse.status !== 200 || !detailResponse.data) {
                    throw new Error(`Failed to fetch model details for md5 ${md5}, status: ${detailResponse.status}`);
                }

                const modelData = detailResponse.data.data;
                
                const newModel: Partial<ModelResource> = {
                    name: modelData.name,
                    id: modelData.id,
                    description: modelData.overview,
                    author: modelData.author,
                    

                }

            }
        }
    }

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
            this.logger.error(`Resource with id ${id} not found`);
            throw new Error(`Resource with id ${id} not found`);
        }
        return resource;
    }

    // invoke external resource

}
