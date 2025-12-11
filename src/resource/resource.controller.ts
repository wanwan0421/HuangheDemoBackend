import { Controller, Post, Get, Query, Param, HttpCode, HttpStatus } from '@nestjs/common';
import { ResourceService } from './resource.service';
import { type ResourceFilter } from './dto/resourceFilter.dto';
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
    async findModels(@Query() filter: ResourceFilter): Promise<ModelResource[]> {
        const { categoryId, keyword } = filter;
        const categoryIdArray = categoryId ? categoryId.split(',') : [];
        const results = await this.resourceService.findModels({categoryId: categoryIdArray, keyword: keyword});

        return results;
    } 
}
