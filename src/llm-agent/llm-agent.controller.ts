import { Body, Controller, HttpException, HttpStatus, Post, Get, Query, Res } from '@nestjs/common';
import { LlmAgentService } from './llm-agent.service';
import type { Response } from 'express';

@Controller('api/llm-agent')
export class LlmAgentController {
    constructor(private readonly llmAgentService: LlmAgentService) {}

    @Post('recommendModel')
    async recommendModel(@Body('prompt') prompt: string) {
        if (!prompt) {
            throw new HttpException('Prompt is required', HttpStatus.BAD_REQUEST);
        }

        try {
            const result = await this.llmAgentService.reconmmendModel(prompt);

            if(!result) {
                // 如果没有找到匹配模型，返回一个提示
                return {
                    success: false,
                    message: 'No suitable geographic model found for your request.',
                    data: null
                };
            }

            return {
                success: true,
                data: result
            }
        } catch(error) {
            throw new HttpException(`Agent Error: ${error.message}`, HttpStatus.INTERNAL_SERVER_ERROR);
        }
    }

    @Get('chat')
    async stream(@Query('query') query: string, @Res() res: Response) {
        if (!query) {
            res.status(400).end('Query parameter is required');
            return;
        }

        // SSE headers
        res.setHeader('Content-Type', 'text/event-stream; charset=utf-8');
        res.setHeader('Cache-Control', 'no-cache');
        res.setHeader('Connection', 'keep-alive');

        await this.llmAgentService.pipePythonSSE(query, res);
    }
}
