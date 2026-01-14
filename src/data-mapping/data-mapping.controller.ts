import { Controller, Query, Get, Res } from '@nestjs/common';
import { DataMappingService } from './data-mapping.service';
import type { Response } from 'express';

@Controller('api/data-mapping')
export class DataMappingController {
    constructor(private readonly dataMappingService: DataMappingService) {}

    @Get('data-scan')
    async stream(@Query('filePath') filePath: string, @Query('sessionId') sessionId: string, @Res() res: Response) {
        if (!filePath) {
            res.status(400).end('filePath parameter is required');
            return
        }

        // 设置 SSE 响应头
        res.setHeader('Content-Type', 'text/event-stream');
        res.setHeader('Cache-Control', 'no-cache');
        res.setHeader('Connection', 'keep-alive');
        res.setHeader('X-Accel-Buffering', 'no');

        await this.dataMappingService.pipeAgentDataScanSSE(filePath, res, sessionId);
    }
}
