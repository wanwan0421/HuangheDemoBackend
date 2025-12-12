import { Controller, Post, Get, Query, Param, HttpCode, HttpStatus } from '@nestjs/common';
import { ResourceService } from './resource.service';
import { type ResourceFilter } from './interfaces/resourceFilter.interface';
import { type ResourceItem } from './interfaces/resourceItem.interface';
import { ModelResource } from './entities/modelResource.entity';

@Controller('api/resource')
export class ResourceController {
    constructor(private readonly resourceService: ResourceService) {}

    @Post('synchronizePortalModels')
    @HttpCode(HttpStatus.OK)
    async synchronizePortalModels(): Promise<void> {
        try {
            await this.resourceService.synchronizePortalModels();
        } catch (error) {
            throw new Error(`Failed to synchronize portal resources: ${error.message}`);
        }
    }

    @Get('findModels')
    @HttpCode(HttpStatus.OK)
    async findModels(@Query() filter: ResourceFilter): Promise<ResourceItem[]> {
        const { categoryId, keyword } = filter;
        const categoryIdArray = categoryId ? categoryId.split(',') : [];
        const modelResults = await this.resourceService.findModels({categoryId: categoryIdArray, keyword: keyword});

        const resourceModelList: ResourceItem[] = modelResults.map(item => {
            // 关键词数据清洗
            const keywords = item.mdlJson?.mdl?.enAttr?.keywords;

            let keywordsString: string;

            if (typeof keywords === 'string') {
                keywordsString = keywords;
            } else if ( keywords && typeof keywords === 'object') {
                keywordsString = String(keywords);
            } else {
                keywordsString = '';
            }


            // 统一分隔符
            // 使用正则表达式 /;/g 替换所有分号为逗号; 分割成数组; trim.()清除每个关键词两边的空格; 过滤掉空字符串
            const processedKeywords = keywordsString.replace(/;/g, ',').split(',').map(keyword => keyword.trim()).filter(keyword => keyword.length > 0)

            const dateValue = item.createTime;
            let formattedDate: string;

            if (dateValue) {
                const dateObj = new Date(dateValue);

                if (!isNaN(dateObj.getTime())) {
                    formattedDate = dateObj.toISOString().replace('T', ' ').replace(/\.\d+Z$/, '');
                } else {
                    formattedDate = ''
                }
            } else {
                formattedDate = ''
            }

            return {
                name: item.name,
                description: item?.description ?? '',
                type: item.type,
                author: item?.author ?? '',
                keywords: processedKeywords,
                createdTime: formattedDate
            }
        })

        return resourceModelList;
    } 
}
