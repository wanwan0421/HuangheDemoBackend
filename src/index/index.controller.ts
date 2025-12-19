import { Get, Controller, HttpCode, HttpStatus, Query } from '@nestjs/common';
import { IndexService } from './index.service';
import { thirdIndex } from './interfaces/thirdIndex.interface'

@Controller('api/index')
export class IndexController {
    constructor(private readonly indexService: IndexService) {}

    // @Get('findIndexs')
    // @HttpCode(HttpStatus.OK)
    // async findIndexs(): Promise<thirdIndex[]> {
    //     const indexResults: thirdIndex[] = await this.indexService.getIndexSystem()

    //     return indexResults
    // }
    
}
