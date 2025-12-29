import { Body, Controller, HttpException, HttpStatus, Post, Sse, Query } from '@nestjs/common';
import { LlmAgentService } from './llm-agent.service';
import { Observable } from 'rxjs';

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

    @Sse('chat')
    stream(@Query('query') query: string): Observable<{ data: any }> {
        return this.llmAgentService.getSystemErrorName(query);
    }
}
