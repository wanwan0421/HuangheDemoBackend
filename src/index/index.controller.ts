import { Get, Controller, HttpCode, HttpStatus, Query } from '@nestjs/common';
import { IndexService } from './index.service';
import { secondIndex } from './interfaces/secondIndex.interface'

@Controller('api/index')
export class IndexController {
    constructor(private readonly indexService: IndexService) {}

    @Get('findIndexs')
    @HttpCode(HttpStatus.OK)
    async findIndexs(): Promise<secondIndex[]> {
        const indexResults: secondIndex[] = await this.indexService.getIndexSystem()

        return indexResults
    }
    
}
