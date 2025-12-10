import { Controller, Post, Get, Query, Param, HttpCode, HttpStatus } from '@nestjs/common';
import { ResourceService } from './resource.service';

@Controller('resource')
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
}
