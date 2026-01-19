import { Controller, Query, Param, MessageEvent, Sse } from '@nestjs/common';
import { Observable } from 'rxjs';
import { DataMappingService } from './data-mapping.service';

@Controller('api/data-mapping')
export class DataMappingController {
    constructor(private readonly dataMappingService: DataMappingService) {}

    /**
     * 流式数据扫描，将结果保存到数据库
     */
    @Sse('sessions/:sessionId/data-scan')
    streamWithMemory(
        @Param('sessionId') sessionId: string,
        @Query('filePath') filePath: string,
    ): Observable<MessageEvent> {
        return this.dataMappingService.streamDataScanWithMemory(sessionId, filePath);
    }
}
