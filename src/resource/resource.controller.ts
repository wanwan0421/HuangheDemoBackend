import { Controller, Get, Query, Param } from '@nestjs/common';
import { ResourceService } from './resource.service';
import { ResourceDto, ResourceType } from './dto/resource.dto';

@Controller('resource')
export class ResourceController {
    constructor(private readonly resourceService: ResourceService) {}

    // get all resources or by type
    // GET /resources
    // GET /resources?type=MODEL
    @Get()
    findAll(@Query('type') type?: ResourceType): ResourceDto[] {
        return this.resourceService.findAll(type);
    }

    // get resource by id
    // GET /resource/:id
    @Get(':id')
    findOne(@Param('id') id:string): ResourceDto {
        return this.resourceService.findOne(id);
    }
}
